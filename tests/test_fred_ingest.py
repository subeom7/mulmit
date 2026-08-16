from __future__ import annotations

import datetime as dt

from app import config, ingest
from app.providers.base import DataUnavailable
from app.providers.fred import FRED_SERIES_BY_ID, FredSeriesData


class FakeFredProvider:
    def __init__(self, failure=None):
        self.calls = []
        self.failure = failure

    def fetch_series(self, series_id):
        self.calls.append(series_id)
        if self.failure:
            raise self.failure
        return FredSeriesData(
            metadata={
                "id": series_id,
                "title": "10-Year Treasury Rate",
                "units": "Percent",
                "units_short": "%",
                "frequency": "Daily",
                "frequency_short": "D",
                "observation_start": "2026-08-13",
                "observation_end": "2026-08-14",
            },
            observations=(
                (dt.date(2026, 8, 13), 4.21),
                (dt.date(2026, 8, 14), 4.19),
            ),
        )


def _configure(monkeypatch, fake):
    monkeypatch.setattr(config, "FRED_ENABLED", True)
    monkeypatch.setattr(config, "FRED_API_KEY", "a" * 32)
    monkeypatch.setattr(config, "FRED_INGEST_DELAY", 0.0)
    monkeypatch.setattr(config, "FRED_MAX_AGE", 3600)
    monkeypatch.setattr(ingest, "FRED_SERIES", (FRED_SERIES_BY_ID["DGS10"],))
    monkeypatch.setattr(ingest, "FredProvider", lambda *_args, **_kwargs: fake)


def test_fred_ingest_persists_then_skips_fresh_series(db, monkeypatch):
    fake = FakeFredProvider()
    _configure(monkeypatch, fake)

    first = ingest.refresh_fred()
    second = ingest.refresh_fred()

    assert first == {
        "attempted": 1,
        "updated": 1,
        "failed": 0,
        "rate_limited": 0,
        "observations": 2,
    }
    assert second["skipped"] == "fresh"
    assert fake.calls == ["DGS10"]
    assert db.get_fred_series("DGS10")["status"] == "ok"


def test_fred_ingest_failure_isolated_and_retryable(db, monkeypatch):
    fake = FakeFredProvider(DataUnavailable("temporary FRED outage"))
    _configure(monkeypatch, fake)

    result = ingest.refresh_fred()

    assert result["failed"] == 1
    assert result["updated"] == 0
    assert db.get_fred_series("DGS10")["status"] == "error"
    assert db.stale_fred_series(["DGS10"], 3600) == ["DGS10"]


def test_fred_missing_key_does_not_disable_price_ingestion(db, monkeypatch):
    monkeypatch.setattr(config, "FRED_ENABLED", True)
    monkeypatch.setattr(config, "FRED_API_KEY", "")

    assert ingest.refresh_fred()["skipped"] == "not_configured"
