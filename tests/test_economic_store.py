"""Provider-neutral macro storage.

The point of the new tables is that a series is identified by an internal key
and carries its provider and rights verdict as data, so connecting NY Fed or
BLS later is a row change rather than a schema change. These tests pin that
behaviour, the transitional fallback to the legacy FRED tables, and the
migration between them.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest
from fastapi.testclient import TestClient

from app import data_rights, ingest, store
from app.macro_dashboard import build_macro_series, build_macro_snapshot
from app.main import app
from app.providers.fred import FRED_SERIES_BY_ID, FRED_SERIES_BY_KEY

OBSERVATIONS = [(dt.date(2026, 8, 13), 4.21), (dt.date(2026, 8, 14), 4.19)]


def _save(db, series_key="treasury_10y", *, provider_id="fred", rights_status="approved",
          observations=None, provider_series_id=None, **overrides):
    spec = FRED_SERIES_BY_KEY[series_key]
    fields = {
        "title": spec.label_en,
        "units": "Percent",
        "units_short": "%",
        "frequency": "Daily",
        "frequency_short": "D",
        "seasonal_adjustment": "Not Seasonally Adjusted",
        "seasonal_adjustment_short": "NSA",
        "observation_start": "1990-01-02",
        "observation_end": "2026-08-14",
        "last_updated": "2026-08-15 08:38:01-05",
    }
    fields.update(overrides)
    return db.save_economic_series(
        series_key,
        provider_id=provider_id,
        provider_series_id=provider_series_id or spec.series_id,
        metadata_fields=fields,
        observations=OBSERVATIONS if observations is None else observations,
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
        rights_status=rights_status,
    )


def test_series_is_keyed_internally_and_records_its_provider(db):
    _save(db, provider_id="nyfed", provider_series_id="DGS10-NYFED")

    row = db.get_economic_series("treasury_10y")

    # The internal key is stable; the provider and its own id are data.
    assert row["series_key"] == "treasury_10y"
    assert row["provider_id"] == "nyfed"
    assert row["provider_series_id"] == "DGS10-NYFED"
    assert row["rights_status"] == "approved"
    # Provider-native units are preserved verbatim so nothing downstream guesses.
    assert row["units"] == "Percent"
    assert row["units_short"] == "%"
    assert row["seasonal_adjustment_short"] == "NSA"


def test_rights_status_defaults_to_pending_not_approved(db):
    spec = FRED_SERIES_BY_KEY["treasury_10y"]
    db.save_economic_series(
        "treasury_10y",
        provider_id="fred",
        provider_series_id=spec.series_id,
        metadata_fields={"title": "t"},
        observations=OBSERVATIONS,
        publisher="p",
        publisher_url="u",
        series_url="s",
    )

    assert db.get_economic_series("treasury_10y")["rights_status"] == "pending"


def test_refetching_the_same_vintage_is_idempotent(db):
    assert _save(db) == 2
    assert _save(db) == 2

    assert db.load_economic_observations("treasury_10y") == OBSERVATIONS


def test_a_revised_vintage_replaces_withdrawn_observations(db):
    _save(db)
    # The provider revised the series and dropped a day.
    _save(db, observations=[(dt.date(2026, 8, 14), 4.30)])

    assert db.load_economic_observations("treasury_10y") == [(dt.date(2026, 8, 14), 4.30)]


def test_observations_can_be_windowed(db):
    _save(db)

    assert db.load_economic_observations("treasury_10y", start=dt.date(2026, 8, 14)) == [
        (dt.date(2026, 8, 14), 4.19)
    ]
    assert db.load_economic_observations("treasury_10y", end=dt.date(2026, 8, 13)) == [
        (dt.date(2026, 8, 13), 4.21)
    ]


def test_empty_observations_are_refused_rather_than_stored(db):
    with pytest.raises(ValueError):
        _save(db, observations=[])


def test_error_marking_keeps_the_last_good_snapshot(db):
    _save(db)
    db.mark_economic_error("treasury_10y", "provider timeout")

    row = db.get_economic_series("treasury_10y")
    assert row["status"] == "error"
    assert row["error"] == "provider timeout"
    assert db.load_economic_observations("treasury_10y") == OBSERVATIONS


def test_listing_can_be_filtered_by_provider(db):
    _save(db, "treasury_10y", provider_id="fred")
    _save(db, "sofr", provider_id="nyfed")

    assert [row["series_key"] for row in db.list_economic_series(provider_id="nyfed")] == ["sofr"]
    assert len(db.list_economic_series()) == 2
    assert db.list_economic_series([]) == []


def test_staleness_covers_never_fetched_and_errored_series(db):
    _save(db)
    _save(db, "sofr")
    db.mark_economic_error("sofr", "boom")

    stale = db.stale_economic_series(["treasury_10y", "sofr", "unemployment"], 3600)

    assert "treasury_10y" not in stale  # fresh and ok
    assert "sofr" in stale  # errored
    assert "unemployment" in stale  # never fetched


# --- transition -------------------------------------------------------------


def _seed_legacy(db, series_id="DGS10", value=4.19, notes=""):
    spec = FRED_SERIES_BY_ID[series_id]
    db.save_fred_series(
        series_id,
        {
            "id": series_id,
            "title": spec.label_en,
            "units": "Percent",
            "units_short": "%",
            "frequency": "Daily",
            "frequency_short": "D",
            "notes": notes,
        },
        [(dt.date(2026, 8, 13), round(value - 0.02, 4)), (dt.date(2026, 8, 14), value)],
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
    )


def test_unmigrated_series_are_still_served_from_the_legacy_tables(db, fred_serving):
    _seed_legacy(db)

    item = next(
        row for row in build_macro_snapshot("max")["series"] if row["id"] == "DGS10"
    )

    assert item["latest"] == {"date": "2026-08-14", "value": 4.19}
    assert item["source"]["provider"] == "fred"
    assert item["source"]["provider_name"] == "FRED®"


def test_the_neutral_row_wins_over_a_stale_legacy_row(db, fred_serving):
    _seed_legacy(db, value=1.11)
    _save(db, observations=[(dt.date(2026, 8, 14), 9.99)])

    item = next(
        row for row in build_macro_snapshot("max")["series"] if row["key"] == "treasury_10y"
    )

    assert item["latest"] == {"date": "2026-08-14", "value": 9.99}


def test_migration_copies_rows_without_removing_the_originals(db, fred_serving):
    _seed_legacy(db)

    moved = ingest.migrate_macro_store()

    assert moved["series"] == 1
    assert moved["observations"] == 2
    assert db.get_economic_series("treasury_10y")["provider_series_id"] == "DGS10"
    assert db.get_economic_series("treasury_10y")["rights_status"] == "approved"
    # The legacy row is deliberately left in place so the move can be repeated.
    assert db.get_fred_series("DGS10") is not None
    assert db.load_economic_observations("treasury_10y") == [
        (dt.date(2026, 8, 13), 4.17),
        (dt.date(2026, 8, 14), 4.19),
    ]


def test_migration_carries_the_license_verdict_across(db):
    _seed_legacy(db, "VIXCLS", value=17.0)

    ingest.migrate_macro_store()

    assert db.get_economic_series("vix")["rights_status"] == "license_required"


def test_migration_is_repeatable(db, fred_serving):
    _seed_legacy(db)

    first = ingest.migrate_macro_store()
    second = ingest.migrate_macro_store()

    assert first["series"] == second["series"] == 1
    assert len(db.load_economic_observations("treasury_10y")) == 2


# --- rights -----------------------------------------------------------------


def test_a_row_marked_license_required_is_withheld_even_on_an_open_lane(db, fred_serving):
    _save(db, rights_status="license_required")

    item = next(
        row for row in build_macro_snapshot("max")["series"] if row["key"] == "treasury_10y"
    )

    assert item["status"] == "license_required"
    assert item["latest"] is None
    assert item["observations"] == []
    assert "4.19" not in str(item)


def test_a_pending_row_is_withheld_too(db, fred_serving):
    _save(db, rights_status="pending")

    assert data_rights.series_values_servable("fred", "pending") is False
    body = build_macro_snapshot("max")
    assert "DGS10" in body["restricted"]


def test_an_unrecognised_rights_string_fails_closed(db, fred_serving):
    _save(db, rights_status="probably_fine")

    assert data_rights.series_values_servable("fred", "probably_fine") is False
    assert "DGS10" in build_macro_snapshot("max")["restricted"]


def test_a_provider_copyright_note_overrides_an_approved_row(db, fred_serving):
    """The publisher's own wording outranks a verdict recorded earlier."""
    _save(db, rights_status="approved", notes="Copyright © Example Data Owner.")

    detail = build_macro_series("treasury_10y", "max")

    assert detail["series"]["status"] == "license_required"
    assert detail["series"]["observations"] == []


