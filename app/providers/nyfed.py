"""Federal Reserve Bank of New York markets API client.

Unlike most feeds in this project, the rights position here is explicit rather
than inferred. The New York Fed's Terms of Use grant a non-exclusive licence to
access Content "through an automated process or device", to "Download, store,
and use" it, to "Copy and distribute" it, and to "Modify and create derivative
works" from it, for personal *or business* purposes. That covers every use
Mulmit makes of it: batch collection, a private history table, the public JSON
API, and computed changes.

The licence is conditional. Any copy has to carry the source identifier the New
York Fed specifies, so :data:`NYFED_ATTRIBUTION` travels with the data instead
of living only in a document.

https://www.newyorkfed.org/privacy/termsofuse

Only :mod:`app.ingest` constructs this. Request handlers read the database.
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
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import DataUnavailable, RateLimited

NYFED_API_BASE = "https://markets.newyorkfed.org/api"
NYFED_SITE_BASE = "https://www.newyorkfed.org"
NYFED_TERMS_URL = f"{NYFED_SITE_BASE}/privacy/termsofuse"
NYFED_REFERENCE_RATES_URL = f"{NYFED_SITE_BASE}/markets/reference-rates"
NYFED_PROVIDER_ID = "nyfed"
NYFED_PUBLISHER = "Federal Reserve Bank of New York"
NYFED_PUBLISHER_URL = f"{NYFED_SITE_BASE}/"

# The exact wording the Terms prescribe when no more specific form is given.
# The year is filled in at collection time.
NYFED_ATTRIBUTION_TEMPLATE = (
    "© {year} Federal Reserve Bank of New York. Content from the New York Fed "
    "subject to the Terms of Use at newyorkfed.org."
)


def attribution(year: int | None = None) -> str:
    return NYFED_ATTRIBUTION_TEMPLATE.format(year=year or dt.date.today().year)


@dataclass(frozen=True)
class NyFedSeriesSpec:
    """One collectable series and how to read it out of the API."""

    series_key: str  # internal card key, shared with the dashboard catalog
    provider_series_id: str  # the New York Fed's own name for it
    path: str
    kind: str  # reference_rate | reverse_repo
    units: str
    units_short: str
    frequency: str
    frequency_short: str
    title: str
    series_url: str


NYFED_SERIES: tuple[NyFedSeriesSpec, ...] = (
    NyFedSeriesSpec(
        series_key="sofr",
        provider_series_id="SOFR",
        path="rates/secured/sofr/search.json",
        kind="reference_rate",
        units="Percent",
        units_short="%",
        frequency="Daily, business days",
        frequency_short="D",
        title="Secured Overnight Financing Rate",
        series_url=NYFED_REFERENCE_RATES_URL,
    ),
    NyFedSeriesSpec(
        series_key="effective_fed_funds",
        provider_series_id="EFFR",
        path="rates/unsecured/effr/search.json",
        kind="reference_rate",
        units="Percent",
        units_short="%",
        frequency="Daily, business days",
        frequency_short="D",
        title="Effective Federal Funds Rate",
        series_url=NYFED_REFERENCE_RATES_URL,
    ),
    NyFedSeriesSpec(
        series_key="reverse_repo",
        provider_series_id="RRP",
        path="rp/reverserepo/propositions/search.json",
        kind="reverse_repo",
        # Reported in whole dollars, not the billions FRED's RRPONTSYD uses.
        # Storing the provider's own unit is the point of the neutral tables.
        units="US Dollars",
        units_short="USD",
        frequency="Daily, business days",
        frequency_short="D",
        title="Overnight Reverse Repurchase Agreements, total accepted",
        series_url=f"{NYFED_SITE_BASE}/markets/desk-operations/reverse-repo",
    ),
)

NYFED_SERIES_BY_KEY = {spec.series_key: spec for spec in NYFED_SERIES}

# Only these count toward the overnight facility. Term operations are a
# different instrument and must not be added to the same series.
OVERNIGHT_REVERSE_REPO_TYPE = "reverse repo"

HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _date(raw: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(raw).strip()[:10])
    except (AttributeError, TypeError, ValueError):
        return None


def _number(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class NyFedProvider:
    """Small, retrying markets-API client with an injectable HTTP transport."""

    name = NYFED_PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        request_interval: float = 0.2,
        api_base: str = NYFED_API_BASE,
        http_get: HttpGet | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
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
        """The Terms permit automated access only while it does not interfere
        with the site, so requests are spaced rather than issued back to back."""
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

    def _request_json(self, path: str, params: dict[str, str]) -> Any:
        url = f"{self.api_base}/{path.lstrip('/')}?{urlencode(params)}"
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Mulmit/1.0"},
        )
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                raw = self._http_get(request, self.timeout)
                return json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                if exc.code == 404:
                    raise DataUnavailable(f"New York Fed has no resource at {path}") from exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("New York Fed throttled the request") from exc
                raise DataUnavailable(f"New York Fed HTTP error {exc.code} for {path}") from exc
            except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"New York Fed response unusable for {path}") from exc
        raise AssertionError("unreachable")

    # --- parsing ------------------------------------------------------------

    def _parse_reference_rate(self, payload: Any, spec: NyFedSeriesSpec) -> dict[dt.date, float]:
        rows = payload.get("refRates") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise DataUnavailable(f"New York Fed returned no refRates for {spec.provider_series_id}")
        values: dict[dt.date, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            # A combined endpoint can return several rate types in one list.
            row_type = str(row.get("type") or "").strip().upper()
            if row_type and row_type != spec.provider_series_id:
                continue
            date = _date(row.get("effectiveDate"))
            rate = _number(row.get("percentRate"))
            # A published day with no rate stays absent rather than becoming 0.
            if date is not None and rate is not None:
                values[date] = rate
        return values

    def _parse_reverse_repo(self, payload: Any, spec: NyFedSeriesSpec) -> dict[dt.date, float]:
        repo = payload.get("repo") if isinstance(payload, dict) else None
        operations = repo.get("operations") if isinstance(repo, dict) else None
        if not isinstance(operations, list):
            raise DataUnavailable("New York Fed returned no reverse-repo operations")
        totals: dict[dt.date, float] = {}
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            if str(operation.get("operationType") or "").strip().lower() != OVERNIGHT_REVERSE_REPO_TYPE:
                continue
            date = _date(operation.get("operationDate"))
            amount = _number(operation.get("totalAmtAccepted"))
            if date is None or amount is None:
                continue
            # Defensive: the desk can run more than one operation in a day, and
            # the daily facility total is their sum.
            totals[date] = totals.get(date, 0.0) + amount
        return totals

    # --- public -------------------------------------------------------------

    def fetch_series(
        self,
        spec: NyFedSeriesSpec,
        *,
        start: dt.date,
        end: dt.date | None = None,
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        """Return ``(metadata, observations)`` sorted oldest first."""
        end = end or dt.date.today()
        if end < start:
            raise ValueError("end must not precede start")
        payload = self._request_json(
            spec.path, {"startDate": start.isoformat(), "endDate": end.isoformat()}
        )
        if spec.kind == "reference_rate":
            values = self._parse_reference_rate(payload, spec)
        elif spec.kind == "reverse_repo":
            values = self._parse_reverse_repo(payload, spec)
        else:  # pragma: no cover - guarded by the catalog
            raise ValueError(f"unsupported series kind: {spec.kind}")

        observations = tuple(sorted(values.items()))
        if not observations:
            raise DataUnavailable(
                f"New York Fed returned no usable observations for {spec.provider_series_id}"
            )
        metadata = {
            "title": spec.title,
            "units": spec.units,
            "units_short": spec.units_short,
            "frequency": spec.frequency,
            "frequency_short": spec.frequency_short,
            "observation_start": observations[0][0].isoformat(),
            "observation_end": observations[-1][0].isoformat(),
            "last_updated": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            # The required source identifier is structural, not free text: it is
            # published through the provider's rights notice rather than through
            # ``notes``, which the dashboard scans for third-party copyright
            # claims that withhold a series.
            "notes": "",
        }
        return metadata, observations
