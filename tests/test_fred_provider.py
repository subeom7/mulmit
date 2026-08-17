from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from app.providers.base import DataUnavailable, RateLimited
from app.providers.fred import (
    FRED_SERIES,
    FRED_SERIES_BY_ID,
    FredConfigurationError,
    FredProvider,
    FredSeriesSpec,
)


def _payload(value) -> bytes:
    return json.dumps(value).encode("utf-8")


def test_dashboard_catalog_contains_the_required_official_series():
    """A subset check on purpose.

    The catalog grows as providers are connected, and a frozen exhaustive list
    would fail on every addition without ever catching a real problem. What
    matters is that the series the dashboard depends on stay present, that the
    restricted set stays exactly what it is, and that opting in to public
    display remains something a spec has to do deliberately.
    """
    assert FredSeriesSpec.__dataclass_fields__["public_web"].default is False
    assert {
        "VIXCLS",
        "T10Y2Y",
        "BAMLH0A0HYM2",
        "STLFSI4",
        "DGS10",
        "DGS2",
        "M2SL",
        "UNRATE",
        "ICSA",
        "WALCL",
        "WRESBAL",
        "RRPONTSYD",
        "WTREGEN",
        "WRMFNS",
        "SOFR",
        "EFFR",
        "IORB",
        "DCOILWTICO",
        "PCOPPUSDM",
    } <= set(FRED_SERIES_BY_ID)
    assert {spec.series_id for spec in FRED_SERIES if not spec.public_web} == {
        "VIXCLS",
        "BAMLH0A0HYM2",
        "PCOPPUSDM",
    }
    # Every key is unique; two cards sharing one would silently overwrite.
    assert len({spec.key for spec in FRED_SERIES}) == len(FRED_SERIES)


def test_fetch_series_parses_metadata_and_numeric_observations():
    calls = []

    def fake_get(request, timeout):
        calls.append((request, timeout))
        path = urlparse(request.full_url).path
        if path.endswith("/series"):
            return _payload({
                "seriess": [{
                    "id": "VIXCLS",
                    "title": "CBOE Volatility Index: VIX",
                    "units": "Index",
                    "frequency": "Daily, Close",
                    "notes": "Copyright, reprinted with permission.",
                }]
            })
        return _payload({
            "observations": [
                {"date": "2026-08-13", "value": "14.1"},
                {"date": "2026-08-14", "value": "."},
                {"date": "2026-08-15", "value": "15.2"},
                # A revised duplicate keeps the last value deterministically.
                {"date": "2026-08-15", "value": "15.3"},
            ]
        })

    provider = FredProvider(
        "a" * 32,
        timeout=7.5,
        http_get=fake_get,
        sleep=lambda _seconds: None,
    )
    result = provider.fetch_series("vixcls")

    assert result.metadata["id"] == "VIXCLS"
    assert [(date.isoformat(), value) for date, value in result.observations] == [
        ("2026-08-13", 14.1),
        ("2026-08-15", 15.3),
    ]
    assert len(calls) == 2
    for request, timeout in calls:
        query = parse_qs(urlparse(request.full_url).query)
        assert query["api_key"] == ["a" * 32]
        assert query["file_type"] == ["json"]
        assert timeout == 7.5
        assert request.headers["User-agent"] == "Mulmit/1.0"


def test_rate_limit_retries_then_raises_without_exposing_key():
    attempts = 0
    waits = []

    def limited(request, _timeout):
        nonlocal attempts
        attempts += 1
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    secret = "s" * 32
    provider = FredProvider(
        secret,
        retries=2,
        retry_backoff=0.25,
        http_get=limited,
        sleep=waits.append,
    )
    with pytest.raises(RateLimited) as exc_info:
        provider.fetch_metadata("DGS10")

    assert attempts == 3
    assert waits == [0.25, 0.5]
    assert secret not in str(exc_info.value)


def test_invalid_json_is_retried_and_reported_as_unavailable():
    attempts = 0

    def invalid(_request, _timeout):
        nonlocal attempts
        attempts += 1
        return b"not-json"

    provider = FredProvider(
        "a" * 32,
        retries=1,
        http_get=invalid,
        sleep=lambda _seconds: None,
    )
    with pytest.raises(DataUnavailable, match="Invalid or unavailable"):
        provider.fetch_metadata("DGS10")
    assert attempts == 2


def test_empty_api_key_fails_before_http():
    with pytest.raises(FredConfigurationError, match="FRED_API_KEY"):
        FredProvider("  ")
