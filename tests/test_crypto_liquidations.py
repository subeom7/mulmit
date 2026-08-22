"""Coinalyze lane — a total is only the venues that answered, and it says which."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_liquidations, data_rights, store
from app.main import app
from app.providers import coinalyze
from app.providers.base import DataUnavailable

NOW = dt.datetime(2026, 8, 22, 11, 0, tzinfo=dt.UTC)
HOUR = 3600
BASE = int(NOW.timestamp()) - 24 * HOUR


def _market(symbol: str, exchange: str, base: str, quote: str, *, perp: bool = True) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "base_asset": base,
        "quote_asset": quote,
        "is_perpetual": perp,
        "oi_lq_vol_denominated_in": "BASE_ASSET",
    }


MARKETS = [
    _market("BTCUSDT_PERP.A", "A", "BTC", "USDT"),
    _market("BTCUSD_PERP.A", "A", "BTC", "USD"),          # same venue, coin-margined: not preferred
    _market("BTCUSDT.6", "6", "BTC", "USDT"),
    _market("BTCUSDT_PERP.3", "3", "BTC", "USDT"),
    _market("BTCUSDT_PERP.4", "4", "BTC", "USDT"),
    _market("BTCUSDT_PERP.0", "0", "BTC", "USDT"),
    _market("BTC.H", "H", "BTC", "USD"),
    _market("BTC_QUARTER.A", "A", "BTC", "USDT", perp=False),   # not perpetual
    _market("ETHUSDT_PERP.A", "A", "ETH", "USDT"),
    _market("ETHUSDT.6", "6", "ETH", "USDT"),
    _market("ETHUSDT_PERP.3", "3", "ETH", "USDT"),
    _market("ETHUSDT_PERP.4", "4", "ETH", "USDT"),
    _market("ETHUSDT_PERP.0", "0", "ETH", "USDT"),
    _market("ETH.H", "H", "ETH", "USD"),
]


def _history(long_per_hour: float, short_per_hour: float, *, hours: int = 24, shift: int = 0) -> list[dict[str, Any]]:
    return [
        {"t": BASE + (i + shift) * HOUR, "l": long_per_hour, "s": short_per_hour}
        for i in range(hours)
    ]


class FakeProvider:
    """Answers for some symbols and stays silent for others, like the real one."""

    def __init__(self, *, answers: dict[str, list[dict[str, Any]]] | None = None,
                 open_interest: dict[str, float] | None = None,
                 fail: Exception | None = None) -> None:
        self.answers = answers if answers is not None else {
            "BTCUSDT_PERP.A": _history(1000.0, 400.0),
            "BTCUSDT.6": _history(100.0, 50.0),
            "ETHUSDT_PERP.A": _history(200.0, 300.0),
        }
        self.open_interest = open_interest if open_interest is not None else {
            "BTCUSDT_PERP.A": 8_000_000_000.0,
            "BTC.H": 2_000_000_000.0,
            "ETHUSDT_PERP.A": 4_000_000_000.0,
        }
        self.fail = fail
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def fetch_markets(self) -> Any:
        return MARKETS

    def fetch_liquidations(self, symbols: list[str], *, interval: str, start: int, end: int) -> dict[str, Any]:
        if self.fail is not None:
            raise self.fail
        self.calls.append(("liquidations", tuple(symbols)))
        raw = [{"symbol": s, "history": self.answers[s]} for s in symbols if s in self.answers]
        return coinalyze.parse_liquidations(raw, symbols)

    def fetch_open_interest(self, symbols: list[str]) -> dict[str, Any]:
        self.calls.append(("open_interest", tuple(symbols)))
        raw = [
            {"symbol": s, "value": self.open_interest[s], "update": 1_787_400_000_000}
            for s in symbols if s in self.open_interest
        ]
        return coinalyze.parse_open_interest(raw, symbols)


@pytest.fixture
def lane_on(db, monkeypatch, hip3_public_display):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_API_KEY", "test-key")
    provider = FakeProvider()
    monkeypatch.setattr(crypto_liquidations, "_provider", lambda: provider)
    monkeypatch.setattr(crypto_liquidations, "_now", lambda: NOW)
    return provider


# --- symbol resolution ------------------------------------------------------


def test_resolve_symbols_takes_one_per_venue_and_prefers_the_stable_quote():
    picked = coinalyze.resolve_symbols(MARKETS, "BTC", coinalyze.LIQUIDATION_VENUES)
    assert [row["symbol"] for row in picked] == [
        "BTCUSDT_PERP.A", "BTCUSDT.6", "BTCUSDT_PERP.3", "BTCUSDT_PERP.4", "BTCUSDT_PERP.0",
    ]
    assert [row["venue_name"] for row in picked][:3] == ["Binance", "Bybit", "OKX"]
    # Quarterlies and other assets are not perpetual markets for this coin.
    assert all("QUARTER" not in row["symbol"] for row in picked)
    assert coinalyze.resolve_symbols(MARKETS, "SOL", coinalyze.LIQUIDATION_VENUES) == []
    # Open interest asks a different venue set, so it picks Hyperliquid instead.
    oi = coinalyze.resolve_symbols(MARKETS, "BTC", coinalyze.OPEN_INTEREST_VENUES)
    assert [row["symbol"] for row in oi] == ["BTCUSDT_PERP.A", "BTCUSDT.6", "BTCUSDT_PERP.3", "BTC.H"]


# --- the silence trap -------------------------------------------------------


def test_a_symbol_with_no_rows_is_reported_silent_not_zero():
    """The API answers 200 [] for both an unknown symbol and one with no data."""
    asked = ["BTCUSDT_PERP.A", "BTC.H", "NOPE.Z"]
    parsed = coinalyze.parse_liquidations([{"symbol": "BTCUSDT_PERP.A", "history": _history(5.0, 5.0)}], asked)
    assert parsed["answered"] == ["BTCUSDT_PERP.A"]
    assert parsed["silent"] == ["BTC.H", "NOPE.Z"]

    # An entry with an empty history counts as silent too — it adds nothing.
    empty = coinalyze.parse_liquidations([{"symbol": "BTC.H", "history": []}], ["BTC.H"])
    assert empty["answered"] == [] and empty["silent"] == ["BTC.H"]

    with pytest.raises(DataUnavailable):
        coinalyze.parse_liquidations({"not": "a list"}, asked)


def test_open_interest_reports_its_silent_symbols_the_same_way():
    parsed = coinalyze.parse_open_interest(
        [{"symbol": "BTCUSDT_PERP.A", "value": 1.5, "update": 1_787_400_000_000}],
        ["BTCUSDT_PERP.A", "BTC.H"],
    )
    assert parsed["answered"] == ["BTCUSDT_PERP.A"] and parsed["silent"] == ["BTC.H"]
    assert parsed["values"]["BTCUSDT_PERP.A"]["updated_at"].endswith("Z")


# --- the collected snapshot -------------------------------------------------


def test_refresh_sums_only_the_venues_that_answered_and_names_them(lane_on):
    assert crypto_liquidations.refresh_crypto_liquidations(force=True)["status"] == "ok"
    payload = crypto_liquidations.build_crypto_liquidations()

    btc = next(coin for coin in payload["coins"] if coin["symbol"] == "BTC")
    liq = btc["liquidations"]
    # Binance 1000/h and Bybit 100/h over 24 hours; OKX, Huobi and BitMEX said nothing.
    assert liq["long_usd"] == pytest.approx(24 * 1100.0)
    assert liq["short_usd"] == pytest.approx(24 * 450.0)
    assert liq["total_usd"] == pytest.approx(24 * 1550.0)
    assert liq["long_share_percent"] == pytest.approx(1100 / 1550 * 100.0)
    assert [row["venue"] for row in liq["venues"]] == ["Binance", "Bybit"]
    assert liq["venues_silent"] == ["OKX", "Huobi", "BitMEX"]
    assert btc["hub"] == "/crypto/BTC"

    # Open interest asks its own venue set and reports its own silence.
    assert btc["open_interest"]["total_usd"] == pytest.approx(10_000_000_000.0)
    assert [row["venue"] for row in btc["open_interest"]["venues"]] == ["Binance", "Hyperliquid"]
    assert btc["open_interest"]["venues_silent"] == ["Bybit", "OKX"]

    # The basis names the venues actually summed, so the card cannot imply more.
    assert "Binance" in payload["basis_ko"] and "전체 시장 합계가 아닙니다" in payload["basis_ko"]
    assert "not a market-wide total" in payload["basis_en"]


def test_the_hour_figure_only_counts_venues_sharing_the_newest_bucket(db, monkeypatch, hip3_public_display):
    """A venue lagging a bucket behind must not be read as having had zero."""
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_API_KEY", "test-key")
    provider = FakeProvider(answers={
        "BTCUSDT_PERP.A": _history(1000.0, 400.0),                 # newest bucket BASE+23h
        "BTCUSDT.6": _history(100.0, 50.0, hours=23),              # one bucket behind
    })
    monkeypatch.setattr(crypto_liquidations, "_provider", lambda: provider)
    monkeypatch.setattr(crypto_liquidations, "_now", lambda: NOW)

    crypto_liquidations.refresh_crypto_liquidations(force=True)
    latest = crypto_liquidations.build_crypto_liquidations()["coins"][0]["liquidations"]["latest_hour"]
    assert latest["long_usd"] == pytest.approx(1000.0)   # Bybit's stale bucket is excluded, not zeroed
    assert latest["short_usd"] == pytest.approx(400.0)
    assert latest["bucket_start"].endswith("Z")


def test_attribution_carries_the_dofollow_condition_and_the_permission(lane_on):
    crypto_liquidations.refresh_crypto_liquidations(force=True)
    payload = crypto_liquidations.build_crypto_liquidations()
    assert payload["attribution"]["dofollow"] is True
    assert payload["attribution"]["url"] == coinalyze.COINALYZE_SITE_URL
    assert "dofollow" in payload["source"]["permission_quote"]
    assert payload["source"]["permission_source"].startswith("contact@coinalyze.net")


def test_a_coin_that_fails_does_not_take_the_snapshot_down(db, monkeypatch, hip3_public_display):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_API_KEY", "test-key")
    provider = FakeProvider(fail=DataUnavailable("upstream"))
    monkeypatch.setattr(crypto_liquidations, "_provider", lambda: provider)
    monkeypatch.setattr(crypto_liquidations, "_now", lambda: NOW)
    with pytest.raises(DataUnavailable):
        crypto_liquidations.refresh_crypto_liquidations(force=True)


# --- gates and the route ----------------------------------------------------


def test_the_key_lives_in_ingest_only(db, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_ENABLED", True)
    monkeypatch.setattr(config, "COINALYZE_API_KEY", "")
    assert data_rights.coinalyze_serving_enabled() is True
    assert data_rights.coinalyze_ingest_enabled() is False
    assert crypto_liquidations.refresh_crypto_liquidations()["status"] == "disabled"


def test_route_gates_then_serves(db, monkeypatch, hip3_public_display):
    client = TestClient(app)
    assert client.get("/api/crypto/liquidations").json()["detail"]["code"] == "crypto_section_disabled"

    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    assert client.get("/api/crypto/liquidations").json()["detail"]["code"] == "crypto_liquidations_disabled"

    monkeypatch.setattr(config, "COINALYZE_ENABLED", True)
    assert client.get("/api/crypto/liquidations").json()["detail"]["code"] == "crypto_liquidations_collecting"

    store.save_report(crypto_liquidations.CACHE_KEY, {"generated_at": "2026-08-22T11:00:00Z", "coins": []})
    response = client.get("/api/crypto/liquidations")
    assert response.status_code == 200
    assert response.headers["x-data-source"] == "Coinalyze"
    assert response.headers["Cache-Control"] == "public, max-age=120"
