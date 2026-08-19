"""GDELT DOC 2.0 클라이언트 — 뉴스 헤드라인 메타데이터 lane.

권리 (2026-08-19 약관 원문 확보, 등록부 §6.1): GDELT 데이터셋은 "unlimited and
unrestricted use for any academic, commercial, or governmental use … without
fee"이고 재배포·재게시가 명시 허용된다. 조건은 GDELT 인용과 gdeltproject.org
링크뿐 — :data:`GDELT_ATTRIBUTION`이 데이터와 함께 다닌다.

API가 주는 것은 기사 제목·URL·출처 도메인·시각·언어까지다. 본문은 없다 —
그래서 이 lane은 언론사 본문 저작권 문제가 구조적으로 발생하지 않는다.

운영 예절 (2026-08-19~20 실측): 키 없음, **5초당 1요청** 상한이며 위반 시 분
단위 쿨다운이 걸린다. 요청 간격을 6초로 두고, 429는 RateLimited로 올려 배치가
다음 주기로 물러나게 한다. UA는 표준 compatible 봇 형식이어야 한다 — 순수 봇
토큰("Mulmit/1.0")은 WAF가 첫 요청부터 거르고, Googlebot식의 진실한
자기표기("Mozilla/5.0 (compatible; Mulmit/1.0; +https://mulmit.com)")는
통과함을 판별 실험으로 확인했다. 위장이 아니라 관례를 따른 자기소개다.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import threading
import time
from collections.abc import Callable
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import DataUnavailable, RateLimited

GDELT_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# 벌크(15분 익스포트) 채널 — 정적 파일 호스팅이라 대화형 WAF가 없다. AWS IP의
# DOC API 차단(2026-08-20 실측: compatible UA로도 두 사이클 연속 제한)을 겪은 뒤
# GDELT 자신의 권고("switch to bulk")대로 이 경로가 기본 수집로가 됐다.
GDELT_LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GKG_MAX_ZIP_BYTES = 40 * 1024 * 1024
GDELT_PROVIDER_ID = "gdelt"
GDELT_PUBLISHER = "The GDELT Project"
GDELT_PUBLISHER_URL = "https://www.gdeltproject.org/"
GDELT_TERMS_URL = "https://www.gdeltproject.org/about.html"
# 약관이 요구하는 인용 + 링크. UI는 이 문구를 링크와 함께 노출해야 한다.
GDELT_ATTRIBUTION = "News metadata: The GDELT Project (gdeltproject.org)"
GDELT_ATTRIBUTION_KO = "뉴스 메타데이터: The GDELT Project (gdeltproject.org)"

# 표준 compatible 봇 형식 — 실측상 이 형식만 WAF를 통과한다 (모듈 독스트링 참조).
GDELT_USER_AGENT = "Mozilla/5.0 (compatible; Mulmit/1.0; +https://mulmit.com)"

# 실측 상한 5초/1요청에 여유를 둔 기본 간격.
REQUEST_INTERVAL_SECONDS = 6.0

HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _seen_iso(raw: Any) -> str | None:
    """GDELT seendate("20260819T221500Z") → ISO("2026-08-19T22:15:00Z")."""
    text = str(raw or "").strip()
    if len(text) == 16 and text.endswith("Z") and text[8] == "T":
        try:
            moment = dt.datetime.strptime(text, "%Y%m%dT%H%M%SZ")
        except ValueError:
            return None
        return moment.replace(tzinfo=dt.UTC).isoformat().replace("+00:00", "Z")
    return None


class GdeltProvider:
    """작고 예의 바른 DOC 2.0 클라이언트. HTTP 전송은 주입 가능하다."""

    name = GDELT_PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 1,
        retry_backoff: float = 8.0,
        request_interval: float = REQUEST_INTERVAL_SECONDS,
        api_url: str = GDELT_API_URL,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.request_interval = max(0.0, request_interval)
        self.api_url = api_url
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self._throttle_lock = threading.Lock()

    def _throttle(self) -> None:
        if not self.request_interval:
            return
        with self._throttle_lock:
            now = self._monotonic()
            if self._last_request_at is not None:
                waiting = self.request_interval - (now - self._last_request_at)
                if waiting > 0:
                    self._sleep(waiting)
                    now = self._monotonic()
            self._last_request_at = now

    def fetch_articles(
        self,
        query: str,
        *,
        timespan: str = "6h",
        max_records: int = 40,
    ) -> list[dict[str, Any]]:
        """artlist 한 번: [{title, url, domain, seendate, language, country}]."""
        params = urlencode({
            "query": query,
            "mode": "artlist",
            "maxrecords": str(max_records),
            "format": "json",
            "timespan": timespan,
        })
        request = Request(
            f"{self.api_url}?{params}",
            headers={"Accept": "application/json", "User-Agent": GDELT_USER_AGENT},
        )
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                raw = self._http_get(request, self.timeout)
                text = raw.decode("utf-8", errors="replace")
                # 429여도 200 본문으로 안내문이 올 수 있다 — JSON이 아니면 그 경우다.
                if text.lstrip().startswith("Please limit requests"):
                    raise RateLimited("GDELT asked for slower requests")
                payload = json.loads(text)
            except RateLimited:
                raise
            except HTTPError as exc:
                if exc.code == 429:
                    raise RateLimited("GDELT throttled the request") from exc
                if 500 <= exc.code < 600 and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"GDELT HTTP error {exc.code}") from exc
            except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable("GDELT response unusable") from exc

            rows = payload.get("articles") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise DataUnavailable("GDELT returned no article list")
            articles = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").strip()
                url = str(row.get("url") or "").strip()
                seen = _seen_iso(row.get("seendate"))
                if not title or not url or seen is None:
                    continue
                articles.append({
                    "title": title,
                    "url": url,
                    "domain": str(row.get("domain") or "").strip(),
                    "seendate": seen,
                    "language": str(row.get("language") or "").strip(),
                    "country": str(row.get("sourcecountry") or "").strip(),
                })
            return articles
        raise AssertionError("unreachable")

    def _get_bytes(self, url: str, *, limit: int) -> bytes:
        request = Request(url, headers={"User-Agent": GDELT_USER_AGENT})
        self._throttle()
        try:
            raw = self._http_get(request, self.timeout)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise DataUnavailable(f"GDELT file unusable at {url}") from exc
        if len(raw) > limit:
            raise DataUnavailable(f"GDELT file exceeds the {limit}-byte guard")
        return raw

    def fetch_latest_gkg_titles(self) -> list[dict[str, Any]]:
        """최신 15분 GKG 파일에서 (제목, URL, 도메인, 시각)만 뽑는다.

        GKG 2.1 탭 구분 레코드: [1]=DATE(yyyymmddhhmmss), [3]=출처 도메인,
        [4]=문서 URL, 마지막 필드 V2EXTRASXML 안의 <PAGE_TITLE>이 기사 제목이다.
        제목이 없는 레코드는 버린다 — 제목이 이 lane의 존재 이유다.
        """
        import re as _re
        import zipfile

        listing = self._get_bytes(GDELT_LASTUPDATE_URL, limit=64 * 1024).decode(
            "utf-8", errors="replace"
        )
        gkg_url = None
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2].endswith(".gkg.csv.zip"):
                gkg_url = parts[2]
        if not gkg_url:
            raise DataUnavailable("GDELT lastupdate has no gkg file")

        blob = self._get_bytes(gkg_url, limit=GKG_MAX_ZIP_BYTES)
        try:
            archive = zipfile.ZipFile(io.BytesIO(blob))
            name = archive.namelist()[0]
            text = archive.read(name).decode("utf-8", errors="replace")
        except Exception as exc:
            raise DataUnavailable("GDELT gkg archive unreadable") from exc

        title_pattern = _re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", _re.S)
        articles: list[dict[str, Any]] = []
        for line in text.splitlines():
            fields = line.split('	')
            if len(fields) < 5:
                continue
            match = title_pattern.search(fields[-1]) if len(fields) > 5 else None
            if not match:
                continue
            title = match.group(1).strip()
            url = fields[4].strip()
            stamp = fields[1].strip()
            if not title or not url.startswith("http") or len(stamp) != 14 or not stamp.isdigit():
                continue
            seen = (
                f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T"
                f"{stamp[8:10]}:{stamp[10:12]}:{stamp[12:]}Z"
            )
            articles.append({
                "title": title,
                "url": url,
                "domain": fields[3].strip(),
                "seendate": seen,
                "language": "English",
                "country": "",
            })
        return articles
