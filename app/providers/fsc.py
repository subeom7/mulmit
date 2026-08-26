"""Financial Services Commission open data, published through data.go.kr.

The rights position here is the reason this lane exists at all. Korea Exchange
is the origin of these numbers, and the KRX OPEN API terms (see
:mod:`app.providers.krx`) restrict it to non-commercial use and forbid passing
the received information to a third party — which is what Mulmit's public JSON
API would do. That lane is therefore still ``pending_rights``.

The Financial Services Commission receives the same end-of-day data and
republishes it as open data under the Act on Promotion of the Provision and Use
of Public Data. Each of the three datasets below is registered on data.go.kr
with 이용허락범위 **"제한 없음"** — no restriction on use — and 비용 "무료".
That is the widest licence tier the portal issues, and it is the grant Mulmit
relies on. It is a different grant from a KRX agreement, so it is recorded as
its own lane rather than as KRX approval arriving late:

    금융위원회_주식시세정보     https://www.data.go.kr/data/15094808/openapi.do
    금융위원회_지수시세정보     https://www.data.go.kr/data/15094807/openapi.do
    금융위원회_KRX상장종목정보  https://www.data.go.kr/data/15094775/openapi.do

What it costs is freshness. These are end-of-day snapshots published the next
business day at 13:00 KST or later, so Friday's close appears on Monday. Nothing
here is a live quote and nothing built on it may be labelled as one. Real-time
KRX prices remain a separate commercial agreement.

A service key is required. data.go.kr issues it in two forms — an "Encoding" key
that is already percent-encoded and a "Decoding" key that is not — and pasting
the wrong one is the single most common way this API fails, with an
authentication error that says nothing about encoding. :func:`_normalized_key`
accepts either.

:mod:`app.ingest` constructs this for scheduled refreshes. :mod:`app.kr_stocks`
also constructs it for user-initiated cache misses — a stock someone just
searched for cannot wait for the hourly batch — under a process-wide lock and
the same throttle, writing straight back to the store so every later request
reads the database.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request, urlopen

from .base import DataError, DataUnavailable, RateLimited

FSC_API_BASE = "https://apis.data.go.kr/1160100/service"
FSC_PROVIDER_ID = "fsc"
FSC_PUBLISHER = "금융위원회"
FSC_PUBLISHER_EN = "Financial Services Commission"
FSC_PUBLISHER_URL = "https://www.fsc.go.kr/"
FSC_PORTAL_URL = "https://www.data.go.kr/"

# The dataset pages carrying the "이용허락범위 제한 없음" grant this lane relies on.
FSC_STOCK_DATASET_URL = "https://www.data.go.kr/data/15094808/openapi.do"
FSC_INDEX_DATASET_URL = "https://www.data.go.kr/data/15094807/openapi.do"
FSC_LISTED_DATASET_URL = "https://www.data.go.kr/data/15094775/openapi.do"
# 증권상품시세정보(ETF·ETN·ELW). 같은 lane·키·약관 등급 — 활용신청 2026-08-18 승인.
FSC_ETF_DATASET_URL = "https://www.data.go.kr/data/15094806/openapi.do"
FSC_TERMS_URL = FSC_STOCK_DATASET_URL

# Attribution is not demanded by the "no restriction" tier, but naming the
# publisher is how every other lane here behaves and it is what lets a reader
# check the number against its source.
FSC_ATTRIBUTION = "출처: 금융위원회 (공공데이터포털 data.go.kr)"
FSC_ATTRIBUTION_EN = "Source: Financial Services Commission, via data.go.kr."

# Published the next business day at 13:00 KST or later. Stated here so the
# staleness logic and the UI copy quote one number rather than two guesses.
PUBLICATION_LAG_DAYS = 1
PUBLICATION_HOUR_KST = 13

STOCK_ENDPOINT = "GetStockSecuritiesInfoService/getStockPriceInfo"
INDEX_ENDPOINT = "GetMarketIndexInfoService/getStockMarketIndex"
LISTED_ENDPOINT = "GetKrxListedInfoService/getItemInfo"
ETF_ENDPOINT = "GetSecuritiesProductInfoService/getETFPriceInfo"

SUCCESS_CODE = "00"
# Reported inside a 200 body, not as an HTTP status.
_RATE_LIMIT_CODES = frozenset({"22", "336"})
_KEY_ERROR_CODES = frozenset({"30", "31", "20", "23"})

# Sized so the common request fits in one round trip. Five years of daily closes
# is about 1,270 rows, and at 1,000 that was two pages — two round trips of
# roughly three seconds each, which is the whole of the 5.8s a cold
# `/api/kr/stock/{code}` took. Fetching the second page concurrently does not
# help when there are only two: page one has to come back before its count is
# known. Asking for more rows at once does.
#
# This is a bet on what the server allows, and a safe one: if data.go.kr caps
# the page below what is asked, it returns fewer rows and `_paged_rows` walks
# the rest exactly as before.
MAX_ROWS_PER_PAGE = 2000
MAX_PAGES = 40
# How many pages may go out at once after the first. Only matters from three
# pages up — with two, the second still waits for the first either way.
PARALLEL_PAGES = 8


class FscConfigurationError(DataError):
    """The lane was enabled without a data.go.kr service key."""


class FscAuthorizationError(DataError):
    """The key is unregistered, expired, or not approved for this dataset."""


@dataclass(frozen=True)
class FscSeriesSpec:
    """One card fed by one FSC dataset row, selected by an exact identifier."""

    series_key: str
    dataset: str  # "index" or "stock"
    provider_series_id: str  # 지수명 for an index, 단축코드 for a stock
    title: str
    units: str
    units_short: str
    series_url: str
    # Optional 지수분류 pin. Left unset until an ambiguity actually shows up:
    # guessing the classification string would close the lane for no reason,
    # while an unresolved ambiguity is raised rather than silently resolved.
    index_class: str | None = None
    frequency: str = "Daily"
    frequency_short: str = "D"


FSC_SERIES: tuple[FscSeriesSpec, ...] = (
    FscSeriesSpec(
        series_key="kospi_exact",
        dataset="index",
        provider_series_id="코스피",
        title="코스피 지수 종가 (공식)",
        units="Index",
        units_short="pt",
        series_url=FSC_INDEX_DATASET_URL,
    ),
    FscSeriesSpec(
        series_key="kosdaq_exact",
        dataset="index",
        provider_series_id="코스닥",
        title="코스닥 지수 종가 (공식)",
        units="Index",
        units_short="pt",
        series_url=FSC_INDEX_DATASET_URL,
    ),
    FscSeriesSpec(
        series_key="samsung_exact",
        dataset="stock",
        provider_series_id="005930",
        title="삼성전자 종가 (공식)",
        units="KRW",
        units_short="원",
        series_url=FSC_STOCK_DATASET_URL,
    ),
    FscSeriesSpec(
        series_key="sk_hynix_exact",
        dataset="stock",
        provider_series_id="000660",
        title="SK하이닉스 종가 (공식)",
        units="KRW",
        units_short="원",
        series_url=FSC_STOCK_DATASET_URL,
    ),
)

FSC_SERIES_BY_KEY = {spec.series_key: spec for spec in FSC_SERIES}

KR_STOCK_KEY_PREFIX = "kr_stock_"


def stock_series_spec(code: str, name: str = "") -> FscSeriesSpec:
    """Spec for one arbitrary listed stock, keyed ``kr_stock_<code>``.

    The catalogue above is for cards the dashboard always shows; this is for
    whatever the user searched. Same dataset, same parser, same rights.
    """
    code = code.strip().upper()
    if not (4 <= len(code) <= 12) or not code.isalnum():
        raise ValueError("code must be a short alphanumeric KRX issue code")
    return FscSeriesSpec(
        series_key=f"{KR_STOCK_KEY_PREFIX}{code}",
        dataset="stock",
        provider_series_id=code,
        title=(name.strip() or code),
        units="KRW",
        units_short="원",
        series_url=FSC_STOCK_DATASET_URL,
    )

HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _normalized_key(raw: str) -> str:
    """Return the percent-encoded form of either key data.go.kr hands out.

    The portal shows an "Encoding" key (``%2F``, ``%2B``) and a "Decoding" key
    (``/``, ``+``) for the same credential. Encoding an already-encoded key
    turns ``%2F`` into ``%252F`` and the server answers
    ``SERVICE_KEY_IS_NOT_REGISTERED_ERROR`` — an error that points at the key
    rather than at the encoding, which is why this normalises both to one form.
    Decoding first is safe because the issued keys are base64 and never contain
    a literal ``%``.
    """
    return quote(unquote(raw.strip()), safe="")


def _kst_today(now: dt.datetime | None = None) -> dt.date:
    return ((now or dt.datetime.now(dt.UTC)) + dt.timedelta(hours=9)).date()


def _as_rows(items: Any) -> list[dict[str, Any]]:
    """Normalise the three shapes ``items`` takes across data.go.kr responses.

    An empty result set is an empty string rather than an empty object, and a
    single-row result is sometimes an object rather than a one-element list.
    """
    if not isinstance(items, dict):
        return []
    item = items.get("item")
    if isinstance(item, dict):
        return [item]
    if isinstance(item, list):
        return [row for row in item if isinstance(row, dict)]
    return []


def _parse_date(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return dt.date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _positive_or_none(value: float | None) -> float | None:
    return value if value is not None and value > 0 else None


def _parse_number(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


class FscProvider:
    """Retrying JSON client for the FSC end-of-day datasets."""

    name = FSC_PROVIDER_ID

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 20.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        request_interval: float = 0.2,
        api_base: str = FSC_API_BASE,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key.strip():
            raise FscConfigurationError(
                "FSC_API_KEY is required: request the key on data.go.kr for "
                "금융위원회_주식시세정보 and 금융위원회_지수시세정보"
            )
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = _normalized_key(api_key)
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.request_interval = max(0.0, float(request_interval))
        self.api_base = api_base.rstrip("/")
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request = 0.0

    def _throttle(self) -> None:
        if self.request_interval <= 0:
            return
        elapsed = self._monotonic() - self._last_request
        if 0 <= elapsed < self.request_interval:
            self._sleep(self.request_interval - elapsed)
        self._last_request = self._monotonic()

    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        # serviceKey is appended raw: it is already percent-encoded and passing
        # it through urlencode would encode it a second time.
        query = urlencode({**params, "resultType": "json"})
        url = f"{self.api_base}/{endpoint}?serviceKey={self.api_key}&{query}"
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Mulmit/1.0"},
            method="GET",
        )
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                raw = self._http_get(request, self.timeout)
                body = json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("data.go.kr throttled the request") from exc
                raise DataUnavailable(f"FSC HTTP error {exc.code} for {endpoint}") from exc
            except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"Unusable FSC response for {endpoint}") from exc

            if not isinstance(body, dict):
                raise DataUnavailable("FSC response is not an object")
            return self._unwrap(body, endpoint)
        raise AssertionError("unreachable")

    def _unwrap(self, body: dict[str, Any], endpoint: str) -> dict[str, Any]:
        """Return the ``body`` block, translating both error envelopes.

        Gateway-level failures (bad key, quota) arrive as HTTP 200 carrying an
        ``OpenAPI_ServiceResponse`` envelope, while service-level failures use
        the normal envelope with a non-``00`` ``resultCode``. Treating either as
        success would store an error string as if it were a price.
        """
        gateway = body.get("OpenAPI_ServiceResponse")
        if isinstance(gateway, dict):
            header = gateway.get("cmmMsgHeader") or {}
            code = str(header.get("returnReasonCode") or "")
            message = str(header.get("errMsg") or header.get("returnAuthMsg") or code)
            if code in _KEY_ERROR_CODES:
                raise FscAuthorizationError(
                    f"data.go.kr rejected the service key ({message}). Check that the "
                    "key is approved for this dataset and has finished activating."
                )
            if code in _RATE_LIMIT_CODES:
                raise RateLimited(f"data.go.kr request allowance exhausted ({message})")
            raise DataUnavailable(f"FSC gateway error for {endpoint}: {message}")

        response = body.get("response")
        if not isinstance(response, dict):
            raise DataUnavailable(f"FSC response for {endpoint} has no response block")
        header = response.get("header") or {}
        code = str(header.get("resultCode") or "")
        if code != SUCCESS_CODE:
            message = str(header.get("resultMsg") or code)
            if code in _RATE_LIMIT_CODES:
                raise RateLimited(f"data.go.kr request allowance exhausted ({message})")
            if code in _KEY_ERROR_CODES:
                raise FscAuthorizationError(f"data.go.kr rejected the service key ({message})")
            raise DataUnavailable(f"FSC returned resultCode {code} for {endpoint}: {message}")
        payload = response.get("body")
        if not isinstance(payload, dict):
            raise DataUnavailable(f"FSC response for {endpoint} has no body block")
        return payload

    def _page(self, endpoint: str, params: dict[str, str], page: int) -> dict[str, Any]:
        return self._get(
            endpoint,
            {**params, "numOfRows": str(MAX_ROWS_PER_PAGE), "pageNo": str(page)},
        )

    def _paged_rows(
        self, endpoint: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Page 1 tells us how many there are; the rest are fetched together.

        A round trip to this API measures a few seconds, so paging one after
        another put the whole count on the caller's clock — five years of daily
        closes is two pages and cost about 5.8s in production. The page count is
        known after the first response, so the remainder go out at once and the
        wall time is one more round trip rather than N.
        """
        first = self._page(endpoint, params, 1)
        rows = _as_rows(first.get("items"))
        total = _parse_number(first.get("totalCount"))
        if not rows or total is None or len(rows) >= int(total):
            return rows

        # Estimate from what page one actually returned, not from what was
        # asked for: this API is free to hand back fewer rows than numOfRows,
        # and dividing by the request size would then stop short of the total.
        #
        # Capped, because the estimate trusts totalCount: an inflated count
        # would otherwise spend a burst of calls on empty pages, and the daily
        # quota is the scarce thing here. Beyond the cap the walk continues one
        # page at a time and stops the moment a page comes back empty.
        expected = min(MAX_PAGES, PARALLEL_PAGES, -(-int(total) // len(rows)))
        if expected > 1:
            with ThreadPoolExecutor(max_workers=min(8, expected - 1)) as pool:
                futures = [
                    pool.submit(self._page, endpoint, params, page)
                    for page in range(2, expected + 1)
                ]
                # Kept in page order: rows are sorted by date downstream, but a
                # stable order keeps a truncated fetch reproducible.
                for future in futures:
                    rows.extend(_as_rows(future.result().get("items")))

        # If the pages came back smaller than page one, the estimate was short.
        # Fall back to walking the rest one at a time, exactly as before.
        page = expected + 1
        while len(rows) < int(total) and page <= MAX_PAGES:
            page_rows = _as_rows(self._page(endpoint, params, page).get("items"))
            if not page_rows:
                break
            rows.extend(page_rows)
            page += 1
        return rows

    # -- selection ----------------------------------------------------------
    #
    # Both datasets filter with LIKE-style parameters, so the server may return
    # neighbours of what was asked for. Every row is re-checked against the exact
    # identifier here; the request parameter narrows the transfer, it never
    # decides what a number means.

    def _select(
        self, spec: FscSeriesSpec, rows: list[dict[str, Any]]
    ) -> dict[dt.date, float]:
        field = "idxNm" if spec.dataset == "index" else "srtnCd"
        wanted = spec.provider_series_id
        values: dict[dt.date, float] = {}
        conflicts: dict[dt.date, set[str]] = {}

        for row in rows:
            if str(row.get(field) or "").strip() != wanted:
                continue
            if spec.index_class and str(row.get("idxCsf") or "").strip() != spec.index_class:
                continue
            date = _parse_date(row.get("basDt"))
            close = _parse_number(row.get("clpr"))
            if date is None or close is None:
                continue
            previous = values.get(date)
            if previous is not None and previous != close:
                # Two different closes for one identifier on one day means the
                # filter is not unique. Picking one would publish a number whose
                # meaning is unknown, so the series fails instead.
                conflicts.setdefault(date, {str(previous)}).add(str(close))
                continue
            values[date] = close

        if conflicts:
            sample = sorted(conflicts)[0]
            raise DataUnavailable(
                f"FSC returned multiple distinct closes for {wanted} on "
                f"{sample.isoformat()} ({', '.join(sorted(conflicts[sample]))}); "
                "pin index_class before serving this series"
            )
        return values

    def fetch_series(
        self,
        spec: FscSeriesSpec,
        *,
        start: dt.date,
        end: dt.date | None = None,
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        """Return ``(metadata, observations)`` for one card, oldest first."""
        end = end or _kst_today()
        if start > end:
            raise ValueError("start must not be after end")

        window = {"beginBasDt": start.strftime("%Y%m%d"), "endBasDt": end.strftime("%Y%m%d")}
        if spec.dataset == "index":
            endpoint = INDEX_ENDPOINT
            params = {**window, "idxNm": spec.provider_series_id}
        elif spec.dataset == "stock":
            endpoint = STOCK_ENDPOINT
            params = {**window, "likeSrtnCd": spec.provider_series_id}
        else:  # pragma: no cover - guarded by the spec table
            raise ValueError(f"unknown FSC dataset {spec.dataset!r}")

        rows = self._paged_rows(endpoint, params)
        values = self._select(spec, rows)
        observations = tuple(sorted(values.items()))
        if not observations:
            raise DataUnavailable(
                f"FSC returned no rows for {spec.provider_series_id} between "
                f"{window['beginBasDt']} and {window['endBasDt']}"
            )

        return self._series_result(spec, rows, observations, window)

    def _daily_rows(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        field: str,
        wanted: str,
        start: dt.date,
        end: dt.date,
    ) -> list[dict[str, Any]]:
        window = {"beginBasDt": start.strftime("%Y%m%d"), "endBasDt": end.strftime("%Y%m%d")}
        rows = self._paged_rows(endpoint, {**params, **window})
        by_date: dict[dt.date, dict[str, Any]] = {}
        for row in rows:
            if str(row.get(field) or "").strip() != wanted:
                continue
            date = _parse_date(row.get("basDt"))
            close = _parse_number(row.get("clpr"))
            if date is None or close is None:
                continue
            previous = by_date.get(date)
            if previous is not None and previous["close"] != close:
                # _select와 같은 이유: 한 식별자·한 날짜에 서로 다른 종가가 오면
                # 필터가 유일하지 않은 것이다. 하나를 고르면 뜻 모를 수가 나간다.
                raise DataUnavailable(
                    f"FSC returned multiple distinct closes for {wanted} on {date.isoformat()}"
                )
            by_date[date] = {
                "date": date,
                "close": close,
                "vs": _parse_number(row.get("vs")),
                "flt_rt": _parse_number(row.get("fltRt")),
                "volume": _parse_number(row.get("trqu")),
            }
        return [by_date[key] for key in sorted(by_date)]

    def fetch_stock_rows(
        self, code: str, *, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        """한 종목의 일별 원시 행(종가·대비·등락률·거래량), 오래된 날짜부터.

        fetch_series와 달리 fltRt·trqu를 버리지 않는다 — 채점 lane이
        (1+fltRt) 연쇄곱(분할·권리락 안전)과 거래정지 감지(trqu 0)를 이 두
        필드에서 읽는다. 실측 근거는 `docs/PLAN_SCORING.md` §1.
        """
        code = code.strip().upper()
        return self._daily_rows(
            STOCK_ENDPOINT,
            {"likeSrtnCd": code},
            field="srtnCd",
            wanted=code,
            start=start,
            end=end,
        )

    def fetch_index_rows(
        self, idx_nm: str, *, start: dt.date, end: dt.date
    ) -> list[dict[str, Any]]:
        """한 지수의 일별 원시 행 — 채점 벤치마크(코스피/코스닥)용."""
        return self._daily_rows(
            INDEX_ENDPOINT,
            {"idxNm": idx_nm},
            field="idxNm",
            wanted=idx_nm,
            start=start,
            end=end,
        )

    def fetch_day_snapshot(
        self, *, max_probe_days: int = 10
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return ``(bas_dt, rows)`` for the most recent published trading day.

        One day of the stock dataset is the whole exchange — every listed
        issue's code, name, market, close and market cap — which doubles as the
        search roster. The latest day is probed rather than assumed because
        publication is T+1 13:00 KST and holidays stretch the gap.
        """
        day = _kst_today()
        for _ in range(max_probe_days):
            probe = self._get(
                STOCK_ENDPOINT,
                {"basDt": day.strftime("%Y%m%d"), "numOfRows": "1", "pageNo": "1"},
            )
            total = _parse_number(probe.get("totalCount"))
            if total and total > 0:
                break
            day -= dt.timedelta(days=1)
        else:
            raise DataUnavailable(
                f"FSC published no trading day in the last {max_probe_days} days"
            )

        rows = self._paged_rows(STOCK_ENDPOINT, {"basDt": day.strftime("%Y%m%d")})
        snapshot = []
        for row in rows:
            code = str(row.get("srtnCd") or "").strip()
            name = str(row.get("itmsNm") or "").strip()
            if not code or not name:
                continue
            snapshot.append({
                "srtn_cd": code,
                "itms_nm": name,
                "mrkt_ctg": str(row.get("mrktCtg") or "").strip(),
                "isin_cd": str(row.get("isinCd") or "").strip(),
                "clpr": _parse_number(row.get("clpr")),
                "flt_rt": _parse_number(row.get("fltRt")),
                "mrkt_tot_amt": _parse_number(row.get("mrktTotAmt")),
            })
        if not snapshot:
            raise DataUnavailable("FSC day snapshot parsed to zero usable rows")
        return day.strftime("%Y-%m-%d"), snapshot

    def fetch_index_day_snapshot(
        self, *, max_probe_days: int = 10
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return ``(bas_dt, rows)`` for every index on the latest trading day.

        One request covers the whole set (~170 indices) and each row already
        carries the day change, the year-to-date change, the 52-week high and
        low with their dates, volume and traded value — the entire statistics
        table, without collecting a single history series.
        """
        day = _kst_today()
        for _ in range(max_probe_days):
            probe = self._get(
                INDEX_ENDPOINT,
                {"basDt": day.strftime("%Y%m%d"), "numOfRows": "1", "pageNo": "1"},
            )
            total = _parse_number(probe.get("totalCount"))
            if total and total > 0:
                break
            day -= dt.timedelta(days=1)
        else:
            raise DataUnavailable(
                f"FSC published no index trading day in the last {max_probe_days} days"
            )

        rows = self._paged_rows(INDEX_ENDPOINT, {"basDt": day.strftime("%Y%m%d")})
        snapshot = []
        for row in rows:
            name = str(row.get("idxNm") or "").strip()
            if not name:
                continue
            snapshot.append({
                "idx_nm": name,
                "idx_csf": str(row.get("idxCsf") or "").strip(),
                "clpr": _parse_number(row.get("clpr")),
                "vs": _parse_number(row.get("vs")),
                "flt_rt": _parse_number(row.get("fltRt")),
                "ls_yr_flt_rt": _parse_number(row.get("lsYrEdVsFltRt")),
                # The dataset publishes an unfinalised 52-week low as 0 with a
                # future date. An index cannot be 0, so 0 means "not a value".
                "yr_hgst": _positive_or_none(_parse_number(row.get("yrWRcrdHgst"))),
                "yr_hgst_dt": str(row.get("yrWRcrdHgstDt") or "").strip() or None,
                "yr_lwst": _positive_or_none(_parse_number(row.get("yrWRcrdLwst"))),
                "yr_lwst_dt": str(row.get("yrWRcrdLwstDt") or "").strip() or None,
                "trqu": _parse_number(row.get("trqu")),
                "tr_prc": _parse_number(row.get("trPrc")),
                "lstg_mrkt_tot_amt": _parse_number(row.get("lstgMrktTotAmt")),
            })
        if not snapshot:
            raise DataUnavailable("FSC index snapshot parsed to zero usable rows")
        return day.strftime("%Y-%m-%d"), snapshot

    def fetch_etf_day_snapshot(
        self, *, max_probe_days: int = 10
    ) -> tuple[str, list[dict[str, Any]]]:
        """Return ``(bas_dt, rows)`` for every listed ETF on the latest trading day.

        One day of the securities-product dataset is the whole ETF board —
        close, day change, NAV, traded value, market cap and the underlying
        index name — so a premium/discount against NAV can be shown from two
        published same-day values without collecting any history.
        """
        day = _kst_today()
        for _ in range(max_probe_days):
            probe = self._get(
                ETF_ENDPOINT,
                {"basDt": day.strftime("%Y%m%d"), "numOfRows": "1", "pageNo": "1"},
            )
            total = _parse_number(probe.get("totalCount"))
            if total and total > 0:
                break
            day -= dt.timedelta(days=1)
        else:
            raise DataUnavailable(
                f"FSC published no ETF trading day in the last {max_probe_days} days"
            )

        rows = self._paged_rows(ETF_ENDPOINT, {"basDt": day.strftime("%Y%m%d")})
        snapshot = []
        for row in rows:
            code = str(row.get("srtnCd") or "").strip()
            name = str(row.get("itmsNm") or "").strip()
            if not code or not name:
                continue
            snapshot.append({
                "srtn_cd": code,
                "itms_nm": name,
                "clpr": _parse_number(row.get("clpr")),
                "vs": _parse_number(row.get("vs")),
                "flt_rt": _parse_number(row.get("fltRt")),
                # NAV가 아직 산출되지 않은 신규 상장분은 0으로 온다. 0 NAV는
                # 값이 아니므로 결측으로 다룬다 — 괴리율이 무한대가 되면 안 된다.
                "nav": _positive_or_none(_parse_number(row.get("nav"))),
                "trqu": _parse_number(row.get("trqu")),
                "tr_prc": _parse_number(row.get("trPrc")),
                "mrkt_tot_amt": _parse_number(row.get("mrktTotAmt")),
                "n_ppt_tot_amt": _parse_number(row.get("nPptTotAmt")),
                "bss_idx_idx_nm": str(row.get("bssIdxIdxNm") or "").strip() or None,
                "bss_idx_clpr": _parse_number(row.get("bssIdxClpr")),
            })
        if not snapshot:
            raise DataUnavailable("FSC ETF snapshot parsed to zero usable rows")
        return day.strftime("%Y-%m-%d"), snapshot

    def _series_result(
        self,
        spec: FscSeriesSpec,
        rows: list[dict[str, Any]],
        observations: tuple[tuple[dt.date, float], ...],
        window: dict[str, str],
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        # Names come from the data rather than the spec where the data has them,
        # so a renamed listing shows up instead of being papered over.
        latest_row = next(
            (
                row
                for row in reversed(rows)
                if _parse_date(row.get("basDt")) == observations[-1][0]
            ),
            {},
        )
        official_name = str(
            latest_row.get("itmsNm") if spec.dataset == "stock" else latest_row.get("idxNm") or ""
        ).strip()

        metadata = {
            "title": spec.title,
            "units": spec.units,
            "units_short": spec.units_short,
            "frequency": spec.frequency,
            "frequency_short": spec.frequency_short,
            "seasonal_adjustment": "Not Applicable",
            "seasonal_adjustment_short": "NA",
            "observation_start": observations[0][0].isoformat(),
            "observation_end": observations[-1][0].isoformat(),
            "last_updated": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "notes": (
                f"{official_name or spec.provider_series_id} · "
                "장 마감 기준값이며 실시간 시세가 아닙니다. "
                "기준일 다음 영업일 13시 이후 공개됩니다."
            ),
        }
        return metadata, observations
