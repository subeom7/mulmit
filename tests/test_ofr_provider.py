"""OFR Financial Stress Index CSV reader, driven from fixtures.

Pinned on purpose: one download serves every column, blank cells are missing
(never zero), the header is matched by exact name, and HTTP throttling
surfaces as RateLimited rather than an empty series.
"""

from __future__ import annotations

import datetime as dt
from urllib.error import HTTPError

import pytest

from app.providers.base import DataUnavailable, RateLimited
from app.providers.ofr import (
    OFR_CITATION_TEMPLATE,
    OFR_SERIES,
    OFR_SERIES_BY_KEY,
    OfrProvider,
)

CSV = (
    "﻿Date,OFR FSI,Credit,Equity valuation,Safe assets,Funding,Volatility,"
    "United States,Other advanced economies,Emerging markets\n"
    "2026-08-14,-2.817,-1.178,-0.614,-0.317,-0.104,-0.604,-1.364,-0.897,-0.555\n"
    "2026-08-17,-2.824,-1.171,-0.606,-0.319,-0.125,-0.602,-1.34,-0.928,-0.556\n"
    # A blank volatility cell: that day is simply missing for that column.
    "2026-08-18,-2.661,-1.156,-0.587,-0.315,-0.119,,-1.299,-0.813,-0.55\n"
    # Garbage rows never become numbers.
    "not-a-date,1,2,3,4,5,6,7,8,9\n"
    "2026-08-19,abc,-1.1,-0.5,-0.3,-0.1,-0.4,-1.2,-0.8,-0.5\n"
).encode()


class Transport:
    def __init__(self, body: bytes | Exception = CSV) -> None:
        self.body = body
        self.calls = 0

    def __call__(self, request, timeout):
        self.calls += 1
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def test_one_download_serves_every_column_and_blanks_stay_missing():
    transport = Transport()
    provider = OfrProvider(http_get=transport, sleep=lambda _s: None)
    start = dt.date(2026, 1, 1)

    metadata, fsi = provider.fetch_series(OFR_SERIES_BY_KEY["ofr_fsi"], start=start)
    _, volatility = provider.fetch_series(OFR_SERIES_BY_KEY["ofr_fsi_volatility"], start=start)
    _, credit = provider.fetch_series(OFR_SERIES_BY_KEY["ofr_fsi_credit"], start=start)

    assert transport.calls == 1
    assert fsi == (
        (dt.date(2026, 8, 14), -2.817),
        (dt.date(2026, 8, 17), -2.824),
        (dt.date(2026, 8, 18), -2.661),
    )
    # 08-18 is blank for volatility only; 08-19 is unparseable for the composite only.
    assert [date for date, _ in volatility] == [
        dt.date(2026, 8, 14), dt.date(2026, 8, 17), dt.date(2026, 8, 19),
    ]
    assert credit[-1] == (dt.date(2026, 8, 19), -1.1)
    assert metadata["title"] == "OFR 금융스트레스지수 (종합)"
    assert metadata["frequency_short"] == "D"
    assert metadata["units_short"] == "Index"
    assert metadata["observation_start"] == "2026-08-14"
    assert metadata["observation_end"] == "2026-08-18"
    assert "Office of Financial Research" in metadata["notes"]


def test_start_bound_filters_and_empty_window_is_unavailable():
    provider = OfrProvider(http_get=Transport(), sleep=lambda _s: None)
    _, rows = provider.fetch_series(OFR_SERIES_BY_KEY["ofr_fsi"], start=dt.date(2026, 8, 17))
    assert [date for date, _ in rows] == [dt.date(2026, 8, 17), dt.date(2026, 8, 18)]
    # Nothing on or after 08-20 in the file: an empty window is unavailable, not zeros.
    with pytest.raises(DataUnavailable):
        provider.fetch_series(OFR_SERIES_BY_KEY["ofr_fsi"], start=dt.date(2026, 8, 20))


def test_every_catalog_column_exists_in_the_file():
    provider = OfrProvider(http_get=Transport(), sleep=lambda _s: None)
    for spec in OFR_SERIES:
        _, rows = provider.fetch_series(spec, start=dt.date(2026, 1, 1))
        assert rows


def test_http_429_is_rate_limited_and_other_errors_unavailable():
    throttled = HTTPError("u", 429, "Too Many", {}, None)
    provider = OfrProvider(http_get=Transport(throttled), retries=0, sleep=lambda _s: None)
    with pytest.raises(RateLimited):
        provider.fetch_series(OFR_SERIES_BY_KEY["ofr_fsi"], start=dt.date(2026, 1, 1))

    broken = OfrProvider(http_get=Transport(b"garbage,without,date\n1,2,3\n"), sleep=lambda _s: None)
    with pytest.raises(DataUnavailable):
        broken.fetch_series(OFR_SERIES_BY_KEY["ofr_fsi"], start=dt.date(2026, 1, 1))


def test_citation_template_carries_the_access_date_slot():
    assert "{date}" in OFR_CITATION_TEMPLATE
    assert "financialresearch.gov/financial-stress-index" in OFR_CITATION_TEMPLATE
