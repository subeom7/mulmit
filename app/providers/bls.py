"""U.S. Bureau of Labor Statistics public data API.

The rights position is stated outright rather than inferred:

    "The Bureau of Labor Statistics (BLS) is a Federal government agency and
    everything that we publish, both in hard copy and electronically, is in the
    public domain... You are free to use our public domain material without
    specific permission, although we do ask that you cite the Bureau of Labor
    Statistics as the source."

    https://www.bls.gov/bls/linksite.htm

So the only obligation is the citation, which travels with the values.

The API works with or without a key. Unregistered access allows 25 queries a
day over a ten-year window; a registered key raises that to 500 and twenty
years. Refreshing one monthly series twice a day fits inside the unregistered
budget, so a key is optional rather than required.

Only :mod:`app.ingest` constructs this. Request handlers read the database.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import DataUnavailable, RateLimited

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BLS_SITE_BASE = "https://www.bls.gov"
BLS_TERMS_URL = f"{BLS_SITE_BASE}/bls/linksite.htm"
BLS_API_DOCS_URL = f"{BLS_SITE_BASE}/developers/home.htm"
BLS_PROVIDER_ID = "bls"
BLS_PUBLISHER = "U.S. Bureau of Labor Statistics"
BLS_PUBLISHER_URL = f"{BLS_SITE_BASE}/"

# The citation the terms ask for in return for public-domain use.
BLS_ATTRIBUTION = "Source: U.S. Bureau of Labor Statistics."

# Unregistered access reaches ten years back; a key reaches twenty.
UNREGISTERED_YEARS = 10
REGISTERED_YEARS = 20

# Monthly periods are M01..M12. M13 is the annual average and is not an
# observation of any month, so it never becomes a data point.
ANNUAL_AVERAGE_PERIOD = "M13"


@dataclass(frozen=True)
class BlsSeriesSpec:
    series_key: str  # internal card key
    provider_series_id: str  # the BLS series id
    title: str
    units: str
    units_short: str
    frequency: str
    frequency_short: str
    series_url: str


BLS_SERIES: tuple[BlsSeriesSpec, ...] = (
    BlsSeriesSpec(
        series_key="unemployment",
        provider_series_id="LNS14000000",
        title="Unemployment rate, 16 years and over, seasonally adjusted",
        units="Percent",
        units_short="%",
        frequency="Monthly",
        frequency_short="M",
        series_url=f"{BLS_SITE_BASE}/cps/",
    ),
)

BLS_SERIES_BY_KEY = {spec.series_key: spec for spec in BLS_SERIES}

HttpPost = Callable[[Request, float], bytes]


def _stdlib_http_post(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _month_end(year: str, period: str) -> dt.date | None:
    """Convert a BLS ``(year, Mnn)`` pair to the last day of that month.

    An observation covering a month is dated at the month's end so it sorts
    correctly beside daily series and never claims to describe the first.
    """
    try:
        month = int(period[1:])
        first = dt.date(int(year), month, 1)
    except (TypeError, ValueError):
        return None
    if month == 12:
        return dt.date(first.year, 12, 31)
    return dt.date(first.year, month + 1, 1) - dt.timedelta(days=1)


class BlsProvider:
    """Small JSON client for the BLS timeseries endpoint."""

    name = BLS_PROVIDER_ID

    def __init__(
        self,
        api_key: str = "",
        *,
        timeout: float = 20.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        api_url: str = BLS_API_URL,
        http_post: HttpPost | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_backoff = max(0.0, retry_backoff)
        self.api_url = api_url
        self._http_post = http_post or _stdlib_http_post
        self._sleep = sleep

    @property
    def max_years(self) -> int:
        return REGISTERED_YEARS if self.api_key else UNREGISTERED_YEARS

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mulmit/1.0",
            },
            method="POST",
        )
        for attempt in range(self.retries + 1):
            try:
                raw = self._http_post(request, self.timeout)
                body = json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("BLS throttled the request") from exc
                raise DataUnavailable(f"BLS HTTP error {exc.code}") from exc
            except (JSONDecodeError, UnicodeDecodeError, URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable("BLS response is unusable") from exc

            if not isinstance(body, dict):
                raise DataUnavailable("BLS response is not an object")
            status = str(body.get("status") or "")
            if status != "REQUEST_SUCCEEDED":
                messages = "; ".join(str(m) for m in body.get("message") or []) or status
                # The daily query allowance is reported in the body, not as 429.
                if "threshold" in messages.lower() or "limit" in messages.lower():
                    raise RateLimited(f"BLS daily query limit reached: {messages}")
                raise DataUnavailable(f"BLS request failed: {messages}")
            return body
        raise AssertionError("unreachable")

    def fetch_series(
        self,
        spec: BlsSeriesSpec,
        *,
        end_year: int | None = None,
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        """Return ``(metadata, observations)`` sorted oldest first."""
        end = end_year or dt.date.today().year
        start = end - (self.max_years - 1)
        payload: dict[str, Any] = {
            "seriesid": [spec.provider_series_id],
            "startyear": str(start),
            "endyear": str(end),
        }
        if self.api_key:
            payload["registrationkey"] = self.api_key

        body = self._request(payload)
        series = (body.get("Results") or {}).get("series") or []
        rows = next(
            (
                item.get("data") or []
                for item in series
                if isinstance(item, dict) and item.get("seriesID") == spec.provider_series_id
            ),
            None,
        )
        if rows is None:
            raise DataUnavailable(f"BLS returned no series named {spec.provider_series_id}")

        values: dict[dt.date, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            period = str(row.get("period") or "")
            # Skip the annual average, which is not a monthly observation.
            if period == ANNUAL_AVERAGE_PERIOD or not period.startswith("M"):
                continue
            date = _month_end(row.get("year"), period)
            if date is None:
                continue
            try:
                value = float(str(row.get("value")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values[date] = value

        observations = tuple(sorted(values.items()))
        if not observations:
            raise DataUnavailable(
                f"BLS returned no usable observations for {spec.provider_series_id}"
            )
        metadata = {
            "title": spec.title,
            "units": spec.units,
            "units_short": spec.units_short,
            "frequency": spec.frequency,
            "frequency_short": spec.frequency_short,
            "seasonal_adjustment": "Seasonally Adjusted",
            "seasonal_adjustment_short": "SA",
            "observation_start": observations[0][0].isoformat(),
            "observation_end": observations[-1][0].isoformat(),
            "last_updated": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "notes": "",
        }
        return metadata, observations
