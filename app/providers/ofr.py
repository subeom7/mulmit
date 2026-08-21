"""Office of Financial Research (U.S. Treasury) — Financial Stress Index.

The OFR FSI is a daily, market-based snapshot of stress in global financial
markets built from 33 variables, published as a composite plus five category
contributions (credit, equity valuation, funding, safe assets, volatility).
It is the rights-clean answer to two cards this project cannot license: the
volatility category carries the implied/realised-volatility family (VIX et
al.), the credit category the spread family (high-yield OAS et al.).

Rights position (Legal Notices, read 2026-08-21):

    "No copyright may be claimed for any work on this website that was created
    by a federal employee in the course of his or her duties. However, credit
    is requested if you reproduce or copy any such work."

    "Federal law prohibits use of any symbol, emblem, seal, insignia, or badge
    of any entity of the Department of Treasury ..."

    https://www.financialresearch.gov/legal-notices/

So: a federal work (public domain), credit requested — the page's suggested
citation travels with every value as :data:`OFR_CITATION_TEMPLATE` — and no
Treasury seal or emblem, text attribution only. The OFR also disclaims
endorsement of commercial products; nothing here may imply it.

The data file is one CSV holding every series, so it is downloaded once per
provider instance and read many times. The site notes the index "publishes
with data that is current from two business days prior".

Only :mod:`app.ingest` constructs this. Request handlers read the database.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import DataUnavailable, RateLimited

OFR_PROVIDER_ID = "ofr"
OFR_SITE_BASE = "https://www.financialresearch.gov"
OFR_PUBLISHER = "Office of Financial Research (U.S. Department of the Treasury)"
OFR_PUBLISHER_URL = f"{OFR_SITE_BASE}/"
OFR_FSI_PAGE_URL = f"{OFR_SITE_BASE}/financial-stress-index/"
OFR_FSI_CSV_URL = f"{OFR_SITE_BASE}/financial-stress-index/data/fsi.csv"
OFR_LEGAL_NOTICES_URL = f"{OFR_SITE_BASE}/legal-notices/"

# The page's own suggested citation; ``{date}`` is the retrieval date, which
# matters because the index is revised as its inputs are.
OFR_CITATION_TEMPLATE = (
    'Office of Financial Research, "OFR Financial Stress Index," refreshed daily, '
    "https://www.financialresearch.gov/financial-stress-index/ (accessed {date})."
)
OFR_ATTRIBUTION = (
    "Source: Office of Financial Research, OFR Financial Stress Index "
    "(financialresearch.gov). A U.S. federal work; credit requested, no Treasury "
    "seal or emblem used, and no OFR endorsement implied."
)

DATE_COLUMN = "Date"


@dataclass(frozen=True)
class OfrSeriesSpec:
    """One column of the FSI file and how it is described downstream."""

    series_key: str  # internal card key, shared with the dashboard catalog
    provider_series_id: str  # our stable id for the column
    column: str  # exact CSV header
    title: str
    title_en: str


_UNITS = "Index (0 = average stress; positive = above-average, negative = below-average)"
_UNITS_SHORT = "Index"
_FREQUENCY = "Daily, business days (published with a two-business-day lag)"

OFR_SERIES: tuple[OfrSeriesSpec, ...] = (
    OfrSeriesSpec("ofr_fsi", "OFR_FSI", "OFR FSI",
                  "OFR 금융스트레스지수 (종합)", "OFR Financial Stress Index"),
    OfrSeriesSpec("ofr_fsi_volatility", "OFR_FSI_VOLATILITY", "Volatility",
                  "OFR 금융스트레스 — 변동성", "OFR FSI — volatility"),
    OfrSeriesSpec("ofr_fsi_credit", "OFR_FSI_CREDIT", "Credit",
                  "OFR 금융스트레스 — 신용", "OFR FSI — credit"),
    OfrSeriesSpec("ofr_fsi_funding", "OFR_FSI_FUNDING", "Funding",
                  "OFR 금융스트레스 — 자금조달", "OFR FSI — funding"),
    OfrSeriesSpec("ofr_fsi_safe_assets", "OFR_FSI_SAFE_ASSETS", "Safe assets",
                  "OFR 금융스트레스 — 안전자산", "OFR FSI — safe assets"),
    OfrSeriesSpec("ofr_fsi_equity_valuation", "OFR_FSI_EQUITY_VALUATION", "Equity valuation",
                  "OFR 금융스트레스 — 주식 밸류에이션", "OFR FSI — equity valuation"),
)
OFR_SERIES_BY_KEY = {spec.series_key: spec for spec in OFR_SERIES}

HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL
        return response.read()


def _number(raw: Any) -> float | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _date(raw: Any) -> dt.date | None:
    text = str(raw or "").strip()
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


class OfrProvider:
    """Small retrying CSV reader. The HTTP transport is injectable for tests."""

    name = OFR_PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        csv_url: str = OFR_FSI_CSV_URL,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.csv_url = csv_url
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep
        self._table: dict[str, dict[dt.date, float]] | None = None
        self._lock = threading.Lock()

    # -- transport ----------------------------------------------------------
    def _download(self) -> bytes:
        request = Request(
            self.csv_url, headers={"Accept": "text/csv", "User-Agent": "Mulmit/1.0"}
        )
        for attempt in range(self.retries + 1):
            try:
                return self._http_get(request, self.timeout)
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("OFR throttled the request") from exc
                raise DataUnavailable(f"OFR HTTP error {exc.code}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable("OFR response unusable") from exc
        raise AssertionError("unreachable")

    # -- parsing ------------------------------------------------------------
    @staticmethod
    def parse(raw: bytes) -> dict[str, dict[dt.date, float]]:
        """Column name → {date: value}. Blank cells are missing, never zero."""
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DataUnavailable("OFR CSV is not UTF-8") from exc
        reader = csv.reader(io.StringIO(text))
        try:
            header = next(reader)
        except StopIteration as exc:
            raise DataUnavailable("OFR CSV is empty") from exc
        header = [cell.strip() for cell in header]
        if DATE_COLUMN not in header:
            raise DataUnavailable("OFR CSV has no Date column")
        date_index = header.index(DATE_COLUMN)
        table: dict[str, dict[dt.date, float]] = {name: {} for name in header if name != DATE_COLUMN}
        for row in reader:
            if len(row) <= date_index:
                continue
            date = _date(row[date_index])
            if date is None:
                continue
            for index, name in enumerate(header):
                if index == date_index or index >= len(row):
                    continue
                value = _number(row[index])
                if value is not None:
                    table[name][date] = value
        if not any(table.values()):
            raise DataUnavailable("OFR CSV held no usable observations")
        return table

    def _load(self) -> dict[str, dict[dt.date, float]]:
        with self._lock:
            if self._table is None:
                self._table = self.parse(self._download())
            return self._table

    # -- public -------------------------------------------------------------
    def fetch_series(
        self,
        spec: OfrSeriesSpec,
        *,
        start: dt.date,
        end: dt.date | None = None,
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        """Return ``(metadata, observations)`` sorted oldest first."""
        end = end or dt.date.today()
        if end < start:
            raise ValueError("end must not precede start")
        table = self._load()
        column = table.get(spec.column)
        if column is None:
            raise DataUnavailable(f"OFR CSV has no column {spec.column!r}")
        observations = tuple(
            sorted((date, value) for date, value in column.items() if start <= date <= end)
        )
        if not observations:
            raise DataUnavailable(f"OFR returned no observations for {spec.column!r}")
        metadata = {
            "title": spec.title,
            "units": _UNITS,
            "units_short": _UNITS_SHORT,
            "frequency": _FREQUENCY,
            "frequency_short": "D",
            "observation_start": observations[0][0].isoformat(),
            "observation_end": observations[-1][0].isoformat(),
            "last_updated": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "notes": (
                f"{spec.title_en}. {OFR_ATTRIBUTION} Values are contributions to the "
                "OFR FSI; the composite is the sum of its five categories."
            ),
        }
        return metadata, observations
