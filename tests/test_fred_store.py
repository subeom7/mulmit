from __future__ import annotations

import datetime as dt

from app.providers.fred import FRED_SERIES_BY_ID


def _metadata(series_id="DGS10", notes="Public domain series"):
    return {
        "id": series_id,
        "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
        "units": "Percent",
        "units_short": "%",
        "frequency": "Daily",
        "frequency_short": "D",
        "seasonal_adjustment": "Not Seasonally Adjusted",
        "seasonal_adjustment_short": "NSA",
        "observation_start": "1962-01-02",
        "observation_end": "2026-08-14",
        "last_updated": "2026-08-15 15:16:02-05",
        "notes": notes,
    }


def _save(db, observations, metadata=None):
    spec = FRED_SERIES_BY_ID["DGS10"]
    return db.save_fred_series(
        "DGS10",
        metadata or _metadata(),
        observations,
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
    )


def test_fred_metadata_and_observations_roundtrip(db):
    observations = [
        (dt.date(2026, 8, 13), 4.21),
        (dt.date(2026, 8, 14), 4.19),
    ]
    assert _save(db, observations) == 2

    record = db.get_fred_series("dgs10")
    assert record["title"].startswith("Market Yield")
    assert record["units_short"] == "%"
    assert record["observation_start"] == dt.date(1962, 1, 2)
    assert record["last_observation_date"] == dt.date(2026, 8, 14)
    assert record["observation_count"] == 2
    assert record["copyrighted"] is False
    assert db.load_fred_observations("DGS10") == observations


def test_fred_full_refresh_removes_observations_missing_from_new_vintage(db):
    _save(db, [
        (dt.date(2026, 8, 12), 4.20),
        (dt.date(2026, 8, 13), 4.21),
    ])
    _save(db, [
        (dt.date(2026, 8, 13), 4.22),
        (dt.date(2026, 8, 14), 4.19),
    ])

    assert db.load_fred_observations("DGS10") == [
        (dt.date(2026, 8, 13), 4.22),
        (dt.date(2026, 8, 14), 4.19),
    ]


def test_fred_error_preserves_last_good_data_and_schedules_retry(db):
    observations = [(dt.date(2026, 8, 14), 4.19)]
    _save(db, observations)
    assert db.stale_fred_series(["DGS10"], 3600) == []

    db.mark_fred_error("DGS10", "temporary upstream failure")
    record = db.get_fred_series("DGS10")
    assert record["status"] == "error"
    assert "temporary" in record["error"]
    assert db.load_fred_observations("DGS10") == observations
    assert db.stale_fred_series(["DGS10"], 3600) == ["DGS10"]


def test_copyright_notice_is_derived_from_provider_notes(db):
    _save(
        db,
        [(dt.date(2026, 8, 14), 14.2)],
        metadata=_metadata(notes="Copyright 2026. Reprinted with permission."),
    )
    assert db.get_fred_series("DGS10")["copyrighted"] is True
