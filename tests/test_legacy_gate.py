from __future__ import annotations

from fastapi.testclient import TestClient

from app import config, ingest
from app.main import app


def test_public_default_serves_split_pages_and_keeps_analytics_route(db):
    client = TestClient(app)

    root = client.get("/")
    korea = client.get("/kr")
    us = client.get("/us")
    legacy = client.get("/monitor")
    analytics = client.get("/analytics")

    assert root.status_code == 200
    assert 'window.MULMIT_PAGE = "landing"' in root.text
    assert korea.status_code == 200
    assert 'window.MULMIT_PAGE = "kr"' in korea.text
    assert us.status_code == 200
    assert 'window.MULMIT_PAGE = "us"' in us.text
    # The pre-split combined monitor stays as the page layer's reference.
    assert legacy.status_code == 200
    assert "MULMIT_PAGE" not in legacy.text
    assert analytics.status_code == 200
    assert 'id="ticker"' in analytics.text


def test_legacy_public_apis_fail_closed_with_migration_response(db):
    client = TestClient(app)

    for path in (
        "/api/market/sectors",
        "/api/metrics?ticker=AAPL",
        "/api/correlation?tickers=SPY,TLT",
    ):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "legacy_price_data_disabled"


def test_status_discloses_disabled_legacy_provider(db):
    response = TestClient(app).get("/api/status")

    assert response.status_code == 200
    assert response.json()["provider"] == "disabled"
    assert response.json()["legacy_provider"] == config.PROVIDER
    assert response.json()["legacy_price_data_enabled"] is False


def test_disabled_ingest_refreshes_fred_without_calling_legacy_provider(db, monkeypatch):
    fred_calls = []

    monkeypatch.setattr(config, "LEGACY_PRICE_DATA_ENABLED", False)
    monkeypatch.setattr(ingest, "refresh_fred", lambda: fred_calls.append(True) or {"updated": 1})
    monkeypatch.setattr(
        ingest,
        "get_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy provider must not be constructed")
        ),
    )

    result = ingest.run_once()

    assert result["skipped"] == "legacy_price_data_disabled"
    assert result["attempted"] == 0
    assert result["fred"] == {"updated": 1}
    assert fred_calls == [True]


def test_disabled_riskfree_refresh_never_constructs_provider(db, monkeypatch):
    monkeypatch.setattr(config, "LEGACY_PRICE_DATA_ENABLED", False)
    monkeypatch.setattr(
        ingest,
        "get_provider",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy provider must not be constructed")
        ),
    )

    ingest._refresh_macro()

    assert db.load_macro("riskfree") is None
