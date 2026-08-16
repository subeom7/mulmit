"""Read-only client for the official KRX Data Marketplace OPEN API.

The three endpoints in this module come from the development specifications
published by Korea Exchange on 2026-01-16.  They are end-of-day snapshots: one
request returns every row for a single ``basDd`` date.  Callers should therefore
store a daily snapshot and select instruments locally instead of making one
request per ticker.

Important usage boundary (KRX OPEN API Terms effective 2025-12-26): the OPEN API
is limited to non-commercial use, received information may not be provided to a
third party, and screens built from it must identify the result as using
``한국거래소 통계정보``.  An issued key and separate approval for each API are
required before use.  Public/commercial redistribution needs a separate KRX
market-data agreement; merely possessing an OPEN API key is not that agreement.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from collections.abc import Callable, Iterable, Mapping
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import DataError, DataUnavailable, RateLimited

KRX_API_BASE = "https://data-dbg.krx.co.kr/svc/apis"
KRX_OPEN_API_HOME = "https://openapi.krx.co.kr/"
KRX_TERMS_URL = "https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO002.jsp"
KRX_USAGE_GUIDE_URL = "https://openapi.krx.co.kr/contents/OPP/INFO/OPPINFO003.jsp"
KRX_REQUIRED_ATTRIBUTION = "한국거래소 통계정보"

# Official API IDs and server paths from the downloadable KRX specifications.
KOSPI_STOCK_ENDPOINT = "sto/stk_bydd_trd"
KOSPI_INDEX_ENDPOINT = "idx/kospi_dd_trd"
KOSDAQ_INDEX_ENDPOINT = "idx/kosdaq_dd_trd"

DASHBOARD_STOCK_CODES = {
    "samsung_electronics": "005930",
    "sk_hynix": "000660",
}
DASHBOARD_INDEX_NAMES = {
    "kospi": ("코스피", "KOSPI"),
    "kosdaq": ("코스닥", "KOSDAQ"),
}

_STOCK_FIELDS = frozenset(
    {
        "BAS_DD",
        "ISU_CD",
        "ISU_NM",
        "MKT_NM",
        "SECT_TP_NM",
        "TDD_CLSPRC",
        "CMPPREVDD_PRC",
        "FLUC_RT",
        "TDD_OPNPRC",
        "TDD_HGPRC",
        "TDD_LWPRC",
        "ACC_TRDVOL",
        "ACC_TRDVAL",
        "MKTCAP",
        "LIST_SHRS",
    }
)
_INDEX_FIELDS = frozenset(
    {
        "BAS_DD",
        "IDX_CLSS",
        "IDX_NM",
        "CLSPRC_IDX",
        "CMPPREVDD_IDX",
        "FLUC_RT",
        "OPNPRC_IDX",
        "HGPRC_IDX",
        "LWPRC_IDX",
        "ACC_TRDVOL",
        "ACC_TRDVAL",
        "MKTCAP",
    }
)

HttpGet = Callable[[Request, float], bytes]


class KrxConfigurationError(DataError):
    """The official KRX provider was enabled without an issued API key."""


class KrxAuthorizationError(DataError):
    """The key is invalid or the requested KRX API has not been approved."""


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _normalized_name(value: Any) -> str:
    return "".join(str(value).split()).casefold()


def find_issue(
    rows: Iterable[Mapping[str, Any]], issue_code: str
) -> dict[str, Any] | None:
    """Return a defensive copy of one exact six-digit KRX issue-code row."""

    normalized_code = issue_code.strip()
    if len(normalized_code) != 6 or not normalized_code.isdigit():
        raise ValueError("issue_code must be a six-digit KRX short code")
    for row in rows:
        if str(row.get("ISU_CD", "")).strip() == normalized_code:
            return dict(row)
    return None


def find_index(
    rows: Iterable[Mapping[str, Any]], names: Iterable[str]
) -> dict[str, Any] | None:
    """Find an index by an explicit Korean or English name, ignoring whitespace/case."""

    expected = {_normalized_name(name) for name in names if str(name).strip()}
    if not expected:
        raise ValueError("at least one non-empty index name is required")
    for row in rows:
        if _normalized_name(row.get("IDX_NM", "")) in expected:
            return dict(row)
    return None


class KrxProvider:
    """Small retrying client for approved KRX end-of-day snapshot APIs."""

    name = "krx"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        api_base: str = KRX_API_BASE,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise KrxConfigurationError(
                "KRX_API_KEY is required and each KRX API must be approved before use"
            )
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.api_base = api_base.rstrip("/")
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep

    def _request_rows(
        self,
        endpoint: str,
        bas_date: dt.date,
        required_fields: frozenset[str],
    ) -> tuple[dict[str, Any], ...]:
        if not isinstance(bas_date, dt.date):
            raise TypeError("bas_date must be datetime.date")

        query = urlencode({"basDd": bas_date.strftime("%Y%m%d")})
        request = Request(
            f"{self.api_base}/{endpoint}?{query}",
            headers={
                "Accept": "application/json",
                "AUTH_KEY": self.api_key,
                "User-Agent": "Mulmit/1.0",
            },
            method="GET",
        )

        for attempt in range(self.retries + 1):
            try:
                raw = self._http_get(request, self.timeout)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("response root is not an object")
                raw_rows = payload.get("OutBlock_1")
                if not isinstance(raw_rows, list):
                    raise ValueError("OutBlock_1 is missing or is not an array")

                rows: list[dict[str, Any]] = []
                for raw_row in raw_rows:
                    if not isinstance(raw_row, dict):
                        raise ValueError("OutBlock_1 contains a non-object row")
                    missing = required_fields.difference(raw_row)
                    if missing:
                        raise ValueError(
                            "OutBlock_1 row is missing documented fields: "
                            + ", ".join(sorted(missing))
                        )
                    rows.append(dict(raw_row))
                return tuple(rows)
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    raise KrxAuthorizationError(
                        "KRX rejected the key or this API has not been approved"
                    ) from exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("KRX OPEN API request limit reached") from exc
                raise DataUnavailable(
                    f"KRX OPEN API HTTP error {exc.code} for {endpoint}"
                ) from exc
            except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError, ValueError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(
                    f"Invalid or unavailable KRX response for {endpoint}"
                ) from exc

        raise AssertionError("unreachable")

    def fetch_kospi_stocks(self, bas_date: dt.date) -> tuple[dict[str, Any], ...]:
        """Return all KOSPI-listed stock rows for one official business date."""

        return self._request_rows(KOSPI_STOCK_ENDPOINT, bas_date, _STOCK_FIELDS)

    def fetch_kospi_indices(self, bas_date: dt.date) -> tuple[dict[str, Any], ...]:
        """Return the complete KOSPI index-series snapshot for one date."""

        return self._request_rows(KOSPI_INDEX_ENDPOINT, bas_date, _INDEX_FIELDS)

    def fetch_kosdaq_indices(self, bas_date: dt.date) -> tuple[dict[str, Any], ...]:
        """Return the complete KOSDAQ index-series snapshot for one date."""

        return self._request_rows(KOSDAQ_INDEX_ENDPOINT, bas_date, _INDEX_FIELDS)
