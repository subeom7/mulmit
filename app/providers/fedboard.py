"""Board of Governors of the Federal Reserve System statistical releases.

The Board is retiring its Data Download Program and pointing users at FRED,
which Mulmit cannot use under FRED's own terms. The transition notice leaves
one route open, and it is the one this module takes:

    "Historical data will remain available for download as XML files on
    statistical release pages."

    https://www.federalreserve.gov/data/data-download-fred-information.htm

So each release is read as its published SDMX-ML archive
(``/releases/h15/data/FRB_h15_xml.zip``) rather than through the DDP query
endpoint that is going away.

Two things in this format will silently produce wrong numbers if ignored.
Observations carry an ``OBS_STATUS`` and a non-``A`` status means the value is
a sentinel — ``-9999`` in H.15, ``-999999`` in H.4.1 — sitting on a US federal
holiday. And an archive holds every series in the release, so it is downloaded
once and read many times rather than fetched per series.

Only :mod:`app.ingest` constructs this. Request handlers read the database.
"""

from __future__ import annotations

import datetime as dt
import io
import math
import threading
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .base import DataUnavailable, RateLimited

FEDBOARD_PROVIDER_ID = "federal_reserve"
FEDBOARD_SITE_BASE = "https://www.federalreserve.gov"
FEDBOARD_PUBLISHER = "Board of Governors of the Federal Reserve System"
FEDBOARD_PUBLISHER_URL = f"{FEDBOARD_SITE_BASE}/"
FEDBOARD_DDP_TRANSITION_URL = f"{FEDBOARD_SITE_BASE}/data/data-download-fred-information.htm"

# The Board publishes no licence to quote, because as a US federal agency its
# works are not subject to copyright. What a reader still needs is provenance,
# so values carry the standard citation rather than a legal notice. This is a
# different situation from the Federal Reserve Bank of New York, which is not a
# federal agency, asserts copyright, and grants an explicit licence.
FEDBOARD_ATTRIBUTION = (
    "Source: Board of Governors of the Federal Reserve System (US), "
    "statistical releases."
)

# Only this status means the number is real. Everything else marks a day the
# release did not publish, and the accompanying value is a sentinel.
AVAILABLE_STATUS = "A"
# Both sentinels seen across releases. Guarded by value as well as by status so
# a future release using one without the other still fails safe.
SENTINEL_VALUES = frozenset({-9999.0, -999999.0})


class FedBoardConfigurationError(RuntimeError):
    """A catalog entry names a release this provider does not know."""


@dataclass(frozen=True)
class FedBoardRelease:
    release_id: str
    name: str
    archive_url: str
    data_member: str
    page_url: str


FEDBOARD_RELEASES: dict[str, FedBoardRelease] = {
    "H15": FedBoardRelease(
        release_id="H15",
        name="H.15 Selected Interest Rates",
        archive_url=f"{FEDBOARD_SITE_BASE}/releases/h15/data/FRB_h15_xml.zip",
        data_member="H15_data.xml",
        page_url=f"{FEDBOARD_SITE_BASE}/releases/h15/",
    ),
    "H10": FedBoardRelease(
        release_id="H10",
        name="H.10 Foreign Exchange Rates",
        archive_url=f"{FEDBOARD_SITE_BASE}/releases/h10/data/FRB_H10_xml.zip",
        data_member="H10_data.xml",
        page_url=f"{FEDBOARD_SITE_BASE}/releases/h10/",
    ),
}

# H.10 quotes in two directions and the series name is the only signal. A name
# containing ``$US`` is dollars per unit of the foreign currency (EUR 1.16);
# everything else is foreign currency per dollar (KRW 1409.94). Reading one as
# the other inverts the rate, so the direction is carried in the units rather
# than left for a reader to infer.
FOREIGN_PER_USD = "foreign_per_usd"
USD_PER_FOREIGN = "usd_per_foreign"


def quote_convention(provider_series_id: str) -> str:
    return USD_PER_FOREIGN if "$US" in provider_series_id else FOREIGN_PER_USD


@dataclass(frozen=True)
class FedBoardSeriesSpec:
    """One collectable series inside a release."""

    series_key: str  # internal card key, shared with the dashboard catalog
    release_id: str
    provider_series_id: str  # the Board's own SERIES_NAME
    title: str
    units: str
    units_short: str
    frequency: str
    frequency_short: str


def _fx(series_key, provider_series_id, name_ko, unit_long, unit_short):
    return FedBoardSeriesSpec(
        series_key=series_key,
        release_id="H10",
        provider_series_id=provider_series_id,
        title=name_ko,
        units=unit_long,
        units_short=unit_short,
        frequency="Daily, business days",
        frequency_short="D",
    )


