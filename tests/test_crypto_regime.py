"""Market regime and the per-card heat badge — breadth arithmetic, composition and the cached half."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_market, crypto_regime, crypto_signal, ingest, store
from app.main import app
from app.providers.base import DataUnavailable, RateLimited

NOW = dt.datetime(2026, 8, 22, 6, 0, tzinfo=dt.UTC)
BASELINE = crypto_signal.FUNDING_BASELINE_APR


def _market(symbol: str, *, apr: float, change: float, volume: float = 5_000_000.0, price: float = 100.0) -> dict[str, Any]:
    """A dex market whose funding APR works out to ``apr`` (hourly × 24 × 365)."""
    return {
        "symbol": symbol, "dex": "main", "metadata": {"name": symbol},
        "context": {"markPx": str(price), "oraclePx": str(price), "prevDayPx": str(price / (1 + change / 100)),
                    "dayNtlVlm": str(volume), "openInterest": "1000", "funding": str(apr / 100 / (24 * 365))},
    }


def _snapshot(markets: list[dict[str, Any]]) -> dict[str, Any]:
    return {"dex": "main", "fetched_at": "2026-08-22T06:00:00Z", "as_of": "2026-08-22T06:00:00Z",
            "cached": False, "stale": False, "age_seconds": 0.0, "markets": markets}


# Four liquid markets: two crowded (far from baseline), three advancing; one illiquid market is ignored.
SNAPSHOT = _snapshot([
    _market("BTC", apr=BASELINE + 1.0, change=3.0, price=77000.0),
    _market("ETH", apr=BASELINE, change=2.0, price=2500.0),
    _market("DOGE", apr=BASELINE + 200.0, change=40.0, price=0.09),
    _market("SOL", apr=BASELINE - 30.0, change=-2.0, price=95.0),
    _market("DUST", apr=BASELINE + 500.0, change=90.0, volume=1000.0),
])


def _candles(count: int = 200, step: float = 1.004) -> list[dict[str, Any]]:
    rows = []
    price = 100.0
    for index in range(count):
        rows.append({"t": 1_780_000_000_000 + index * 86_400_000, "T": 1_780_000_000_000 + (index + 1) * 86_400_000 - 1,
                     "o": str(price), "c": str(price), "h": str(price * 1.01), "l": str(price * 0.99), "v": "10", "n": 5})
        price *= step
    return rows


class FakeProvider:
    def __init__(self, *, snapshot: dict[str, Any] = SNAPSHOT, dex_error: Exception | None = None,
                 candle_error: Exception | None = None, candles: list[dict[str, Any]] | None = None) -> None:
        self.snapshot, self.dex_error, self.candle_error = snapshot, dex_error, candle_error
        self.candles = _candles() if candles is None else candles
        self.candle_calls: list[str] = []

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        if self.dex_error is not None:
            raise self.dex_error
        return self.snapshot

    def fetch_predicted_fundings(self) -> dict[str, Any]:
        raise DataUnavailable("enrichment")

    def fetch_candles(self, symbol: str, *, interval: str, start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
        self.candle_calls.append(symbol)
        if self.candle_error is not None:
            raise self.candle_error
        return {"symbol": symbol, "interval": interval, "candles": self.candles,
                "as_of": "2026-08-22T00:00:00Z", "fetched_at": "2026-08-22T06:00:00Z"}


@pytest.fixture
def regime_on(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(crypto_regime, "REQUEST_GAP_SECONDS", 0.0)
    crypto_regime.clear_cache()
    yield
    crypto_regime.clear_cache()


def test_refresh_stores_one_price_part_per_curated_coin(regime_on):
    fake = FakeProvider()
    result = crypto_regime.refresh_coin_price_parts(provider=fake, now=NOW)
    # Four of the curated coins are in this fixture snapshot, plus one venue-level sample.
    assert result == {"updated": len(crypto_market.COIN_SPECS), "failed": 0, "sampled": 5}
    assert fake.candle_calls == [spec.symbol for spec in crypto_market.COIN_SPECS]
    parts = crypto_regime.coin_price_parts()
    assert set(parts) == {spec.symbol for spec in crypto_market.COIN_SPECS}
    assert {c["id"] for c in parts["BTC"]["components"]} == {"volatility", "range", "momentum"}  # funding is never stored
    assert parts["BTC"]["direction"]["band"] == "up" and parts["BTC"]["as_of"] == "2026-08-22T00:00:00Z"
    assert crypto_regime.refresh_coin_price_parts(provider=fake, now=NOW) == {"skipped": "fresh"}


def test_refresh_is_gated_and_survives_partial_venue_failure(db, monkeypatch):
    crypto_regime.clear_cache()
    monkeypatch.setattr(crypto_regime, "REQUEST_GAP_SECONDS", 0.0)
    assert crypto_regime.refresh_coin_price_parts(provider=FakeProvider()) == {"skipped": "disabled"}
    assert ingest.refresh_crypto_coin_heat() == {"skipped": "disabled"}
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", True)
    with pytest.raises(DataUnavailable):
        crypto_regime.refresh_coin_price_parts(provider=FakeProvider(candle_error=DataUnavailable("down")), now=NOW)
    limited = FakeProvider(candle_error=RateLimited("slow"))
    with pytest.raises(DataUnavailable):
        crypto_regime.refresh_coin_price_parts(provider=limited, now=NOW)
    assert limited.candle_calls == ["BTC"]  # a rate limit stops the pass instead of hammering


def test_badges_compose_the_cached_half_with_each_card_s_live_funding(regime_on):
    crypto_regime.refresh_coin_price_parts(provider=FakeProvider(), now=NOW)
    overview = crypto_market.build_crypto_overview(provider=FakeProvider())
    attached = crypto_regime.attach_coin_signals(overview)
    cards = {card["symbol"]: card for card in attached["coins"]}
    assert cards["BTC"]["signal"]["band"] in {"steady", "warm", "elevated", "overheated"}
    assert cards["BTC"]["signal"]["url"] == "/crypto/BTC"
    # DOGE funding sits 200pp from the baseline and BTC 1pp, on identical candles.
    assert cards["DOGE"]["signal"]["heat"] > cards["BTC"]["signal"]["heat"]
    assert cards["ETH"]["signal"]["heat"] <= cards["BTC"]["signal"]["heat"]  # ETH sits exactly at the baseline
    # No stored parts → no badge, and no exception.
    store.save_report(crypto_regime.PRICE_PARTS_CACHE_KEY, {"parts": {}})
    crypto_regime.clear_cache()
    bare = crypto_regime.attach_coin_signals(crypto_market.build_crypto_overview(provider=FakeProvider()))
    assert all("signal" not in card for card in bare["coins"])


def test_market_regime_counts_breadth_over_liquid_markets_only(regime_on, monkeypatch):
    monkeypatch.setattr(crypto_regime, "_sentiment_value", lambda: (76.0, {"status": "ok", "classification": "Greed"}))
    crypto_regime.refresh_coin_price_parts(provider=FakeProvider(), now=NOW)
    payload = crypto_regime.build_crypto_regime(provider=FakeProvider(), now=NOW)
    assert payload["sample"] == {"markets": 5, "liquid": 4, "min_volume_usd": 1_000_000.0,
                                 "with_funding": 4, "crowded": 2, "advancing": 3}
    by_id = {c["id"]: c for c in payload["components"]}
    assert by_id["funding_breadth"]["value"] == pytest.approx(50.0)      # 2 of 4 liquid markets
    assert by_id["advance_breadth"]["value"] == pytest.approx(75.0)      # 3 of 4
    assert by_id["sentiment"]["heat_score"] == 76.0 and "Greed" in by_id["sentiment"]["note"]["ko"]
    assert by_id["anchor"]["heat_score"] is not None
    weights = crypto_regime.MARKET_WEIGHTS
    assert payload["heat"]["score"] == pytest.approx(
        sum(by_id[k]["heat_score"] * weights[k] for k in weights), abs=0.15)
    assert payload["direction"]["band"] == "up"
    assert payload["heat"]["band"] in {"warm", "elevated", "overheated"}
    assert "매수·매도 신호" in payload["disclaimer"]["ko"] and payload["reading"]["ko"].startswith("시장")
    assert payload["anchor"]["symbol"] == "BTC" and payload["anchor"]["url"] == "/crypto/BTC"


def test_missing_sentiment_renormalises_and_venue_outage_is_refused(regime_on, monkeypatch):
    crypto_regime.refresh_coin_price_parts(provider=FakeProvider(), now=NOW)
    monkeypatch.setattr(crypto_regime, "_sentiment_value", lambda: (None, {"status": "collecting"}))
    payload = crypto_regime.build_crypto_regime(provider=FakeProvider(), now=NOW)
    by_id = {c["id"]: c for c in payload["components"]}
    assert by_id["sentiment"]["heat_score"] is None
    others = {k: v for k, v in crypto_regime.MARKET_WEIGHTS.items() if k != "sentiment"}
    assert payload["heat"]["score"] == pytest.approx(
        sum(by_id[k]["heat_score"] * w for k, w in others.items()) / sum(others.values()), abs=0.15)
    with pytest.raises(crypto_regime.RegimeUnavailable) as excinfo:
        crypto_regime.build_crypto_regime(provider=FakeProvider(dex_error=DataUnavailable("down")), now=NOW)
    assert excinfo.value.reason == "unavailable"


def test_regime_route_follows_the_gates(db, monkeypatch):
    crypto_regime.clear_cache()
    client = TestClient(app)
    assert client.get("/api/crypto/regime").json()["detail"]["code"] == "crypto_section_disabled"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    assert client.get("/api/crypto/regime").json()["detail"]["code"] == "hip3_public_display_pending_rights"
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", True)
    monkeypatch.setattr(crypto_regime, "_DEFAULT_PROVIDER", FakeProvider())
    monkeypatch.setattr(crypto_regime, "_sentiment_value", lambda: (60.0, {"status": "ok"}))
    response = client.get("/api/crypto/regime")
    assert response.status_code == 200 and response.headers["x-data-source"] == "Hyperliquid"
    assert response.json()["sample"]["liquid"] == 4
    assert 'id="crypto-regime"' in client.get("/crypto").text


def test_position_flow_names_the_standard_derivatives_reads():
    assert crypto_regime.position_flow(5.0, 8.0) == "new_longs"
    assert crypto_regime.position_flow(5.0, -8.0) == "short_covering"
    assert crypto_regime.position_flow(-5.0, 8.0) == "new_shorts"
    assert crypto_regime.position_flow(-5.0, -8.0) == "long_unwind"
    assert crypto_regime.position_flow(0.1, 9.0) == "flat"      # a price move this small is noise
    assert crypto_regime.position_flow(9.0, 0.1) == "flat"
    assert crypto_regime.position_flow(None, 5.0) is None


def test_samples_accumulate_and_yield_24h_changes(regime_on, monkeypatch):
    first = dt.datetime(2026, 8, 21, 6, 0, tzinfo=dt.UTC)
    crypto_regime.refresh_coin_price_parts(provider=FakeProvider(), now=first)

    # A day later the same coins are dearer with more open interest: new longs.
    hotter = _snapshot([
        _market("BTC", apr=BASELINE + 1.0, change=3.0, price=88000.0),
        _market("ETH", apr=BASELINE, change=2.0, price=2500.0),
        _market("DOGE", apr=BASELINE + 200.0, change=40.0, price=0.09),
        _market("SOL", apr=BASELINE - 30.0, change=-2.0, price=95.0),
    ])
    for market in hotter["markets"]:
        market["context"]["openInterest"] = "1200"  # 1000 → 1200
    second = first + dt.timedelta(days=1)
    monkeypatch.setattr(config, "CRYPTO_HEAT_MAX_AGE", 0)
    crypto_regime.refresh_coin_price_parts(provider=FakeProvider(snapshot=hotter), now=second, force=True)

    history = crypto_regime.history_for("BTC", now=second)
    assert len(history["recent"]) == 2 and len(history["daily"]) == 2
    assert [row["date"] for row in history["daily"]] == ["2026-08-21", "2026-08-22"]
    changes = history["changes"]
    assert changes["status"] == "ok"
    assert changes["price_24h_percent"] == pytest.approx((88000 / 77000 - 1) * 100, abs=1e-3)
    assert changes["oi_usd_24h_percent"] == pytest.approx((88000 * 1200) / (77000 * 1000) * 100 - 100, abs=1e-3)
    assert changes["flow"] == "new_longs" and changes["flow_label"]["ko"] == "신규 롱 유입"
    assert "heat_24h_points" in changes

    market_history = crypto_regime.history_for(crypto_regime.MARKET_KEY, now=second)
    assert market_history["recent"][-1]["liquid"] == 4 and "crowded_share" in market_history["recent"][-1]
    assert crypto_regime.history_for("NOTACOIN") is None


def test_a_single_sample_reports_collecting_rather_than_zero_change(regime_on):
    crypto_regime.refresh_coin_price_parts(provider=FakeProvider(), now=NOW)
    history = crypto_regime.history_for("BTC", now=NOW)
    assert history["changes"] == {"status": "collecting", "samples": 1}
    assert "flow" not in history["changes"] and "heat_24h_points" not in history["changes"]
    assert len(history["recent"]) == 1  # the sample itself is still served for the sparkline


def test_history_is_capped_and_one_point_per_day(regime_on, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_HEAT_MAX_AGE", 0)
    monkeypatch.setattr(crypto_regime, "RECENT_SAMPLES", 3)
    base = dt.datetime(2026, 8, 22, 0, 0, tzinfo=dt.UTC)
    for index in range(5):  # five samples inside the same UTC day
        crypto_regime.refresh_coin_price_parts(provider=FakeProvider(), now=base + dt.timedelta(hours=index), force=True)
    history = crypto_regime.history_for("BTC", now=base + dt.timedelta(hours=4))
    assert len(history["recent"]) == 3          # capped
    assert len(history["daily"]) == 1           # one point per UTC day, replaced in place
    assert history["daily"][0]["date"] == "2026-08-22"


def test_payloads_carry_the_series(regime_on, monkeypatch):
    monkeypatch.setattr(crypto_regime, "_sentiment_value", lambda: (60.0, {"status": "ok"}))
    crypto_regime.refresh_coin_price_parts(provider=FakeProvider(), now=NOW)
    regime = crypto_regime.build_crypto_regime(provider=FakeProvider(), now=NOW)
    assert regime["history"]["recent"][-1]["liquid"] == 4
    overview = crypto_regime.attach_coin_signals(crypto_market.build_crypto_overview(provider=FakeProvider()))
    btc = next(card for card in overview["coins"] if card["symbol"] == "BTC")
    assert "heat_24h_points" in btc["signal"]
