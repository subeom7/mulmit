"""The OFR lane end to end: gate, ingest, storage, API, citation."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, ingest, store
from app.macro_dashboard import build_macro_snapshot
from app.main import app
from app.providers.ofr import OFR_SERIES

OBSERVATIONS = (
    (dt.date(2026, 8, 17), -0.602),
    (dt.date(2026, 8, 18), -0.484),
)


class FakeOfr:
    def __init__(self, failure=None):
        self.calls: list[str] = []
        self.failure = failure

    def fetch_series(self, spec, *, start, end=None):
        self.calls.append(spec.series_key)
        if self.failure:
            raise self.failure
        return (
            {
                "title": spec.title,
                "units": "Index",
                "units_short": "Index",
                "frequency": "Daily, business days",
                "frequency_short": "D",
                "observation_start": OBSERVATIONS[0][0].isoformat(),
                "observation_end": OBSERVATIONS[-1][0].isoformat(),
                "notes": "",
            },
            OBSERVATIONS,
        )


@pytest.fixture
def ofr(db, monkeypatch):
    fake = FakeOfr()
    monkeypatch.setattr(config, "OFR_ENABLED", True)
    monkeypatch.setattr(ingest, "OfrProvider", lambda *_a, **_k: fake)
    return fake


def test_lane_is_closed_by_default_and_builds_nothing(db, monkeypatch):
    monkeypatch.setattr(
        ingest, "OfrProvider", lambda *_a, **_k: pytest.fail("provider must not be built")
    )
    assert ingest.refresh_ofr()["skipped"] == "disabled"
    assert store.list_economic_series(provider_id="ofr") == []


def test_ingest_stores_the_composite_and_five_categories_as_approved(db, ofr):
    result = ingest.refresh_ofr()

    assert result["updated"] == len(OFR_SERIES) == 6
    assert sorted(ofr.calls) == sorted(spec.series_key for spec in OFR_SERIES)
    row = store.get_economic_series("ofr_fsi_volatility")
    assert row["provider_id"] == "ofr"
    assert row["provider_series_id"] == "OFR_FSI_VOLATILITY"
    assert row["rights_status"] == "approved"
    assert row["rights_evidence"] == "https://www.financialresearch.gov/legal-notices/"
    assert "Office of Financial Research" in row["publisher"]


def test_a_second_pass_skips_fresh_series(db, ofr):
    ingest.refresh_ofr()
    ofr.calls.clear()
    assert ingest.refresh_ofr()["skipped"] == "fresh"
    assert ofr.calls == []


def test_the_lane_serves_with_citation_and_access_date(db, ofr):
    ingest.refresh_ofr()

    response = TestClient(app).get("/api/market/macro?history=max")
    assert response.status_code == 200
    body = response.json()
    served = {item["key"] for item in body["series"]}
    assert {"ofr_fsi", "ofr_fsi_volatility", "ofr_fsi_credit"} <= served
    assert body["lanes"]["enabled"] == ["ofr"]
    assert response.headers["x-data-source"] == "OFR"

    item = next(i for i in build_macro_snapshot("max")["series"] if i["key"] == "ofr_fsi_volatility")
    assert item["source"]["provider"] == "ofr"
    assert item["source"]["provider_name"] == "Office of Financial Research (U.S. Treasury)"
    assert item["latest"] == {"date": "2026-08-18", "value": -0.484}
    citation = item["rights"]["citation"]
    assert citation.startswith('Office of Financial Research, "OFR Financial Stress Index,"')
    assert "(accessed " in citation and "{date}" not in citation
    assert "Office of Financial Research" in item["rights"]["notice"]
    # Attribution block names the lane and its legal notices page.
    providers = body["attribution"]["providers"]
    assert any(entry["provider"] == "ofr" and "legal-notices" in entry["terms_url"] for entry in providers)
