"""New York Fed markets-API client, driven entirely from fixtures.

The awkward parts are pinned deliberately: the API answers newest-first, a
combined rates endpoint can mix rate types, a published day can carry a null
rate, and the reverse-repo feed reports operations rather than a daily series.
"""

from __future__ import annotations

import datetime as dt
import json
from urllib.error import HTTPError

import pytest

from app.providers.base import DataUnavailable, RateLimited
from app.providers.nyfed import (
    NYFED_SERIES_BY_KEY,
    NyFedProvider,
    attribution,
)

SOFR = NYFED_SERIES_BY_KEY["sofr"]
EFFR = NYFED_SERIES_BY_KEY["effective_fed_funds"]
RRP = NYFED_SERIES_BY_KEY["reverse_repo"]

# Newest first, exactly as the API returns it.
SOFR_BODY = json.dumps({
    "refRates": [
        {"effectiveDate": "2026-08-13", "type": "SOFR", "percentRate": 3.62},
        {"effectiveDate": "2026-08-12", "type": "SOFR", "percentRate": 3.62},
        {"effectiveDate": "2026-08-11", "type": "SOFR", "percentRate": 3.64},
        # A published row with no rate must be skipped, never read as zero.
        {"effectiveDate": "2026-08-10", "type": "SOFR", "percentRate": None},
        # A different rate type sharing the response must not be mixed in.
        {"effectiveDate": "2026-08-13", "type": "EFFR", "percentRate": 9.99},
    ]
}).encode()

RRP_BODY = json.dumps({
    "repo": {
        "operations": [
            {"operationDate": "2026-08-14", "operationType": "Reverse Repo",
             "totalAmtAccepted": 250000000},
            # Two operations in one day: the daily facility total is their sum.
            {"operationDate": "2026-08-13", "operationType": "Reverse Repo",
             "totalAmtAccepted": 400000000},
            {"operationDate": "2026-08-13", "operationType": "Reverse Repo",
             "totalAmtAccepted": 50000000},
            # Term operations are a different instrument.
            {"operationDate": "2026-08-12", "operationType": "Repo",
             "totalAmtAccepted": 999999999},
        ]
    }
}).encode()


class Transport:
    def __init__(self, body=SOFR_BODY, failures=None):
        self.body = body
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
    return NyFedProvider(http_get=transport or Transport(), **kwargs)


def test_reference_rates_are_returned_oldest_first():
    _, observations = make_provider().fetch_series(SOFR, start=dt.date(2026, 8, 1))

    assert observations == (
        (dt.date(2026, 8, 11), 3.64),
        (dt.date(2026, 8, 12), 3.62),
        (dt.date(2026, 8, 13), 3.62),
    )


def test_a_null_rate_is_skipped_rather_than_zeroed():
    _, observations = make_provider().fetch_series(SOFR, start=dt.date(2026, 8, 1))

    assert dt.date(2026, 8, 10) not in dict(observations)
    assert 0.0 not in [value for _, value in observations]


def test_another_rate_type_in_the_same_response_is_ignored():
    _, observations = make_provider().fetch_series(SOFR, start=dt.date(2026, 8, 1))

    assert 9.99 not in [value for _, value in observations]


def test_metadata_carries_provider_native_units_and_range():
    metadata, _ = make_provider().fetch_series(SOFR, start=dt.date(2026, 8, 1))

    assert metadata["units"] == "Percent"
    assert metadata["units_short"] == "%"
    assert metadata["observation_start"] == "2026-08-11"
    assert metadata["observation_end"] == "2026-08-13"
    # The required source identifier is published through the rights notice,
    # not through notes, which the dashboard scans for third-party claims.
    assert metadata["notes"] == ""


def test_reverse_repo_sums_same_day_operations_and_drops_term_repo():
    _, observations = make_provider(Transport(RRP_BODY)).fetch_series(
        RRP, start=dt.date(2026, 8, 1)
    )

    assert dict(observations) == {
        dt.date(2026, 8, 13): 450000000.0,  # 400M + 50M
        dt.date(2026, 8, 14): 250000000.0,
    }
    # The 999,999,999 "Repo" operation is a different instrument.
    assert 999999999.0 not in [value for _, value in observations]


def test_reverse_repo_keeps_whole_dollars_not_billions():
    """FRED publishes RRPONTSYD in billions; this feed reports whole dollars.

    Rescaling here would make the stored series disagree with its declared
    units, which is what the neutral tables exist to prevent.
    """
    metadata, observations = make_provider(Transport(RRP_BODY)).fetch_series(
        RRP, start=dt.date(2026, 8, 1)
    )

    assert metadata["units"] == "US Dollars"
    # 250,000,000 dollars, not the 0.25 a billions-denominated feed would give.
    assert dict(observations)[dt.date(2026, 8, 14)] == 250000000.0
    assert all(value > 1e6 for _, value in observations)


def test_the_requested_window_is_passed_through():
    transport = Transport()
    make_provider(transport).fetch_series(
        EFFR, start=dt.date(2026, 1, 1), end=dt.date(2026, 8, 17)
    )

    url = transport.requests[0].full_url
    assert "startDate=2026-01-01" in url
    assert "endDate=2026-08-17" in url
    assert "unsecured/effr" in url


def test_end_before_start_is_refused():
    with pytest.raises(ValueError):
        make_provider().fetch_series(SOFR, start=dt.date(2026, 8, 17), end=dt.date(2026, 8, 1))


