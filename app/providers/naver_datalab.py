"""네이버 데이터랩 통합검색어 트렌드 — 종목 검색 관심도의 상류.

권리 판정(docs/DATA_SOURCE_REGISTER.md §6.7, 2026-08-23): **데이터랩에는 개별 API
특약이 없다.** 뉴스 검색을 기각시킨 검색 API 특약(독립 노출·삽입 금지·무조건 저장
금지·검색결과 페이지 광고 금지)이 여기에는 적용되지 않는다. 근거 셋 —
① 국문 원본 `AI·Naver API 서비스 이용약관 v6.0`(2025-03-20, 현행)의 개별 API 특약은
지도·파파고·CLOVA 셋뿐이고 `데이터랩`·`검색`·`광고`·`캐싱` 어느 낱말도 없다.
② 2026-08-20 개정 공지(시행 2026-09-20)는 "B. 개별 API별 특약조건" 아래
**"2. 네이버 검색 API 서비스" 조항 하나**만 고친다고 못박는다.
③ 콘솔의 API 카탈로그가 **Data Lab**(쇼핑인사이트·검색어트렌드)과 **NAVER 검색**
(뉴스·블로그·지역 등 10종)을 제품 수준에서 갈라 놓는다.

**저장하지 않는다.** 일반조건은 결과 데이터를 "허용 범위를 초과하여" 복제·저장·
가공·배포하는 것을 금지하는데, 그 판단을 아예 마주치지 않는 자리에 선다 — 이 API는
요청마다 조회 기간 전체의 시계열을 통째로 돌려주므로 이력 blob을 만들 이유가 없다.
여기 있는 것은 같은 화면을 두 번 그릴 때 상류를 두 번 때리지 않기 위한 TTL 캐시
하나뿐이고, 디스크에도 DB에도 남지 않는다.

값의 성질(공식 문서 원문): "요청된 기간 중 검색 횟수가 **가장 높은 시점을 100**으로
두고 나머지는 상대적 값으로 제공", "검색 횟수의 **절댓값 제공은 아직 고려하고 있지
않습니다**". 따라서 **정규화가 요청 단위**다 — 종목 A를 혼자 조회한 100과 종목 B를
혼자 조회한 100은 같은 크기가 아니다. 한 요청에 함께 넣은 그룹끼리만 비교할 수 있다.
이 함정은 상류의 성질이라 여기서 고칠 수 없고, 부르는 쪽(`kr_search_interest`)이
같은 요청 안에서만 비교하도록 설계돼 있다.

쿼터: NCP API HUB 구독 실측 **월 50,000회 · 일 한도 없음**(구 개발자센터는 일 1,000회).
게이트 `NAVER_DATALAB_ENABLED` + 클라이언트 아이디/시크릿.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import DataUnavailable, RateLimited
from .http_cache import TtlCache

DATALAB_PROVIDER_ID = "naver_datalab"
DATALAB_PUBLISHER = "네이버 데이터랩"
DATALAB_PUBLISHER_EN = "NAVER DataLab"
DATALAB_PUBLISHER_URL = "https://datalab.naver.com/"
DATALAB_TREND_URL = "https://openapi.naver.com/v1/datalab/search"
DATALAB_DOCS_URL = "https://developers.naver.com/docs/serviceapi/datalab/search/search.md"
DATALAB_TERMS_URL = "https://www.ncloud.com/policy/terms/opapi"
DATALAB_ATTRIBUTION = "네이버 데이터랩 검색어 트렌드"
DATALAB_ATTRIBUTION_EN = "NAVER DataLab search trends"

# 문서 원문의 상한. 넘겨 보내면 상류가 거절한다 — 여기서 먼저 막는다.
MAX_GROUPS = 5
MAX_KEYWORDS_PER_GROUP = 20
EARLIEST_DATE = dt.date(2016, 1, 1)
TIME_UNITS = ("date", "week", "month")

# 값은 하루 단위로만 바뀐다. 짧은 TTL은 쿼터만 태우고 새 값을 주지 않는다.
DEFAULT_TTL = 6 * 60 * 60.0
DEFAULT_STALE_TTL = 24 * 60 * 60.0
DEFAULT_TIMEOUT = 8.0
DEFAULT_RETRIES = 1
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

Transport = Callable[[str, bytes, dict[str, str], float], Any]


class DatalabConfigError(RuntimeError):
    """키가 없다. 게이트가 열려 있어도 부를 수 없다."""


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _default_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def build_request(
    groups: list[tuple[str, list[str]]],
    *,
    start: dt.date,
    end: dt.date,
    time_unit: str = "date",
) -> dict[str, Any]:
    """요청 본문을 만들면서 문서의 상한을 강제한다.

    상류가 조용히 잘라 내는 게 아니라 400으로 되돌려 주므로, 여기서 걸러야 어느
    종목이 빠졌는지 알 수 있다.
    """
    if not groups:
        raise ValueError("at least one keyword group is required")
    if len(groups) > MAX_GROUPS:
        raise ValueError(f"데이터랩은 한 요청에 주제어 {MAX_GROUPS}개까지만 받는다 (요청 {len(groups)}개)")
    if time_unit not in TIME_UNITS:
        raise ValueError(f"time_unit must be one of {TIME_UNITS}")
    if start < EARLIEST_DATE:
        raise ValueError(f"데이터랩은 {EARLIEST_DATE.isoformat()}부터 조회할 수 있다")
    if end < start:
        raise ValueError("end must not precede start")

    payload_groups = []
    for name, keywords in groups:
        cleaned = [str(word).strip() for word in keywords if str(word).strip()]
        if not name.strip() or not cleaned:
            raise ValueError("주제어와 검색어가 모두 있어야 한다")
        if len(cleaned) > MAX_KEYWORDS_PER_GROUP:
            raise ValueError(
                f"주제어 하나에 검색어 {MAX_KEYWORDS_PER_GROUP}개까지다 ('{name}' {len(cleaned)}개)"
            )
        payload_groups.append({"groupName": name.strip(), "keywords": cleaned})

    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": time_unit,
        "keywordGroups": payload_groups,
    }


def parse_trend(raw: Any, *, fetched_at: str) -> dict[str, Any]:
    """응답에서 쓰는 것만 남긴다. 읽을 수 없는 행은 지어내지 않고 버린다.

    비율은 **요청 안에서만** 뜻이 있으므로 요청 서명(기간·단위)을 함께 남긴다 —
    나중에 두 응답을 섞어 비교하려는 코드가 있으면 여기서 걸리게 하기 위해서다.
    """
    if not isinstance(raw, dict):
        raise DataUnavailable("데이터랩이 사전이 아닌 응답을 돌려주었다")
    results = raw.get("results")
    if not isinstance(results, list) or not results:
        raise DataUnavailable("데이터랩 응답에 results가 없다")

    groups: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        rows = item.get("data")
        if not title or not isinstance(rows, list):
            continue
        series: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            period = str(row.get("period") or "").strip()
            try:
                ratio = float(row.get("ratio"))
            except (TypeError, ValueError):
                continue
            if not period or ratio != ratio:  # NaN
                continue
            series.append({"period": period, "ratio": ratio})
        if not series:
            continue
        series.sort(key=lambda point: point["period"])
        keywords = item.get("keywords")
        groups.append(
            {
                "title": title,
                "keywords": [str(word) for word in keywords] if isinstance(keywords, list) else [],
                "series": series,
            }
        )

    if not groups:
        raise DataUnavailable("데이터랩이 읽을 수 있는 계열을 하나도 주지 않았다")

    return {
        "fetched_at": fetched_at,
        "start_date": str(raw.get("startDate") or ""),
        "end_date": str(raw.get("endDate") or ""),
        "time_unit": str(raw.get("timeUnit") or ""),
        "groups": groups,
    }


class DatalabProvider:
    """검색어 트렌드 한 묶음을 받아 온다. 단일 비행 TTL 캐시, 저장 없음."""

    name = DATALAB_PROVIDER_ID

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        ttl: float = DEFAULT_TTL,
        stale_ttl: float = DEFAULT_STALE_TTL,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client_id = str(client_id or "").strip()
        self.client_secret = str(client_secret or "").strip()
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep
        self._cache = TtlCache(ttl=ttl, stale_ttl=stale_ttl)

    def clear_cache(self) -> None:
        self._cache.clear()

    def fetch_trend(
        self,
        groups: list[tuple[str, list[str]]],
        *,
        start: dt.date,
        end: dt.date,
        time_unit: str = "date",
    ) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise DatalabConfigError("네이버 데이터랩 클라이언트 아이디/시크릿이 없다")
        body = build_request(groups, start=start, end=end, time_unit=time_unit)
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        # 캐시 열쇠는 요청 그 자체다. 기간이나 종목 묶음이 다르면 다른 응답이고,
        # 비율은 요청 안에서만 뜻이 있어 섞으면 안 된다.
        key = json.dumps(body, ensure_ascii=False, sort_keys=True)

        def load() -> dict[str, Any]:
            raw = self._request(encoded)
            return parse_trend(raw, fetched_at=_utc_iso(self._wall_clock()))

        return self._cache.fetch(key, load, label="NAVER DataLab trend")

    def _request(self, body: bytes) -> Any:
        headers = {
            "X-Naver-Client-Id": self.client_id,
            "X-Naver-Client-Secret": self.client_secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._transport(DATALAB_TREND_URL, body, headers, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    if attempt >= self.retries:
                        raise RateLimited("데이터랩 호출 한도에 걸렸다") from exc
                elif exc.code in (401, 403):
                    # 키 문제는 재시도해도 같다. 쿼터만 태운다.
                    raise DataUnavailable(f"데이터랩이 인증을 거절했다 (HTTP {exc.code})") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(f"데이터랩이 요청을 거절했다 (HTTP {exc.code})") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("데이터랩이 읽을 수 없는 응답을 돌려주었다") from exc
            if attempt < self.retries:
                self._sleep(min(0.3 * (2**attempt), 1.0))
        raise DataUnavailable("데이터랩 검색어 트렌드를 받을 수 없다") from last_error
