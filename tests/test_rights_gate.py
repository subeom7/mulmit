"""Serving-side rights gates.

The point of these tests is the failure the previous release shipped with:
``FRED_ENABLED=false`` stopped ingestion but not serving, so a database seeded
while the flag was on kept publishing those numbers. Every assertion here is
about what leaves the process, not about what is stored.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, data_rights
from app.macro_dashboard import MacroDataDisabled, build_macro_series, build_macro_snapshot
from app.main import app
from app.providers.fred import FRED_SERIES, FRED_SERIES_BY_ID, FRED_SERIES_BY_KEY

MACRO_PATHS = ("/api/market/macro?history=max", "/api/market/macro/dgs10?history=max")


def _seed_fred(db, series_id: str = "DGS10", value: float = 14.25) -> None:
    """Simulate a production database that was filled before the flag flipped."""
    spec = FRED_SERIES_BY_ID[series_id]
    db.save_fred_series(
        series_id,
        {
            "id": series_id,
            "title": spec.label_en,
            "units": "Percent",
            "units_short": "%",
            "frequency": "Daily, Close",
            "frequency_short": "D",
            "observation_start": "1990-01-02",
            "observation_end": "2026-08-14",
            "last_updated": "2026-08-15 08:38:01-05",
            "notes": "",
        },
        [(dt.date(2026, 8, 13), value - 0.25), (dt.date(2026, 8, 14), value)],
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
    )


def _seed_economic(
    db,
    series_key: str,
    *,
    provider_id: str,
    provider_series_id: str,
    value: float,
    rights_status: str = "approved",
) -> None:
    spec = FRED_SERIES_BY_KEY[series_key]
    db.save_economic_series(
        series_key,
        provider_id=provider_id,
        provider_series_id=provider_series_id,
        metadata_fields={
            "title": spec.label_en,
            "units": "Percent",
            "units_short": "%",
            "frequency": "Daily",
            "frequency_short": "D",
        },
        observations=[(dt.date(2026, 8, 13), value - 0.25), (dt.date(2026, 8, 14), value)],
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
        rights_status=rights_status,
    )


@pytest.mark.parametrize("path", MACRO_PATHS)
def test_seeded_fred_rows_are_withheld_while_the_lane_is_closed(db, path):
    _seed_fred(db)

    response = TestClient(app).get(path)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "macro_data_disabled"
    assert response.headers["cache-control"] == "no-store"
    # The rows are still there; only the serving path refuses them.
    assert db.get_fred_series("DGS10")["observation_count"] == 2
    assert "14.25" not in response.text


def test_disabled_macro_response_never_carries_a_public_cache_header(db):
    _seed_fred(db)

    response = TestClient(app).get("/api/market/macro?history=max")

    assert "public" not in response.headers.get("cache-control", "")
    assert "stale-while-revalidate" not in response.headers.get("cache-control", "")


def test_assembler_fails_closed_even_when_a_route_is_bypassed(db):
    """Defence in depth: the reader refuses without help from the route layer."""
    _seed_fred(db)

    with pytest.raises(MacroDataDisabled):
        build_macro_snapshot("max")
    with pytest.raises(MacroDataDisabled):
        build_macro_series("DGS10", "max")


def test_unknown_series_still_reports_not_found_not_disabled(db, fred_serving):
    assert TestClient(app).get("/api/market/macro/NOPE").status_code == 404


def test_gate_is_scoped_to_the_provider_lane_not_the_whole_macro_route(db, monkeypatch):
    """An approved lane must serve even while the FRED lane stays closed.

    The provider now comes from the stored row rather than from the catalog, so
    this exercises the real mechanism: one series collected as ``nyfed``, the
    rest still FRED-sourced and therefore withheld.
    """
    monkeypatch.setitem(data_rights._MACRO_LANES, "nyfed", lambda: True)
    _seed_fred(db)  # DGS10 in the legacy tables, FRED lane, closed
    _seed_economic(db, "sofr", provider_id="nyfed", provider_series_id="SOFR", value=4.5)

    response = TestClient(app).get("/api/market/macro?history=max")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["series"]] == ["SOFR"]
    assert body["series"][0]["latest"] == {"date": "2026-08-14", "value": 4.5}
    assert body["series"][0]["source"]["provider"] == "nyfed"
    assert body["series"][0]["source"]["provider_name"] == "Federal Reserve Bank of New York"
    # The closed lane is reported as disabled, which is not the same claim as
    # "we never collected this".
    assert "DGS10" in body["disabled"]
    assert "DGS10" not in body["missing"]
    assert body["lanes"]["enabled"] == ["nyfed"]
    assert len(body["disabled"]) == len(FRED_SERIES) - 1
    assert "14.25" not in response.text


def test_open_fred_lane_serves_the_same_seeded_rows(db, fred_serving):
    _seed_fred(db)

    response = TestClient(app).get("/api/market/macro?history=max")

    assert response.status_code == 200
    treasury = next(item for item in response.json()["series"] if item["id"] == "DGS10")
    assert treasury["latest"] == {"date": "2026-08-14", "value": 14.25}
    assert response.json()["disabled"] == []


@pytest.mark.parametrize("path", ("/api/market/assets?history=3y", "/api/market/weekend"))
def test_hip3_endpoints_withhold_values_until_display_rights_are_confirmed(db, path):
    response = TestClient(app).get(path)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "hip3_public_display_pending_rights"
    assert detail["status"] == "pending_rights"
    assert response.headers["cache-control"] == "no-store"


def test_hip3_gate_runs_before_any_provider_call(db, monkeypatch):
    """A closed lane must not even reach out to Hyperliquid."""
    monkeypatch.setattr(
        "app.main.build_asset_snapshot",
        lambda history: pytest.fail("provider must not be consulted while gated"),
    )

    assert TestClient(app).get("/api/market/assets?history=3y").status_code == 503


def test_status_reports_every_lane_gate(db):
    body = TestClient(app).get("/api/status").json()

    lanes = body["data_lanes"]
    assert lanes["legacy_price_data"]["status"] == "disabled"
    assert lanes["hyperliquid_hip3"]["status"] == "pending_rights"
    assert lanes["macro:fred"] == {"status": "disabled", "gate": "FRED_ENABLED"}


def test_unregistered_provider_lane_is_never_servable(db, monkeypatch):
    monkeypatch.setattr(config, "FRED_ENABLED", True)

    assert data_rights.macro_lane_enabled("fred") is True
    assert data_rights.macro_lane_enabled("some_vendor_we_never_reviewed") is False