FEDBOARD_SERIES: tuple[FedBoardSeriesSpec, ...] = (
    FedBoardSeriesSpec(
        series_key="treasury_10y",
        release_id="H15",
        provider_series_id="RIFLGFCY10_N.B",
        title="Market yield on U.S. Treasury securities at 10-year constant maturity",
        units="Percent per year",
        units_short="%",
        frequency="Daily, business days",
        frequency_short="D",
    ),
    FedBoardSeriesSpec(
        series_key="treasury_2y",
        release_id="H15",
        provider_series_id="RIFLGFCY02_N.B",
        title="Market yield on U.S. Treasury securities at 2-year constant maturity",
        units="Percent per year",
        units_short="%",
        frequency="Daily, business days",
        frequency_short="D",
    ),
    # Units spell out the direction because the two conventions differ.
    _fx("fx_usdkrw", "RXI_N.B.KO", "Korean won per US dollar",
        "Korean won per US dollar", "KRW/USD"),
    _fx("fx_usdjpy", "RXI_N.B.JA", "Japanese yen per US dollar",
        "Japanese yen per US dollar", "JPY/USD"),
    _fx("fx_usdcny", "RXI_N.B.CH", "Chinese yuan per US dollar",
        "Chinese yuan per US dollar", "CNY/USD"),
    _fx("fx_eurusd", "RXI$US_N.B.EU", "US dollars per euro",
        "US dollars per euro", "USD/EUR"),
    _fx("fx_gbpusd", "RXI$US_N.B.UK", "US dollars per British pound",
        "US dollars per British pound", "USD/GBP"),
)

FEDBOARD_SERIES_BY_KEY = {spec.series_key: spec for spec in FEDBOARD_SERIES}


@dataclass(frozen=True)
class DerivedSeriesSpec:
    """A series Mulmit computes from two published ones.

    The Board publishes the 10-year and the 2-year separately and does not
    publish the spread, so it is calculated here from both official series
    aligned on the same observation date. Dates present in only one of them are
    dropped rather than carried forward.
    """

    series_key: str
    minuend_key: str
    subtrahend_key: str
    title: str
    units: str
    units_short: str
    frequency: str
    frequency_short: str

    @property
    def provider_series_id(self) -> str:
        minuend = FEDBOARD_SERIES_BY_KEY[self.minuend_key].provider_series_id
        subtrahend = FEDBOARD_SERIES_BY_KEY[self.subtrahend_key].provider_series_id
        return f"{minuend} - {subtrahend}"


FEDBOARD_DERIVED: tuple[DerivedSeriesSpec, ...] = (
    DerivedSeriesSpec(
        series_key="yield_curve",
        minuend_key="treasury_10y",
        subtrahend_key="treasury_2y",
        title="10-year minus 2-year Treasury constant maturity spread",
        units="Percentage points",
        units_short="%p",
        frequency="Daily, business days",
        frequency_short="D",
    ),
)

HttpGet = Callable[[Request, float], bytes]


