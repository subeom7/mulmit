"""The New York Fed lane end to end: gate, ingest, storage, API.

This is the first provider to occupy the neutral tables, so it is also the
first proof that a second macro lane can serve while the FRED lane stays shut.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, data_rights, ingest, store
from app.macro_dashboard import build_macro_snapshot
from app.main import app
from app.providers.fred import FRED_SERIES

OBSERVATIONS = (
    (dt.date(2026, 8, 12), 3.62),
    (dt.date(2026, 8, 13), 3.64),
)


class FakeNyFed:
    """Returns the same shape the real client produces, without the network."""

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
                "units": spec.units,
                "units_short": spec.units_short,
                "frequency": spec.frequency,
                "frequency_short": spec.frequency_short,
                "observation_start": OBSERVATIONS[0][0].isoformat(),
                "observation_end": OBSERVATIONS[-1][0].isoformat(),
                "notes": "",
            },
            OBSERVATIONS,
        )


@pytest.fixture
def nyfed(db, monkeypatch):
    fake = FakeNyFed()
    monkeypatch.setattr(config, "NYFED_ENABLED", True)
    monkeypatch.setattr(ingest, "NyFedProvider", lambda *_a, **_k: fake)
    return fake


def test_lane_is_closed_by_default_and_calls_nothing(db, monkeypatch):
    monkeypatch.setattr(
        ingest, "NyFedProvider", lambda *_a, **_k: pytest.fail("provider must not be built")
    )

    assert ingest.refresh_nyfed()["skipped"] == "disabled"
    assert store.list_economic_series(provider_id="nyfed") == []


def test_ingest_stores_all_four_series_with_approved_rights(db, nyfed):
    result = ingest.refresh_nyfed()

    assert result["updated"] == 4
    assert sorted(nyfed.calls) == [
        "effective_fed_funds", "recession_prob", "reverse_repo", "sofr",
    ]
    row = store.get_economic_series("sofr")
    assert row["provider_id"] == "nyfed"
    assert row["provider_series_id"] == "SOFR"
    assert row["rights_status"] == "approved"
    assert row["rights_evidence"] == "https://www.newyorkfed.org/privacy/termsofuse"
    assert row["publisher"] == "Federal Reserve Bank of New York"
    assert row["units"] == "Percent"


def test_a_second_pass_skips_fresh_series(db, nyfed):
    ingest.refresh_nyfed()
    nyfed.calls.clear()

    assert ingest.refresh_nyfed()["skipped"] == "fresh"
    assert nyfed.calls == []


def test_reverse_repo_keeps_its_own_units(db, nyfed):
    ingest.refresh_nyfed()

    row = store.get_economic_series("reverse_repo")
    assert row["units"] == "US Dollars"
    assert row["provider_series_id"] == "RRP"


def test_the_lane_serves_while_fred_stays_shut(db, nyfed):
    ingest.refresh_nyfed()

    response = TestClient(app).get("/api/market/macro?history=max")

    assert response.status_code == 200
    body = response.json()
    served = {item["key"] for item in body["series"]}
    assert served == {"sofr", "effective_fed_funds", "reverse_repo", "recession_prob"}
    assert body["lanes"]["enabled"] == ["nyfed"]
    # Every card sourced from a closed lane is reported as disabled, not missing.
    assert set(body["disabled"]).isdisjoint({"SOFR", "EFFR", "RRPONTSYD", "REC_PROB_12M"})
    assert len(body["disabled"]) == len(FRED_SERIES) - 4
    assert response.headers["x-data-source"] == "NYFED"


def test_served_values_carry_the_required_source_identifier(db, nyfed):
    ingest.refresh_nyfed()

    item = next(i for i in build_macro_snapshot("max")["series"] if i["key"] == "sofr")

    assert item["source"]["provider"] == "nyfed"
    assert item["source"]["provider_name"] == "Federal Reserve Bank of New York"
    assert item["source"]["provider_series_id"] == "SOFR"
    # The licence is conditional on this notice travelling with the data.
    assert "Federal Reserve Bank of New York" in item["rights"]["notice"]
    assert "newyorkfed.org" in item["rights"]["notice"]
    assert item["latest"] == {"date": "2026-08-13", "value": 3.64}


def test_a_copyright_note_does_not_withhold_a_first_party_series(db, nyfed, monkeypatch):
    """The New York Fed asserts copyright over content it then licenses to us.

    On the FRED lane a copyright note means a third party owns the series and it
    must be withheld. Applying that rule to a first-party publisher would empty
    a card we are explicitly permitted to show.
    """
    ingest.refresh_nyfed()
    with store.engine().begin() as conn:
        conn.execute(
            store.economic_series.update()
            .where(store.economic_series.c.series_key == "sofr")
            .values(notes="Copyright 2026 Federal Reserve Bank of New York.")
        )

    item = next(i for i in build_macro_snapshot("max")["series"] if i["key"] == "sofr")

    assert item["status"] != "license_required"
    assert item["latest"]["value"] == 3.64


def test_fred_cannot_take_back_a_series_the_ny_fed_owns(db, nyfed, monkeypatch):
    """Two lanes can name the same card; whoever holds the row keeps it.

    FRED still collects the twelve series nobody else claims — it just may not
    overwrite an approved New York Fed series with a weaker-rights copy.
    """
    ingest.refresh_nyfed()

    requested: list[str] = []

    class RecordingFred:
        def __init__(self, *_args, **_kwargs):
            pass

        def fetch_series(self, series_id):
            requested.append(series_id)
            raise RuntimeError("stop after recording the target")

    monkeypatch.setattr(config, "FRED_ENABLED", True)
    monkeypatch.setattr(config, "FRED_API_KEY", "k" * 32)
    monkeypatch.setattr(config, "FRED_INGEST_DELAY", 0.0)
    monkeypatch.setattr(config, "FRED_MAX_AGE", 0)  # make everything look stale
    monkeypatch.setattr(ingest, "FredProvider", RecordingFred)

    ingest.refresh_fred()

    assert requested, "FRED should still collect the series nobody else owns"
    for owned in ("SOFR", "EFFR", "RRPONTSYD"):
        assert owned not in requested
    # Research-file and FSC keys are never FRED downloads, owned or not:
    # their catalog ids do not exist on FRED and would 404 on the first cycle.
    for foreign in ("REC_PROB_12M", "FSC_KOSPI"):
        assert foreign not in requested
    assert store.get_economic_series("sofr")["provider_id"] == "nyfed"
    assert store.get_economic_series("sofr")["rights_status"] == "approved"


def test_a_failure_marks_the_series_without_dropping_history(db, nyfed, monkeypatch):
    ingest.refresh_nyfed()
    monkeypatch.setattr(config, "NYFED_MAX_AGE", 0)
    monkeypatch.setattr(
        ingest, "NyFedProvider", lambda *_a, **_k: FakeNyFed(RuntimeError("outage"))
    )

    result = ingest.refresh_nyfed()

    assert result["failed"] == 4
    assert store.get_economic_series("sofr")["status"] == "error"
    assert len(store.load_economic_observations("sofr")) == 2


def test_status_reports_the_lane(db, nyfed):
    lanes = TestClient(app).get("/api/status").json()["data_lanes"]

    assert lanes["macro:nyfed"] == {"status": "enabled", "gate": "NYFED_ENABLED"}
    assert lanes["macro:fred"]["status"] == "disabled"


def test_unregistered_lane_still_fails_closed(db):
    assert data_rights.macro_lane_enabled("nyfed") is False
    assert data_rights.series_values_servable("nyfed", "approved") is False


def test_the_snapshot_credits_the_lane_that_served_it(db, nyfed):
    """FRED is switched off; crediting it for New York Fed rates would be a lie."""
    ingest.refresh_nyfed()

    body = TestClient(app).get("/api/market/macro?history=max").json()

    assert body["provider"]["id"] == "nyfed"
    assert body["provider"]["name"] == "Federal Reserve Bank of New York"
    assert "FRED" not in body["provider"]["name"]
    providers = body["attribution"]["providers"]
    assert [entry["provider"] for entry in providers] == ["nyfed"]
    assert "newyorkfed.org" in providers[0]["terms_url"]
    # No FRED terms surface while the FRED lane is closed.
    assert "api_terms_url" not in body["attribution"]


def test_both_lanes_are_credited_when_both_serve(db, nyfed, monkeypatch):
    monkeypatch.setattr(config, "FRED_ENABLED", True)

    body = TestClient(app).get("/api/market/macro?history=max").json()

    assert body["provider"]["id"] == "multi-source"
    assert {entry["provider"] for entry in body["attribution"]["providers"]} == {"fred", "nyfed"}
