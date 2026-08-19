"""한국은행 경제통계시스템(ECOS) OpenAPI 클라이언트 — 한국 거시 lane.

미국 FRED lane의 한국 대칭이다. v1 시리즈는 실측으로 코드가 검증된 둘:
기준금리(722Y001/0101000, 월), 소비자물가지수 총지수(901Y009/0, 2020=100, 월),
실업률(901Y027/I61BC, %, 월).

권리: 인증키 발급 시 동의하는 이용약관이 근거 문서다. 약관 전문이 확인·기록될
때까지 lane 게이트(ECOS_ENABLED)는 꺼진 채 배포된다 — fail-closed. 출처표시
문구는 :data:`ECOS_ATTRIBUTION`으로 데이터와 함께 다닌다.

값은 ECOS가 준 그대로 전달한다. DATA_VALUE가 빈 문자열인 달은 결측으로
남기고 0으로 채우지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import DataUnavailable, RateLimited

ECOS_API_BASE = "https://ecos.bok.or.kr/api"
ECOS_SITE_URL = "https://ecos.bok.or.kr/"
ECOS_PROVIDER_ID = "ecos"
ECOS_PUBLISHER = "한국은행"
ECOS_PUBLISHER_EN = "Bank of Korea"
ECOS_PUBLISHER_URL = ECOS_SITE_URL
ECOS_TERMS_URL = "https://ecos.bok.or.kr/api/"  # 약관은 인증키 신청 화면에서 노출된다
ECOS_ATTRIBUTION = "출처: 한국은행 경제통계시스템(ECOS)"
ECOS_ATTRIBUTION_EN = "Source: Bank of Korea Economic Statistics System (ECOS)"

# 한 번에 받는 최대 행 수. 월 주기 10년치(120행)를 넉넉히 덮는다.
MAX_ROWS = 1200


@dataclass(frozen=True)
class EcosSeriesSpec:
    """수집 대상 시리즈 하나. 코드는 전부 라이브 검증 후에만 넣는다."""

    series_key: str
    stat_code: str
    item_code: str
    cycle: str  # 현재 "M"만 지원
    units: str
    units_short: str
    frequency: str
    frequency_short: str
    title: str
    title_en: str


ECOS_SERIES: tuple[EcosSeriesSpec, ...] = (
    EcosSeriesSpec(
        series_key="kr_base_rate",
        stat_code="722Y001",
        item_code="0101000",
        cycle="M",
        units="연%",
        units_short="%",
        frequency="Monthly",
        frequency_short="M",
        title="한국은행 기준금리",
        title_en="Bank of Korea Base Rate",
    ),
    EcosSeriesSpec(
        series_key="kr_unemployment",
        stat_code="901Y027",
        item_code="I61BC",
        cycle="M",
        units="%",
        units_short="%",
        frequency="Monthly",
        frequency_short="M",
        title="실업률",
        title_en="Unemployment Rate (Korea)",
    ),
    EcosSeriesSpec(
        series_key="kr_cpi",
        stat_code="901Y009",
        item_code="0",
        cycle="M",
        units="2020=100",
        units_short="2020=100",
        frequency="Monthly",
        frequency_short="M",
        title="소비자물가지수 (총지수)",
        title_en="Consumer Price Index (All items)",
    ),
)

ECOS_SERIES_BY_KEY = {spec.series_key: spec for spec in ECOS_SERIES}

HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _month_date(raw: Any) -> dt.date | None:
    text = str(raw or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    year, month = int(text[:4]), int(text[4:])
    try:
        return dt.date(year, month, 1)
    except ValueError:
        return None


def _number(raw: Any) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    try:
        value = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class EcosProvider:
    """작고 재시도하는 ECOS 클라이언트. HTTP 전송은 주입 가능하다."""

    name = ECOS_PROVIDER_ID

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        request_interval: float = 0.2,
        api_base: str = ECOS_API_BASE,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        key = str(api_key or "").strip()
        if not key:
            raise ValueError("ECOS api_key is required")
        self.api_key = key
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.request_interval = max(0.0, request_interval)
        self.api_base = api_base.rstrip("/")
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

    def _request_json(self, url: str) -> Any:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "Mulmit/1.0"})
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                raw = self._http_get(request, self.timeout)
                return json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("ECOS throttled the request") from exc
                raise DataUnavailable(f"ECOS HTTP error {exc.code}") from exc
            except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable("ECOS response unusable") from exc
        raise AssertionError("unreachable")

    def fetch_series(
        self,
        spec: EcosSeriesSpec,
        *,
        start: dt.date,
        end: dt.date | None = None,
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        """Return ``(metadata, observations)`` sorted oldest first."""
        if spec.cycle != "M":
            raise ValueError(f"unsupported ECOS cycle: {spec.cycle}")
        end = end or dt.date.today()
        if end < start:
            raise ValueError("end must not precede start")
        url = (
            f"{self.api_base}/StatisticSearch/{self.api_key}/json/kr/1/{MAX_ROWS}/"
            f"{spec.stat_code}/{spec.cycle}/{start.strftime('%Y%m')}/{end.strftime('%Y%m')}/"
            f"{spec.item_code}"
        )
        payload = self._request_json(url)
        if not isinstance(payload, dict):
            raise DataUnavailable("ECOS returned a non-object payload")
        # 오류는 200 응답의 RESULT 봉투로 온다. INFO-200(데이터 없음)도 여기 속한다.
        result = payload.get("RESULT")
        if isinstance(result, dict):
            code = str(result.get("CODE") or "")
            message = str(result.get("MESSAGE") or "")
            raise DataUnavailable(f"ECOS error {code}: {message}")
        body = payload.get("StatisticSearch")
        rows = body.get("row") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise DataUnavailable(f"ECOS returned no rows for {spec.stat_code}")

        values: dict[dt.date, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            date = _month_date(row.get("TIME"))
            value = _number(row.get("DATA_VALUE"))
            # 발표 전이거나 결측인 달은 그대로 결측 — 0으로 채우지 않는다.
            if date is not None and value is not None:
                values[date] = value

        observations = tuple(sorted(values.items()))
        if not observations:
            raise DataUnavailable(f"ECOS returned no usable observations for {spec.stat_code}")
        metadata = {
            "title": spec.title,
            "units": spec.units,
            "units_short": spec.units_short,
            "frequency": spec.frequency,
            "frequency_short": spec.frequency_short,
            "observation_start": observations[0][0].isoformat(),
            "observation_end": observations[-1][0].isoformat(),
            "last_updated": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "notes": "",
        }
        return metadata, observations
