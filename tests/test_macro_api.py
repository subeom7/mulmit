from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.macro_dashboard import MAX_PUBLIC_OBSERVATIONS, _downsample_observations
from app.main import app
from app.providers.fred import FRED_REQUIRED_NOTICE, FRED_SERIES_BY_ID


def _seed(db, *, notes: str = ""):
    spec = FRED_SERIES_BY_ID["DGS10"]
    db.save_fred_series(
        "DGS10",
        {
            "id": "DGS10",
            "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
            "units": "Percent",
            "units_short": "%",
            "frequency": "Daily, Close",
            "frequency_short": "D",
            "seasonal_adjustment": "Not Seasonally Adjusted",
            "seasonal_adjustment_short": "NSA",
            "observation_start": "1990-01-02",
            "observation_end": "2026-08-14",
            "last_updated": "2026-08-15 08:38:01-05",
            "notes": notes,
        },
        [
            (dt.date(2026, 8, 13), 14.0),
            (dt.date(2026, 8, 14), 14.25),
        ],
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
    )


def test_macro_overview_has_cards_series_freshness_and_attribution(db, fred_serving):
    _seed(db)
    client = TestClient(app)

    response = client.get("/api/market/macro?history=max")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"]["id"] == "fred"
    assert body["attribution"]["notice"] == FRED_REQUIRED_NOTICE
    assert body["attribution"]["terms_url"].startswith("https://fred.stlouisfed.org/")
    assert body["history"] == "max"
    treasury = next(item for item in body["series"] if item["id"] == "DGS10")
    assert treasury["source"]["publisher"] == "Board of Governors of the Federal Reserve System"
    assert treasury["units"]["long"] == "Percent"
    assert treasury["latest"] == {"date": "2026-08-14", "value": 14.25}
    assert treasury["change"]["value"] == 0.25
    assert treasury["freshness"]["status"] == "fresh"
    assert treasury["rights"]["copyrighted"] is False
    assert treasury["rights"]["public_display"] is True
    assert treasury["observations"] == [
        {"date": "2026-08-13", "value": 14.0},
        {"date": "2026-08-14", "value": 14.25},
    ]
    assert set(body["restricted"]) == {"VIXCLS", "BAMLH0A0HYM2", "PCOPPUSDM"}
    for series_id in body["restricted"]:
        restricted = next(item for item in body["series"] if item["id"] == series_id)
        assert restricted["status"] == "license_required"
        assert restricted["latest"] is None
        assert restricted["observations"] == []
        assert restricted["rights"]["public_display"] is False
    assert response.headers["x-data-source"] == "FRED"
    assert "stale-while-revalidate" in response.headers["cache-control"]


def test_macro_series_endpoint_and_unknown_series(db, fred_serving):
    _seed(db)
    client = TestClient(app)

    response = client.get("/api/market/macro/dgs10?history=max")
    assert response.status_code == 200
    assert response.json()["series"]["key"] == "treasury_10y"

    restricted = client.get("/api/market/macro/vixcls?history=max")
    assert restricted.status_code == 200
    assert restricted.json()["series"]["status"] == "license_required"
    assert restricted.json()["series"]["observations"] == []

    unknown = client.get("/api/market/macro/NOPE")
    assert unknown.status_code == 404


def test_provider_copyright_note_fails_closed_at_runtime(db, fred_serving):
    _seed(db, notes="Copyright © Example Data Owner. Reprinted with permission.")
    client = TestClient(app)

    overview = client.get("/api/market/macro?history=max")
    detail = client.get("/api/market/macro/dgs10?history=max")

    assert overview.status_code == 200
    assert "DGS10" in overview.json()["restricted"]
    treasury = next(item for item in overview.json()["series"] if item["id"] == "DGS10")
    assert treasury["status"] == "license_required"
    assert treasury["latest"] is None
    assert treasury["observations"] == []
    assert treasury["rights"]["public_display"] is False
    assert detail.status_code == 200
    assert detail.json()["series"]["status"] == "license_required"
    assert detail.json()["series"]["observations"] == []


def test_macro_history_is_validated_without_network_access(db, fred_serving):
    client = TestClient(app)
    assert client.get("/api/market/macro?history=forever").status_code == 422


def test_long_macro_history_is_bounded_and_keeps_endpoints():
    start = dt.date(2000, 1, 1)
    observations = [
        (start + dt.timedelta(days=index), float(index)) for index in range(5000)
    ]

    sampled = _downsample_observations(observations)

    assert len(sampled) == MAX_PUBLIC_OBSERVATIONS
    assert sampled[0] == observations[0]
    assert sampled[-1] == observations[-1]
