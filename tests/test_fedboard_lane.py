"""The Federal Reserve Board lane end to end."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, ingest, store
from app.macro_dashboard import build_macro_snapshot
from app.main import app
from app.providers.fedboard import FEDBOARD_DERIVED, FEDBOARD_SERIES

TEN_YEAR = ((dt.date(2026, 8, 12), 4.68), (dt.date(2026, 8, 13), 4.63))
TWO_YEAR = ((dt.date(2026, 8, 12), 4.20), (dt.date(2026, 8, 13), 4.15))
SPREAD = ((dt.date(2026, 8, 12), 0.48), (dt.date(2026, 8, 13), 0.48))
FX = ((dt.date(2026, 8, 12), 1410.5), (dt.date(2026, 8, 13), 1409.94))


class FakeFedBoard:
    def __init__(self, failure=None):
        self.calls: list[str] = []
        self.failure = failure

    def _payload(self, spec, rows):
        return (
            {
                "title": spec.title,
                "units": spec.units,
                "units_short": spec.units_short,
                "frequency": spec.frequency,
                "frequency_short": spec.frequency_short,
                "observation_start": rows[0][0].isoformat(),
                "observation_end": rows[-1][0].isoformat(),
                "release": "H.15 Selected Interest Rates",
                "notes": "",
            },
            rows,
        )

    def fetch_series(self, spec, *, start=None):
        self.calls.append(spec.series_key)
        if self.failure:
            raise self.failure
        rows = {"treasury_10y": TEN_YEAR, "treasury_2y": TWO_YEAR}.get(spec.series_key, FX)
        return self._payload(spec, rows)

    def fetch_derived(self, spec, *, start=None):
        self.calls.append(spec.series_key)
        if self.failure:
            raise self.failure
        metadata, rows = self._payload(spec, SPREAD)
        metadata["derivation"] = spec.provider_series_id
        return metadata, rows


@pytest.fixture
def fedboard(db, monkeypatch):
    fake = FakeFedBoard()
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", True)
    monkeypatch.setattr(ingest, "FedBoardProvider", lambda *_a, **_k: fake)
    return fake


def test_lane_is_closed_by_default_and_downloads_nothing(db, monkeypatch):
    monkeypatch.setattr(
        ingest, "FedBoardProvider", lambda *_a, **_k: pytest.fail("must not be built")
    )

    assert ingest.refresh_fedboard()["skipped"] == "disabled"
    assert store.list_economic_series(provider_id="federal_reserve") == []


def test_ingest_stores_published_and_derived_series(db, fedboard):
    result = ingest.refresh_fedboard()

    assert result["updated"] == len(FEDBOARD_SERIES) + len(FEDBOARD_DERIVED)
    ten = store.get_economic_series("treasury_10y")
    assert ten["provider_id"] == "federal_reserve"
    assert ten["provider_series_id"] == "RIFLGFCY10_N.B"
    assert ten["rights_status"] == "approved"
    assert ten["units"] == "Percent per year"

    spread = store.get_economic_series("yield_curve")
    # The derivation is recorded so the number can be traced back to its inputs.
    assert spread["provider_series_id"] == "RIFLGFCY10_N.B - RIFLGFCY02_N.B"
    assert spread["units_short"] == "%p"


def test_inputs_are_collected_before_what_is_derived_from_them(db, fedboard):
    ingest.refresh_fedboard()

    assert fedboard.calls.index("treasury_10y") < fedboard.calls.index("yield_curve")
    assert fedboard.calls.index("treasury_2y") < fedboard.calls.index("yield_curve")


def test_the_spread_matches_its_inputs(db, fedboard):
    ingest.refresh_fedboard()

    ten = dict(store.load_economic_observations("treasury_10y"))
    two = dict(store.load_economic_observations("treasury_2y"))
    spread = dict(store.load_economic_observations("yield_curve"))

    for date, value in spread.items():
        assert value == pytest.approx(ten[date] - two[date])


def test_the_cards_are_served_with_their_own_provider(db, fedboard):
    ingest.refresh_fedboard()

    body = TestClient(app).get("/api/market/macro?history=max").json()
    served = {item["key"]: item for item in body["series"]}

    assert {"treasury_10y", "treasury_2y", "yield_curve"} <= set(served)
    # H.10 rates arrive from the same lane and the same archive mechanism.
    assert served["fx_usdkrw"]["latest"] == {"date": "2026-08-13", "value": 1409.94}
    assert served["fx_usdkrw"]["units"]["short"] == "KRW/USD"
    assert served["fx_eurusd"]["units"]["short"] == "USD/EUR"
    assert served["treasury_10y"]["latest"] == {"date": "2026-08-13", "value": 4.63}
    assert served["yield_curve"]["latest"] == {"date": "2026-08-13", "value": 0.48}
    assert served["treasury_10y"]["source"]["provider"] == "federal_reserve"
    assert served["treasury_10y"]["source"]["provider_name"] == "Federal Reserve Board"
    assert body["provider"]["id"] == "federal_reserve"


def test_a_second_pass_skips_fresh_series(db, fedboard):
    ingest.refresh_fedboard()
    fedboard.calls.clear()

    assert ingest.refresh_fedboard()["skipped"] == "fresh"
    assert fedboard.calls == []


def test_a_failure_keeps_the_previous_snapshot(db, fedboard, monkeypatch):
    ingest.refresh_fedboard()
    monkeypatch.setattr(config, "FEDBOARD_MAX_AGE", 0)
    monkeypatch.setattr(
        ingest, "FedBoardProvider", lambda *_a, **_k: FakeFedBoard(RuntimeError("archive down"))
    )

    result = ingest.refresh_fedboard()

    assert result["failed"] == len(FEDBOARD_SERIES) + len(FEDBOARD_DERIVED)
    assert store.get_economic_series("treasury_10y")["status"] == "error"
    assert len(store.load_economic_observations("treasury_10y")) == 2


def test_status_names_the_variable_that_actually_exists(db, fedboard):
    """A gate name derived from the provider id would say FEDERAL_RESERVE_ENABLED."""
    lanes = TestClient(app).get("/api/status").json()["data_lanes"]

    assert lanes["macro:federal_reserve"] == {"status": "enabled", "gate": "FEDBOARD_ENABLED"}


def test_two_lanes_can_serve_together(db, fedboard, monkeypatch):
    """The Board publishes rates; the New York Fed publishes its own."""
    ingest.refresh_fedboard()
    monkeypatch.setattr(config, "NYFED_ENABLED", True)
    store.save_economic_series(
        "sofr",
        provider_id="nyfed",
        provider_series_id="SOFR",
        metadata_fields={"title": "SOFR", "units": "Percent"},
        observations=[(dt.date(2026, 8, 13), 3.62)],
        publisher="Federal Reserve Bank of New York",
        publisher_url="https://www.newyorkfed.org/",
        series_url="https://www.newyorkfed.org/markets/reference-rates",
        rights_status="approved",
    )

    body = build_macro_snapshot("max")
    served = {item["key"]: item["source"]["provider"] for item in body["series"]}

    assert served["treasury_10y"] == "federal_reserve"
    assert served["sofr"] == "nyfed"
    assert body["provider"]["id"] == "multi-source"
    assert {entry["provider"] for entry in body["attribution"]["providers"]} == {
        "nyfed",
        "federal_reserve",
    }
