"""Mulmit Market Sentiment Gauge (experimental).

Pins what keeps a composite honest: it only uses inputs this deployment may
publish (OFR rows with approved rights, HIP-3 closes behind both gates), it
withholds itself below the minimum, it never imputes, its orientation is
"higher = more risk appetite", and it publishes the method and a history.
"""

from __future__ import annotations

import datetime as dt
import math

import pytest
from fastapi.testclient import TestClient

from app import config, hip3_history, store
from app.main import app
from app.sentiment_index import (
    COMPONENTS,
    MIN_COMPONENTS,
    MIN_HISTORY_POINTS,
    MOMENTUM_WINDOW,
    SentimentIndexUnavailable,
    build_sentiment_index,
)

TODAY = dt.date(2026, 8, 21)
DAYS = 200


def _closes(fn, days: int = DAYS, end: dt.date = TODAY) -> list[dict]:
    start = end - dt.timedelta(days=days - 1)
    return [
        {"date": (start + dt.timedelta(days=index)).isoformat(), "value": round(fn(index), 4)}
        for index in range(days)
    ]


def _seed_hip3(db, *, equity=None, gold=None):
    # Equity: gentle uptrend with a wiggle; gold: flat with a slower wiggle.
    equity = equity or _closes(lambda i: 6000 + i * 8 + 40 * math.sin(i / 3))
    gold = gold or _closes(lambda i: 4000 + 15 * math.sin(i / 9))
    store.save_report(hip3_history.CACHE_KEY, {
        "generated_at": "2026-08-21T12:00:00Z", "interval": "1d", "window_days": 366,
        "basis": hip3_history.BASIS,
        "series": {
            "xyz:SP500": {"as_of": "2026-08-21T23:59:59Z", "interval": "1d", "observations": equity},
            "xyz:GOLD": {"as_of": "2026-08-21T23:59:59Z", "interval": "1d", "observations": gold},
        },
    })
    hip3_history.clear_cache()


def _seed_ofr(db, series_key: str, fn, *, rights_status="approved", days: int = 400):
    observations = [
        (TODAY - dt.timedelta(days=days - 1 - index), float(fn(index))) for index in range(days)
    ]
    db.save_economic_series(
        series_key,
        provider_id="ofr",
        provider_series_id=series_key.upper(),
        metadata_fields={"title": series_key, "units": "Index"},
        observations=observations,
        publisher="Office of Financial Research",
        publisher_url="https://www.financialresearch.gov/",
        series_url="https://www.financialresearch.gov/financial-stress-index/",
        rights_status=rights_status,
    )


@pytest.fixture
def gauge_lanes(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "HIP3_HISTORY_ENABLED", True)
    monkeypatch.setattr(config, "OFR_ENABLED", True)
    hip3_history.clear_cache()
    yield
    hip3_history.clear_cache()


def _seed_all(db):
    _seed_hip3(db)
    # Volatility stress easing into its lows; credit stress at its highs.
    _seed_ofr(db, "ofr_fsi_volatility", lambda i: 1.0 - i * 0.004)
    _seed_ofr(db, "ofr_fsi_credit", lambda i: -1.0 + i * 0.004)


def test_all_five_inputs_compose_an_oriented_equal_weighted_gauge(gauge_lanes, db):
    _seed_all(db)

    index = build_sentiment_index(as_of=TODAY)

    by_key = {item["key"]: item for item in index["components"]}
    assert set(by_key) == {component.key for component in COMPONENTS}
    assert index["missing"] == []
    # Volatility at its five-year low: inverted, so it scores as strong risk appetite.
    assert by_key["ofr_fsi_volatility"]["inverted"] is True
    assert by_key["ofr_fsi_volatility"]["percentile"] < 1.0
    assert by_key["ofr_fsi_volatility"]["score"] > 99.0
    # Credit at its high: inverted, so it scores as strong risk-off.
    assert by_key["ofr_fsi_credit"]["score"] < 1.0
    # Perp-derived inputs were computed from the stored closes.
    assert by_key["sp500_momentum"]["observations"] == DAYS - MOMENTUM_WINDOW + 1
    assert by_key["sp500_momentum"]["unit"].endswith("MA")
    assert by_key["equity_vs_gold"]["observations"] > MIN_HISTORY_POINTS
    scores = [item["score"] for item in index["components"]]
    assert index["score"] == pytest.approx(round(sum(scores) / len(scores), 1))
    assert 0.0 <= index["score"] <= 100.0
    assert index["method"]["weighting"] == "equal"
    assert index["method"]["orientation"].startswith("higher")
    assert index["experimental"] is True
    assert "Fear & Greed" in index["disclaimer"]["en"]
    # A history exists, is dated, and never has fewer than the minimum inputs.
    assert index["observations"]
    assert index["observations"][-1]["date"] == TODAY.isoformat()
    assert all(item["components"] >= MIN_COMPONENTS for item in index["observations"])
    assert all(0.0 <= item["value"] <= 100.0 for item in index["observations"])


def test_closing_the_hip3_history_gate_leaves_too_few_inputs(gauge_lanes, db, monkeypatch):
    _seed_all(db)
    monkeypatch.setattr(config, "HIP3_HISTORY_ENABLED", False)
    hip3_history.clear_cache()

    with pytest.raises(SentimentIndexUnavailable) as caught:
        build_sentiment_index(as_of=TODAY)
    assert caught.value.available == 2
    assert caught.value.required == MIN_COMPONENTS


def test_a_series_the_deployment_may_not_publish_is_not_used(gauge_lanes, db):
    _seed_all(db)
    _seed_ofr(db, "ofr_fsi_credit", lambda i: 0.0, rights_status="license_required")

    index = build_sentiment_index(as_of=TODAY)

    assert "ofr_fsi_credit" in index["missing"]
    assert "ofr_fsi_credit" not in {item["key"] for item in index["components"]}


def test_short_perp_history_is_dropped_not_imputed(gauge_lanes, db):
    # 70 closes: realized vol (21-close window) gets 50 points, momentum (50-day
    # MA) gets 21, relative return gets 50 — all below MIN_HISTORY_POINTS.
    _seed_hip3(db, equity=_closes(lambda i: 6000 + i, days=70), gold=_closes(lambda i: 4000.0, days=70))
    _seed_ofr(db, "ofr_fsi_volatility", lambda i: 1.0 - i * 0.004)
    _seed_ofr(db, "ofr_fsi_credit", lambda i: -1.0 + i * 0.004)

    with pytest.raises(SentimentIndexUnavailable) as caught:
        build_sentiment_index(as_of=TODAY)
    assert caught.value.available == 2


def test_api_serves_the_gauge_and_reports_insufficient_inputs_as_503(gauge_lanes, db):
    client = TestClient(app)
    response = client.get("/api/market/sentiment")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "sentiment_index_unavailable"

    _seed_all(db)
    response = client.get("/api/market/sentiment")
    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "market_sentiment"
    assert len(body["components"]) == 5
    assert body["band"]["en"] in {"Strong risk-off", "Risk-off", "Neutral", "Risk-on", "Strong risk-on"}
    assert response.headers["cache-control"] == "public, max-age=300"
