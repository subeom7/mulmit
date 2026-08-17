"""Federal Reserve Board statistical-release reader, driven from fixtures.

The format's two traps are pinned here: a non-available OBS_STATUS sits beside
a sentinel value on US federal holidays, and one archive holds every series in
the release so it must be downloaded once rather than per series.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from urllib.error import HTTPError

import pytest

from app.providers.base import DataUnavailable, RateLimited
from app.providers.fedboard import (
    FEDBOARD_DERIVED,
    FEDBOARD_SERIES_BY_KEY,
    FedBoardConfigurationError,
    FedBoardProvider,
)

TEN_YEAR = FEDBOARD_SERIES_BY_KEY["treasury_10y"]
TWO_YEAR = FEDBOARD_SERIES_BY_KEY["treasury_2y"]
SPREAD = FEDBOARD_DERIVED[0]

H15_XML = """<?xml version="1.0" encoding="UTF-8"?>
<message:MessageGroup xmlns:message="http://www.SDMX.org/message"
                      xmlns:frb="http://www.federalreserve.gov/common"
                      xmlns:kf="http://www.federalreserve.gov/H15">
  <frb:DataSet id="H15">
    <kf:Series SERIES_NAME="RIFLGFCY10_N.B" UNIT="Percent:_Per_Year">
      <frb:Obs TIME_PERIOD="2026-08-11" OBS_VALUE="4.70" OBS_STATUS="A"/>
      <frb:Obs TIME_PERIOD="2026-08-12" OBS_VALUE="4.68" OBS_STATUS="A"/>
      <frb:Obs TIME_PERIOD="2026-08-13" OBS_VALUE="4.63" OBS_STATUS="A"/>
      <!-- A federal holiday: the status says nothing was published and the
           value beside it is the release's sentinel. -->
      <frb:Obs TIME_PERIOD="2026-07-03" OBS_VALUE="-9999" OBS_STATUS="ND"/>
    </kf:Series>
    <kf:Series SERIES_NAME="RIFLGFCY02_N.B" UNIT="Percent:_Per_Year">
      <frb:Obs TIME_PERIOD="2026-08-12" OBS_VALUE="4.20" OBS_STATUS="A"/>
      <frb:Obs TIME_PERIOD="2026-08-13" OBS_VALUE="4.15" OBS_STATUS="A"/>
      <frb:Obs TIME_PERIOD="2026-07-03" OBS_VALUE="-9999" OBS_STATUS="ND"/>
    </kf:Series>
    <kf:Series SERIES_NAME="RIFLGFCY10_N.M">
      <frb:Obs TIME_PERIOD="2026-07-31" OBS_VALUE="4.55" OBS_STATUS="A"/>
    </kf:Series>
  </frb:DataSet>
