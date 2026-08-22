"""Stablecoin supply lane (CoinMarketCap quotes/latest, same key): parsing, history accumulation, serving block."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_structure, ingest, store
from app.main import app
from app.providers.base import DataUnavailable
from app.providers.coinmarketcap import (
    CMC_QUOTES_URL,
    CoinMarketCapProvider,
    parse_global_metrics,
    parse_quotes,
)

FETCHED_AT = "2026-08-22T03:00:00Z"

GLOBAL_RAW = {
    "status": {"error_code": 0, "credit_count": 1},
    "data": {
        "btc_dominance": 57.19, "eth_dominance": 12.4, "stablecoin_24h_percentage_change": 0.3,
        "stablecoin_volume_24h": 164790931661.78, "last_updated": "2026-08-22T02:59:00.000Z",
        "quote": {"USD": {"total_market_cap": 2689999231765.0, "total_volume_24h": 441695784840.0,
                          "stablecoin_market_cap": 290000000000.0, "altcoin_market_cap": 1.15e12}},
    },
}


def _coin(cid: int, symbol: str, name: str, slug: str, *, supply: float, price: float, mcap: float, dom: float) -> dict[str, Any]:
    return {"id": cid, "symbol": symbol, "name": name, "slug": slug, "circulating_supply": supply, "total_supply": supply + 1,
            "quote": {"USD": {"price": price, "market_cap": mcap, "volume_24h": 1.0e9, "market_cap_dominance": dom, "last_updated": "2026-08-22T02:17:02.000Z"}}}


USDT = _coin(825, "USDT", "Tether USDt", "tether", supply=183230580044.15735, price=1.0000581476096806, mcap=183241234464.40732, dom=6.9309)
USDC = _coin(3408, "USDC", "USDC", "usd-coin", supply=73617743124.17963, price=0.9998985764005294, mcap=73610276547.68707, dom=2.7842)
QUOTES_RAW = {"status": {"error_code": 0, "credit_count": 1}, "data": {"825": USDT, "3408": USDC}}


class FakeGlobal:
    def fetch_global_metrics(self) -> dict[str, Any]:
        return parse_global_metrics(GLOBAL_RAW, fetched_at=FETCHED_AT)


class FakeQuotes:
    def __init__(self) -> None:
        self.calls = 0

    def fetch_quotes(self, ids) -> dict[str, Any]:
        self.calls += 1
        assert list(ids) == [825, 3408]
        return parse_quotes(QUOTES_RAW, fetched_at=FETCHED_AT)


@pytest.fixture
def cmc_on(db, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CMC_ENABLED", True)
    monkeypatch.setattr(config, "CMC_API_KEY", "test-key")
    crypto_structure.clear_cache()
    yield
    crypto_structure.clear_cache()


def test_parse_quotes_reads_id_objects_and_symbol_lists_and_rejects_errors():
    by_id = parse_quotes(QUOTES_RAW, fetched_at=FETCHED_AT)
    assert [c["symbol"] for c in by_id["coins"]] == ["USDT", "USDC"] and by_id["credit_count"] == 1
    assert by_id["coins"][0]["circulating_supply"] == pytest.approx(183230580044.157, abs=0.01)
    by_symbol = parse_quotes({"status": {"error_code": 0}, "data": {"USDT": [USDT]}}, fetched_at=FETCHED_AT)
    assert by_symbol["coins"][0]["id"] == 825
    with pytest.raises(DataUnavailable):
        parse_quotes({"status": {"error_code": 1002, "error_message": "API key missing."}}, fetched_at=FETCHED_AT)
    with pytest.raises(DataUnavailable):
        parse_quotes({"status": {"error_code": 0}, "data": {"825": {"id": 825, "symbol": "USDT", "quote": {}}}}, fetched_at=FETCHED_AT)


def test_provider_fetch_quotes_requests_ids_with_key_header():
    seen: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        seen.append((url, headers))
        return QUOTES_RAW

    parsed = CoinMarketCapProvider("secret", transport=transport).fetch_quotes([825, 3408])
    assert seen[0][0] == f"{CMC_QUOTES_URL}?id=825,3408&convert=USD"
    assert seen[0][1]["X-CMC_PRO_API_KEY"] == "secret"
    assert [c["symbol"] for c in parsed["coins"]] == ["USDT", "USDC"]


def test_stablecoin_refresh_keeps_one_point_per_utc_day_and_serves_block(cmc_on):
    assert crypto_structure.refresh_crypto_structure(provider=FakeGlobal())["updated"] == 1
    fake = FakeQuotes()
    day1 = dt.datetime(2026, 8, 22, 3, 0, tzinfo=dt.UTC)
    assert crypto_structure.refresh_crypto_stablecoins(provider=fake, now=day1)["history_points"] == 1
    assert crypto_structure.refresh_crypto_stablecoins(provider=fake, now=day1) == {"skipped": "fresh"}
    assert crypto_structure.refresh_crypto_stablecoins(provider=fake, now=day1 + dt.timedelta(hours=5), force=True)["history_points"] == 1
    assert crypto_structure.refresh_crypto_stablecoins(provider=fake, now=day1 + dt.timedelta(days=1), force=True)["history_points"] == 2
    assert fake.calls == 3

    payload = crypto_structure.build_crypto_structure(now=day1 + dt.timedelta(minutes=5))  # the fake's fetched_at is fixed at day1 03:00Z
    stable = payload["stablecoins"]
    assert stable["status"] == "ok" and stable["stale"] is False
    assert stable["history"]["status"] == "collecting" and stable["history"]["points"] == 2 and stable["history"]["since"] == "2026-08-22"
    usdt = next(c for c in stable["coins"] if c["symbol"] == "USDT")
    assert usdt["circulating_supply"] == pytest.approx(183230580044.16, abs=0.01)
    assert usdt["peg_deviation_bp"] == pytest.approx(0.58, abs=0.01)
    assert usdt["change_7d_percent"] is None and usdt["change_30d_percent"] is None
    assert usdt["share_of_stablecoins_percent"] == pytest.approx(183241234464.40732 / 290e9 * 100, abs=1e-4)
    assert usdt["source_url"] == "https://coinmarketcap.com/currencies/tether/"
    agg = stable["aggregate"]
    assert agg["share_of_total_percent"] == pytest.approx(290e9 / 2689999231765.0 * 100, abs=1e-4)
    assert agg["volume_24h_usd"] == pytest.approx(164790931661.78, abs=0.01)
    assert agg["change_24h_percent"] == pytest.approx(0.3)
    assert payload["source"]["quotes_api_url"] == CMC_QUOTES_URL
    assert "스테이블코인 비중" in payload["methodology"]["ko"]


def test_stablecoin_changes_use_stored_day_within_grace_window(cmc_on):
    crypto_structure.refresh_crypto_structure(provider=FakeGlobal())
    today = dt.date(2026, 9, 30)
    coins = parse_quotes(QUOTES_RAW, fetched_at="2026-09-30T03:00:00Z")["coins"]
    history = [
        {"date": (today - dt.timedelta(days=d)).isoformat(), "as_of": None, "supply": {"USDT": supply, "USDC": 70e9}, "market_cap_usd": {}}
        for d, supply in ((40, 150e9), (31, 170e9), (9, 179e9), (7, 180e9), (1, 182e9), (0, 183e9))
    ]
    store.save_report(crypto_structure.STABLE_CACHE_KEY, {"generated_at": "x", "fetched_at": "2026-09-30T03:00:00Z", "coins": coins, "history": history})
    crypto_structure.clear_cache()
    stable = crypto_structure.build_crypto_structure(now=dt.datetime(2026, 9, 30, 3, 30, tzinfo=dt.UTC))["stablecoins"]
    usdt = next(c for c in stable["coins"] if c["symbol"] == "USDT")
    assert usdt["change_7d_percent"] == pytest.approx((183230580044.15735 / 180e9 - 1) * 100, abs=1e-4)
    assert usdt["change_30d_percent"] == pytest.approx((183230580044.15735 / 170e9 - 1) * 100, abs=1e-4)  # day −31 sits inside the 2-day grace
    assert stable["history"]["status"] == "ok" and stable["history"]["since"] == "2026-08-21"


def test_stablecoin_lane_keyless_makes_no_calls_and_structure_still_serves(db, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CMC_ENABLED", True)
    monkeypatch.setattr(config, "CMC_API_KEY", "k")
    crypto_structure.clear_cache()
    crypto_structure.refresh_crypto_structure(provider=FakeGlobal())
    monkeypatch.setattr(config, "CMC_API_KEY", "")

    def explode(*args, **kwargs):
        raise AssertionError("provider must not be constructed without a key")

    monkeypatch.setattr(crypto_structure, "CoinMarketCapProvider", explode)
    assert crypto_structure.refresh_crypto_stablecoins() == {"skipped": "not_configured"}
    assert ingest.refresh_crypto_stablecoins() == {"skipped": "not_configured"}
    client = TestClient(app)
    body = client.get("/api/crypto/structure").json()
    assert body["dominance"]["btc_percent"] == pytest.approx(57.19)
    assert body["stablecoins"]["status"] == "collecting" and body["stablecoins"]["coins"] == []
    assert body["stablecoins"]["aggregate"]["share_of_total_percent"] is not None
    monkeypatch.setattr(config, "CMC_ENABLED", False)
    assert crypto_structure.refresh_crypto_stablecoins() == {"skipped": "disabled"}