def test_an_empty_series_is_unavailable_rather_than_silently_empty():
    empty = json.dumps({"refRates": []}).encode()

    with pytest.raises(DataUnavailable):
        make_provider(Transport(empty)).fetch_series(SOFR, start=dt.date(2026, 8, 1))


def test_a_missing_envelope_is_rejected():
    with pytest.raises(DataUnavailable):
        make_provider(Transport(b'{"unexpected": 1}')).fetch_series(SOFR, start=dt.date(2026, 8, 1))
    with pytest.raises(DataUnavailable):
        make_provider(Transport(b"{")).fetch_series(SOFR, start=dt.date(2026, 8, 1))


def test_throttling_spaces_requests():
    clock = {"now": 0.0}
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        clock["now"] += seconds

    provider = make_provider(
        Transport(), request_interval=0.2, sleep=sleep, monotonic=lambda: clock["now"]
    )
    provider.fetch_series(SOFR, start=dt.date(2026, 8, 1))
    provider.fetch_series(SOFR, start=dt.date(2026, 8, 1))

    assert slept == [pytest.approx(0.2)]


def test_rate_limiting_and_server_errors_are_distinguished():
    too_many = HTTPError("u", 429, "Too Many Requests", {}, None)
    with pytest.raises(RateLimited):
        make_provider(Transport(failures=[too_many] * 3), retries=2).fetch_series(
            SOFR, start=dt.date(2026, 8, 1)
        )

    transport = Transport(failures=[HTTPError("u", 503, "busy", {}, None), None])
    _, observations = make_provider(transport, retries=2).fetch_series(
        SOFR, start=dt.date(2026, 8, 1)
    )
    assert observations
    assert len(transport.requests) == 2


def test_a_missing_resource_is_final():
    transport = Transport(failures=[HTTPError("u", 404, "Not Found", {}, None)])

    with pytest.raises(DataUnavailable):
        make_provider(transport, retries=3).fetch_series(SOFR, start=dt.date(2026, 8, 1))
    assert len(transport.requests) == 1


def test_attribution_matches_the_wording_the_terms_prescribe():
    text = attribution(2026)

    assert text == (
        "© 2026 Federal Reserve Bank of New York. Content from the New York Fed "
        "subject to the Terms of Use at newyorkfed.org."
    )


# --- recession probability workbook -------------------------------------------
#
# Cell layout mirrors the real allmonth.xls: a Date/Rec_prob header row, dates
# as "01-Jan-1959" text, probabilities as decimals with blank strings before the
# model's first forecast, and target months that reach into the future because
# the series predicts twelve months ahead.

RECESSION_ROWS = [
    ["Date", "10 Year Treasury Yield", "3 Month Treasury Yield",
     "3 Month Treasury Yield (Bond Equivalent Basis)", "Spread", "Rec_prob", "NBER_Rec"],
    ["01-Jan-1959", 4.02, 2.82, 2.88, 1.14, "", 0.0],
    ["01-May-2026", 4.4, 4.1, 4.12, 0.28, 0.0912, 0.0],
    ["01-Jun-2027", "", "", "", "", 0.16061881370338651, ""],
    ["01-Jul-2027", "", "", "", "", 0.15187350665955465, ""],
    # Malformed rows must stay absent, never clamped or guessed.
    ["01-Aug-2027", "", "", "", "", 1.5, ""],
    ["not-a-date", "", "", "", "", 0.5, ""],
]

RECESSION = NYFED_SERIES_BY_KEY["recession_prob"]


def make_recession_provider(rows=None, transport=None, **kwargs):
    from app.providers import nyfed as nyfed_module

    provider = make_provider(transport or Transport(body=b"ole2-bytes"), **kwargs)
    original = nyfed_module._extract_recession_rows
    nyfed_module._extract_recession_rows = lambda raw: rows if rows is not None else RECESSION_ROWS
    return provider, lambda: setattr(nyfed_module, "_extract_recession_rows", original)


def test_recession_probabilities_scale_to_percent_and_keep_future_months():
    provider, restore = make_recession_provider()
    try:
        metadata, observations = provider.fetch_series(RECESSION, start=dt.date(2016, 1, 1))
    finally:
        restore()

    values = dict(observations)
    assert values[dt.date(2026, 5, 1)] == pytest.approx(9.12)
    # The newest observations are legitimately dated in the future.
    assert values[dt.date(2027, 7, 1)] == pytest.approx(15.187350665955465)
    assert dt.date(2027, 8, 1) not in values  # probability above 1.0 is malformed
    assert dt.date(1959, 1, 1) not in values  # blank cell and before start
    assert metadata["units"] == "Percent"
    assert metadata["observation_end"] == "2027-07-01"


def test_recession_start_filter_trims_history_but_not_the_future():
    provider, restore = make_recession_provider()
    try:
        _, observations = provider.fetch_series(RECESSION, start=dt.date(2027, 1, 1))
    finally:
        restore()

    assert [date for date, _ in observations] == [dt.date(2027, 6, 1), dt.date(2027, 7, 1)]


def test_recession_workbook_without_headers_is_unavailable():
    provider, restore = make_recession_provider(rows=[["nothing", "here"]])
    try:
        with pytest.raises(DataUnavailable):
            provider.fetch_series(RECESSION, start=dt.date(2016, 1, 1))
    finally:
        restore()


def test_recession_dates_parse_without_locale():
    from app.providers.nyfed import _recession_date

    assert _recession_date("01-Jan-1959") == dt.date(1959, 1, 1)
    assert _recession_date("01-Dec-2027") == dt.date(2027, 12, 1)
    assert _recession_date("32-Jan-2027") is None
    assert _recession_date("01-XXX-2027") is None