def test_detail_route_resolves_both_the_provider_id_and_the_internal_key(db, fred_serving):
    _save(db)
    client = TestClient(app)

    by_provider_id = client.get("/api/market/macro/DGS10?history=max")
    by_internal_key = client.get("/api/market/macro/treasury_10y?history=max")

    assert by_provider_id.status_code == 200
    assert by_internal_key.status_code == 200
    assert by_provider_id.json()["series"] == by_internal_key.json()["series"]


def test_status_counts_the_neutral_tables(db, fred_serving):
    _save(db)

    body = TestClient(app).get("/api/status").json()

    assert body["economic_series"] == 1
    assert body["economic_observations"] == 2
    assert body["last_economic_ingest"] is not None


def test_ingest_writes_only_to_the_neutral_tables(db, monkeypatch):
    """A closed lane still must not write anything."""
    monkeypatch.setattr("app.ingest.FredProvider", lambda *_a, **_k: pytest.fail("gated"))

    assert ingest.refresh_fred()["skipped"] == "disabled"
    assert store.list_economic_series() == []


# --- dialect compatibility --------------------------------------------------


def test_schema_and_upsert_compile_for_postgres_and_sqlite():
    """Deployment runs Postgres while tests and local dev run SQLite.

    Nothing else in the suite would notice a Postgres-only problem, and the
    upsert is the genuinely dialect-specific part: the two dialects expose
    ``ON CONFLICT DO UPDATE`` through different modules.
    """
    from sqlalchemy.dialects import postgresql, sqlite
    from sqlalchemy.schema import CreateIndex, CreateTable

    tables = (
        store.economic_series,
        store.economic_observations,
        store.sec_companies,
        store.insider_transactions,
    )
    for dialect_module in (postgresql, sqlite):
        dialect = dialect_module.dialect()
        for table in tables:
            CreateTable(table).compile(dialect=dialect)
            for index in table.indexes:
                CreateIndex(index).compile(dialect=dialect)
                # Postgres truncates identifiers at 63 bytes, which would
                # silently collide two long index names into one.
                assert len(index.name) < 63, index.name

            keys = [column.name for column in table.primary_key.columns]
            statement = dialect_module.insert(table).values([dict.fromkeys(keys)])
            statement.on_conflict_do_update(
                index_elements=keys,
                set_={
                    column.name: statement.excluded[column.name]
                    for column in table.columns
                    if column.name not in keys
                },
            ).compile(dialect=dialect)


@pytest.mark.skipif(
    not os.environ.get("MULMIT_TEST_DATABASE_URL"),
    reason="set MULMIT_TEST_DATABASE_URL to run against a live Postgres",
)
def test_round_trip_against_a_live_database(tmp_path, monkeypatch):
    """Opt-in end-to-end check against a real server.

        docker run --rm -e POSTGRES_PASSWORD=test -e POSTGRES_USER=stock \
          -e POSTGRES_DB=stock -p 55432:5432 postgres:16-alpine
        MULMIT_TEST_DATABASE_URL=postgresql+psycopg://stock:test@127.0.0.1:55432/stock \
          python -m pytest tests/test_economic_store.py -k live
    """
    store.reset(os.environ["MULMIT_TEST_DATABASE_URL"])
    try:
        store.init_db()
        with store.engine().begin() as conn:
            conn.execute(store.economic_observations.delete())
            conn.execute(store.economic_series.delete())
        _save(store)
        _save(store)  # idempotent second write exercises the upsert path
        assert store.load_economic_observations("treasury_10y") == OBSERVATIONS
        assert store.get_economic_series("treasury_10y")["provider_id"] == "fred"
    finally:
        store.reset()