</message:MessageGroup>
"""


def _archive(member="H15_data.xml", body=H15_XML):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, body)
    return buffer.getvalue()


class Transport:
    def __init__(self, body=None, failures=None):
        self.body = _archive() if body is None else body
        self.failures = list(failures or [])
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        return self.body


def make_provider(transport=None, **kwargs):
    kwargs.setdefault("request_interval", 0.0)
    kwargs.setdefault("retry_backoff", 0.0)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return FedBoardProvider(http_get=transport or Transport(), **kwargs)


def test_a_holiday_sentinel_never_becomes_an_observation():
    """-9999 on a non-available status is the release saying "closed"."""
    _, observations = make_provider().fetch_series(TEN_YEAR)

    assert dict(observations) == {
        dt.date(2026, 8, 11): 4.70,
        dt.date(2026, 8, 12): 4.68,
        dt.date(2026, 8, 13): 4.63,
    }
    assert dt.date(2026, 7, 3) not in dict(observations)
    assert all(value > 0 for _, value in observations)


def test_observations_come_back_oldest_first():
    _, observations = make_provider().fetch_series(TEN_YEAR)

    assert [date for date, _ in observations] == sorted(date for date, _ in observations)


def test_only_the_requested_series_is_returned():
    """The archive also carries the monthly frequency of the same rate."""
    _, observations = make_provider().fetch_series(TEN_YEAR)

    assert dt.date(2026, 7, 31) not in dict(observations)


def test_one_archive_serves_every_series_in_the_release():
    transport = Transport()
    provider = make_provider(transport)

    provider.fetch_series(TEN_YEAR)
    provider.fetch_series(TWO_YEAR)
    provider.fetch_derived(SPREAD)

    assert len(transport.requests) == 1


def test_the_request_asks_for_anything():
    """A narrow Accept such as application/zip is answered with 406."""
    transport = Transport()
    make_provider(transport).fetch_series(TEN_YEAR)

    assert transport.requests[0].get_header("Accept") == "*/*"


def test_the_spread_uses_only_dates_both_series_published():
    """2026-08-11 has a 10-year but no 2-year, so it cannot be differenced."""
    metadata, observations = make_provider().fetch_derived(SPREAD)

    assert dict(observations) == {
        dt.date(2026, 8, 12): 0.48,
        dt.date(2026, 8, 13): 0.48,
    }
    assert dt.date(2026, 8, 11) not in dict(observations)
    assert metadata["derivation"] == "RIFLGFCY10_N.B - RIFLGFCY02_N.B"
    assert metadata["units_short"] == "%p"


def test_the_spread_is_not_stored_with_float_noise():
    _, observations = make_provider().fetch_derived(SPREAD)

    # 4.63 - 4.15 is 0.47999999999999954 in binary floating point.
    assert dict(observations)[dt.date(2026, 8, 13)] == 0.48


def test_a_start_date_windows_both_published_and_derived_series():
    provider = make_provider()

    _, published = provider.fetch_series(TEN_YEAR, start=dt.date(2026, 8, 13))
    _, derived = provider.fetch_derived(SPREAD, start=dt.date(2026, 8, 13))

    assert [date for date, _ in published] == [dt.date(2026, 8, 13)]
    assert [date for date, _ in derived] == [dt.date(2026, 8, 13)]


def test_metadata_reports_the_actual_range():
    metadata, _ = make_provider().fetch_series(TEN_YEAR)

    assert metadata["observation_start"] == "2026-08-11"
    assert metadata["observation_end"] == "2026-08-13"
    assert metadata["units"] == "Percent per year"
    assert metadata["release"].startswith("H.15")


def test_an_absent_series_is_reported_rather_than_guessed():
    body = _archive(body=H15_XML.replace("RIFLGFCY10_N.B", "SOMETHING_ELSE"))

    with pytest.raises(DataUnavailable):
        make_provider(Transport(body)).fetch_series(TEN_YEAR)


def test_a_window_with_no_observations_is_unavailable():
    with pytest.raises(DataUnavailable):
        make_provider().fetch_series(TEN_YEAR, start=dt.date(2030, 1, 1))


def test_unreadable_archives_are_rejected():
    with pytest.raises(DataUnavailable):
        make_provider(Transport(b"not a zip")).fetch_series(TEN_YEAR)
    with pytest.raises(DataUnavailable):
        make_provider(Transport(_archive(body="<broken"))).fetch_series(TEN_YEAR)
    with pytest.raises(DataUnavailable):
        make_provider(Transport(_archive(member="OTHER.xml"))).fetch_series(TEN_YEAR)


def test_a_release_with_no_usable_observation_is_unavailable():
    empty = H15_XML.replace('OBS_STATUS="A"', 'OBS_STATUS="ND"')

    with pytest.raises(DataUnavailable):
        make_provider(Transport(_archive(body=empty))).fetch_series(TEN_YEAR)


def test_throttling_and_retries():
    clock = {"now": 0.0}
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    provider = FedBoardProvider(
        http_get=Transport(), request_interval=0.5, retry_backoff=0.0,
        sleep=sleep, monotonic=lambda: clock["now"],
    )
    provider.fetch_series(TEN_YEAR)
    provider._releases.clear()  # force a second download
    provider.fetch_series(TEN_YEAR)

    assert slept == [pytest.approx(0.5)]

    transport = Transport(failures=[HTTPError("u", 503, "busy", {}, None), None])
    make_provider(transport, retries=2).fetch_series(TEN_YEAR)
    assert len(transport.requests) == 2

    with pytest.raises(RateLimited):
        make_provider(
            Transport(failures=[HTTPError("u", 429, "slow down", {}, None)] * 3), retries=2
        ).fetch_series(TEN_YEAR)

    missing = Transport(failures=[HTTPError("u", 404, "gone", {}, None)])
    with pytest.raises(DataUnavailable):
        make_provider(missing, retries=3).fetch_series(TEN_YEAR)
    assert len(missing.requests) == 1  # 404 is final


def test_an_unknown_release_is_a_configuration_error():
    with pytest.raises(FedBoardConfigurationError):
        make_provider().load_release("H99")