def _stdlib_http_get(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS base
        return response.read()


def _date(raw: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(raw).strip()[:10])
    except (AttributeError, TypeError, ValueError):
        return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class FedBoardProvider:
    """Reads statistical-release XML archives, one download per release."""

    name = FEDBOARD_PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        retries: int = 2,
        retry_backoff: float = 0.5,
        request_interval: float = 0.5,
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
        self._http_get = http_get or _stdlib_http_get
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self._throttle_lock = threading.Lock()
        # One archive serves every series in its release.
        self._releases: dict[str, dict[str, list[tuple[dt.date, float]]]] = {}

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

    def _download(self, url: str) -> bytes:
        # The Board answers 406 to a narrow Accept such as application/zip even
        # though the resource it serves is exactly that, so ask for anything.
        request = Request(url, headers={"Accept": "*/*", "User-Agent": "Mulmit/1.0"})
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                return self._http_get(request, self.timeout)
            except HTTPError as exc:
                if exc.code == 404:
                    raise DataUnavailable(f"Federal Reserve Board has no archive at {url}") from exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                if exc.code == 429:
                    raise RateLimited("Federal Reserve Board throttled the request") from exc
                raise DataUnavailable(f"Federal Reserve Board HTTP error {exc.code}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt < self.retries:
                    self._sleep(self.retry_backoff * (2**attempt))
                    continue
                raise DataUnavailable(f"Federal Reserve Board is unreachable: {url}") from exc
        raise AssertionError("unreachable")

    def _parse(self, payload: bytes, release: FedBoardRelease) -> dict[str, list[tuple[dt.date, float]]]:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                raw = archive.read(release.data_member)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise DataUnavailable(f"{release.release_id} archive is unreadable") from exc
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError as exc:
            raise DataUnavailable(f"{release.release_id} XML is unreadable") from exc

        series: dict[str, list[tuple[dt.date, float]]] = {}
        for node in root.iter():
            if _local_name(node.tag) != "Series":
                continue
            name = node.get("SERIES_NAME")
            if not name:
                continue
            observations: list[tuple[dt.date, float]] = []
            for child in node:
                if _local_name(child.tag) != "Obs":
                    continue
                # A non-available status means the release did not publish that
                # day; the value beside it is a holiday sentinel.
                if child.get("OBS_STATUS") != AVAILABLE_STATUS:
                    continue
                date = _date(child.get("TIME_PERIOD"))
                if date is None:
                    continue
                try:
                    value = float(child.get("OBS_VALUE"))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value) or value in SENTINEL_VALUES:
                    continue
                observations.append((date, value))
            if observations:
                observations.sort()
                series[name] = observations
        if not series:
            raise DataUnavailable(f"{release.release_id} archive contained no usable series")
        return series

    def load_release(self, release_id: str) -> dict[str, list[tuple[dt.date, float]]]:
        """Fetch and parse one release, memoised for this provider instance."""
        if release_id in self._releases:
            return self._releases[release_id]
        release = FEDBOARD_RELEASES.get(release_id)
        if release is None:
            raise FedBoardConfigurationError(f"unknown release: {release_id}")
        parsed = self._parse(self._download(release.archive_url), release)
        self._releases[release_id] = parsed
        return parsed

    def fetch_series(
        self,
        spec: FedBoardSeriesSpec,
        *,
        start: dt.date | None = None,
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        """Return ``(metadata, observations)`` sorted oldest first."""
        release = FEDBOARD_RELEASES[spec.release_id]
        parsed = self.load_release(spec.release_id)
        rows = parsed.get(spec.provider_series_id)
        if not rows:
            raise DataUnavailable(
                f"{spec.provider_series_id} is absent from the {spec.release_id} archive"
            )
        if start is not None:
            rows = [row for row in rows if row[0] >= start]
        if not rows:
            raise DataUnavailable(f"{spec.provider_series_id} has no observations after {start}")
        return self._metadata(spec, release, rows), tuple(rows)

    def _metadata(
        self,
        spec: FedBoardSeriesSpec | DerivedSeriesSpec,
        release: FedBoardRelease,
        rows: list[tuple[dt.date, float]],
    ) -> dict[str, Any]:
        return {
            "title": spec.title,
            "units": spec.units,
            "units_short": spec.units_short,
            "frequency": spec.frequency,
            "frequency_short": spec.frequency_short,
            "observation_start": rows[0][0].isoformat(),
            "observation_end": rows[-1][0].isoformat(),
            "last_updated": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "release": release.name,
            "notes": "",
        }

    def fetch_derived(
        self,
        spec: DerivedSeriesSpec,
        *,
        start: dt.date | None = None,
    ) -> tuple[dict[str, Any], tuple[tuple[dt.date, float], ...]]:
        """Compute a spread from two official series aligned on the same date."""
        minuend = FEDBOARD_SERIES_BY_KEY[spec.minuend_key]
        subtrahend = FEDBOARD_SERIES_BY_KEY[spec.subtrahend_key]
        if minuend.release_id != subtrahend.release_id:
            raise FedBoardConfigurationError("a derived series must come from one release")
        parsed = self.load_release(minuend.release_id)
        left = dict(parsed.get(minuend.provider_series_id) or ())
        right = dict(parsed.get(subtrahend.provider_series_id) or ())
        # Only dates both series published. A day present in one alone is
        # dropped rather than paired with a carried-forward value.
        # The release publishes two decimals, so their difference is exact at two.
        # Rounding to four is well beyond the source's precision — it cannot lose
        # information — and it keeps 4.63 - 4.15 from being stored as
        # 0.47999999999999954.
        rows = [
            (date, round(left[date] - right[date], 4))
            for date in sorted(left.keys() & right.keys())
        ]
        if start is not None:
            rows = [row for row in rows if row[0] >= start]
        if not rows:
            raise DataUnavailable(f"{spec.series_key} has no dates common to both series")
        release = FEDBOARD_RELEASES[minuend.release_id]
        metadata = self._metadata(spec, release, rows)
        metadata["derivation"] = spec.provider_series_id
        return metadata, tuple(rows)
