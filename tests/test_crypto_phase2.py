"""Crypto Phase 2 lanes — CoinMarketCap dominance (keyed, ingest blob) and Upbit kimchi premium.

Both lanes default off. The CoinMarketCap lane serves only a stored blob and
fetches only with a key held by ingest; the Upbit lane is `pending_rights` and
answers 503 until the operator opens the gate. Premiums are arithmetic on
displayed values and null out whenever an input is missing.
"""

from __future__ import annotations

import datetime as dt
import threading
import urllib.error
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_kimchi, crypto_structure, data_rights, ingest
from app.main import app
from app.providers.base import DataUnavailable, RateLimited
from app.providers.coinmarketcap import CoinMarketCapProvider, parse_global_metrics
from app.providers.http_cache import TtlCache
from app.providers.upbit import UpbitProvider, parse_tickers

FETCHED_AT = "2026-08-21T14:00:00Z"


@pytest.fixture
def phase2(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CMC_ENABLED", True)
    monkeypatch.setattr(config, "CMC_API_KEY", "test-key")
    monkeypatch.setattr(config, "UPBIT_ENABLED", True)
    crypto_structure.clear_cache()
    yield
    crypto_structure.clear_cache()


# --- shared cache -----------------------------------------------------------


def test_ttl_cache_single_flight_and_stale_fallback():
    clock = {"t": 100.0}
    cache = TtlCache(ttl=10, stale_ttl=60, clock=lambda: clock["t"])
    calls: list[int] = []

    def loader() -> dict[str, Any]:
        calls.append(1)
        return {"value": len(calls)}

    first = cache.fetch("k", loader, label="x")
    assert first["value"] == 1 and first["cached"] is False
    clock["t"] += 5
    second = cache.fetch("k", loader, label="x")
    assert second["value"] == 1 and second["cached"] is True and second["stale"] is False
    assert len(calls) == 1

    clock["t"] += 10  # past ttl → reload; the loader now fails → stale fallback with error

    def failing() -> dict[str, Any]:
        raise DataUnavailable("down")

    stale = cache.fetch("k", failing, label="x")
    assert stale["value"] == 1 and stale["stale"] is True and stale["error"] == "DataUnavailable"
    # Cooldown: the next call inside the failure window does not hit the loader.
    stale_again = cache.fetch("k", failing, label="x")
    assert stale_again["stale"] is True

    clock["t"] += 100  # beyond stale_ttl → failures surface
    with pytest.raises(DataUnavailable):
        cache.fetch("k", failing, label="x")


def test_ttl_cache_coalesces_concurrent_callers():
    cache = TtlCache(ttl=10, stale_ttl=60)
    gate = threading.Event()
    calls: list[int] = []

    def loader() -> dict[str, Any]:
        calls.append(1)
        gate.wait(timeout=2)
        return {"value": 1}

    results: list[dict[str, Any]] = []
    threads = [threading.Thread(target=lambda: results.append(cache.fetch("k", loader, label="x"))) for _ in range(4)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join(timeout=5)
    assert len(calls) == 1 and len(results) == 4


# --- Upbit provider -----------------------------------------------------------


UPBIT_RAW = [
    {"market": "KRW-BTC", "trade_price": 105640000.0, "prev_closing_price": 100591000.0, "signed_change_rate": 0.0501933573, "acc_trade_price_24h": 422329423496.97, "timestamp": 1787320951819},
    {"market": "KRW-ETH", "trade_price": 3269000.0, "signed_change_rate": 0.0202871411, "acc_trade_price_24h": 168583151229.6, "timestamp": 1787320951792},
    {"market": "KRW-USDT", "trade_price": 1374.0, "signed_change_rate": -0.0021786492, "acc_trade_price_24h": 1.0e11, "timestamp": 1787320951801},
    {"market": "KRW-SOL", "trade_price": "oops"},
    "junk",
]


def test_parse_tickers_keeps_usable_rows_only():
    parsed = parse_tickers(UPBIT_RAW, fetched_at=FETCHED_AT)
    assert set(parsed["tickers"]) == {"KRW-BTC", "KRW-ETH", "KRW-USDT"}
    btc = parsed["tickers"]["KRW-BTC"]
    assert btc["trade_price"] == 105640000.0
    assert btc["change_24h_percent"] == pytest.approx(5.0193, abs=1e-3)
    assert btc["traded_at"] == "2026-08-21T14:02:31.819000Z"
    assert parsed["as_of"].startswith("2026-08-21T14:02:31")
    with pytest.raises(DataUnavailable):
        parse_tickers({"not": "a list"}, fetched_at=FETCHED_AT)
    with pytest.raises(DataUnavailable):
        parse_tickers([{"market": "KRW-BTC", "trade_price": "nan"}], fetched_at=FETCHED_AT)


def test_upbit_provider_maps_errors_and_caches():
    calls: list[str] = []

    def transport(url: str, timeout: float) -> Any:
        calls.append(url)
        return UPBIT_RAW

    provider = UpbitProvider(transport=transport, retries=0, ttl=30, stale_ttl=60)
    snap = provider.fetch_tickers(["KRW-BTC", "KRW-USDT"])
    assert "markets=KRW-BTC%2CKRW-USDT" in calls[0] or "markets=KRW-BTC,KRW-USDT" in calls[0]
    assert provider.fetch_tickers(["KRW-USDT", "KRW-BTC"])["cached"] is True
    assert len(calls) == 1
    assert snap["tickers"]["KRW-USDT"]["trade_price"] == 1374.0

    def too_many(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)

    with pytest.raises(RateLimited):
        UpbitProvider(transport=too_many, retries=0).fetch_tickers(["KRW-BTC"])

    def forbidden(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)

    with pytest.raises(DataUnavailable):
        UpbitProvider(transport=forbidden, retries=1, sleep=lambda _s: None).fetch_tickers(["KRW-BTC"])


# --- CoinMarketCap provider ---------------------------------------------------


CMC_RAW = {
    "status": {"timestamp": "2026-08-21T14:00:00.000Z", "error_code": 0, "error_message": None, "credit_count": 1},
    "data": {
        "active_cryptocurrencies": 9800,
        "active_exchanges": 760,
        "btc_dominance": 57.19,
        "eth_dominance": 12.4,
        "btc_dominance_yesterday": 56.9,
        "btc_dominance_24h_percentage_change": 0.29,
        "eth_dominance_24h_percentage_change": -0.1,
        "stablecoin_24h_percentage_change": 0.3,
        "last_updated": "2026-08-21T13:59:00.000Z",
        "quote": {"USD": {
            "total_market_cap": 2689999231765.0,
            "total_volume_24h": 441695784840.0,
            "total_market_cap_yesterday_percentage_change": 5.72,
            "total_volume_24h_yesterday_percentage_change": 10.51,
            "altcoin_market_cap": 1150000000000.0,
            "stablecoin_market_cap": 290000000000.0,
            "defi_market_cap": 120000000000.0,
            "last_updated": "2026-08-21T13:59:00.000Z",
        }},
    },
}


def test_parse_global_metrics_flattens_and_validates():
    parsed = parse_global_metrics(CMC_RAW, fetched_at=FETCHED_AT)
    assert parsed["btc_dominance"] == 57.19 and parsed["eth_dominance"] == 12.4
    assert parsed["total_market_cap_usd"] == pytest.approx(2689999231765.0)
    assert parsed["total_market_cap_24h_change_percent"] == pytest.approx(5.72)
    assert parsed["stablecoin_market_cap_usd"] == pytest.approx(2.9e11)
    assert parsed["as_of"] == "2026-08-21T13:59:00.000Z"
    assert parsed["credit_count"] == 1
    with pytest.raises(DataUnavailable):
        parse_global_metrics({"status": {"error_code": 1002, "error_message": "API key missing."}}, fetched_at=FETCHED_AT)
    with pytest.raises(DataUnavailable):
        parse_global_metrics({"status": {"error_code": 0}, "data": {"eth_dominance": 12}}, fetched_at=FETCHED_AT)


def test_cmc_provider_sends_key_header_and_maps_auth_errors():
    seen: list[dict[str, str]] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        seen.append(headers)
        assert url.startswith("https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest")
        return CMC_RAW

    metrics = CoinMarketCapProvider("secret", transport=transport).fetch_global_metrics()
    assert seen[0]["X-CMC_PRO_API_KEY"] == "secret"
    assert metrics["btc_dominance"] == 57.19

    def unauthorized(url: str, headers: dict[str, str], timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 401, "Unauthorized", hdrs=None, fp=None)

    with pytest.raises(DataUnavailable):
        CoinMarketCapProvider("bad", transport=unauthorized, retries=2, sleep=lambda _s: None).fetch_global_metrics()
    with pytest.raises(ValueError):
        CoinMarketCapProvider("   ")


# --- structure lane -----------------------------------------------------------


class FakeCmc:
    def __init__(self, raw: dict[str, Any] = CMC_RAW) -> None:
        self.raw = raw
        self.calls = 0

    def fetch_global_metrics(self) -> dict[str, Any]:
        self.calls += 1
        return parse_global_metrics(self.raw, fetched_at=FETCHED_AT)


def test_structure_refresh_stores_blob_and_serving_derives_others(phase2):
    fake = FakeCmc()
    assert crypto_structure.refresh_crypto_structure(provider=fake)["updated"] == 1
    payload = crypto_structure.build_crypto_structure(now=dt.datetime(2026, 8, 21, 14, 30, tzinfo=dt.UTC))
    assert payload["dominance"]["btc_percent"] == 57.19
    assert payload["dominance"]["others_percent"] == pytest.approx(100 - 57.19 - 12.4)
    assert payload["market_cap"]["total_usd"] == pytest.approx(2689999231765.0)
    assert payload["attribution"]["text"] == "Data provided by CoinMarketCap"
    assert payload["attribution"]["placement"] == "adjacent_to_value"
    assert payload["freshness"]["status"] == "fresh"
    assert payload["rights"]["status"] == "provider_terms_apply"
    # Fresh blob → no second fetch inside CMC_MAX_AGE.
    assert crypto_structure.refresh_crypto_structure(provider=fake) == {"skipped": "fresh"}
    assert fake.calls == 1
    stale = crypto_structure.build_crypto_structure(now=dt.datetime(2026, 8, 21, 18, 0, tzinfo=dt.UTC))
    assert stale["freshness"]["status"] == "stale"


def test_structure_lane_off_or_keyless_makes_no_network_calls(db, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CMC_ENABLED", True)
    monkeypatch.setattr(config, "CMC_API_KEY", "")
    crypto_structure.clear_cache()

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("provider must not be built without a key")

    monkeypatch.setattr(crypto_structure, "CoinMarketCapProvider", explode)
    assert crypto_structure.refresh_crypto_structure() == {"skipped": "not_configured"}
    assert ingest.refresh_crypto_structure() == {"skipped": "not_configured"}
    with pytest.raises(crypto_structure.CryptoStructureUnavailable) as excinfo:
        crypto_structure.build_crypto_structure()
    assert excinfo.value.reason == "collecting"  # switched on, nothing stored yet

    monkeypatch.setattr(config, "CMC_ENABLED", False)
    assert crypto_structure.refresh_crypto_structure() == {"skipped": "disabled"}
    with pytest.raises(crypto_structure.CryptoStructureUnavailable) as excinfo:
        crypto_structure.build_crypto_structure()
    assert excinfo.value.reason == "disabled"


def test_structure_route_states(db, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/crypto/structure").json()["detail"]["code"] == "crypto_section_disabled"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    crypto_structure.clear_cache()
    assert client.get("/api/crypto/structure").json()["detail"]["code"] == "crypto_structure_disabled"
    monkeypatch.setattr(config, "CMC_ENABLED", True)
    crypto_structure.clear_cache()
    response = client.get("/api/crypto/structure")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "crypto_structure_collecting"
    monkeypatch.setattr(config, "CMC_API_KEY", "k")
    crypto_structure.refresh_crypto_structure(provider=FakeCmc())
    response = client.get("/api/crypto/structure")
    assert response.status_code == 200
    assert response.json()["dominance"]["btc_percent"] == 57.19
    assert response.headers["x-data-source"] == "CoinMarketCap"
    crypto_structure.clear_cache()


# --- kimchi lane --------------------------------------------------------------


class FakeUpbit:
    def __init__(self, raw: Any = UPBIT_RAW, *, error: Exception | None = None, stale: bool = False) -> None:
        self.raw = raw
        self.error = error
        self.stale = stale
        self.calls: list[list[str]] = []

    def fetch_tickers(self, markets: list[str]) -> dict[str, Any]:
        self.calls.append(list(markets))
        if self.error is not None:
            raise self.error
        parsed = parse_tickers(self.raw, fetched_at=FETCHED_AT)
        parsed.update({"cached": False, "stale": self.stale, "age_seconds": 0.0})
        return parsed


class FakeHl:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = prices

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        assert dex == "main"
        return {
            "dex": dex, "fetched_at": FETCHED_AT, "as_of": FETCHED_AT, "cached": False, "stale": False,
            "markets": [
                {"symbol": symbol, "dex": dex, "metadata": {"name": symbol}, "context": {"oraclePx": str(price), "markPx": str(price)}}
                for symbol, price in self.prices.items()
            ],
        }


def _fx_ok() -> dict[str, Any]:
    return {"status": "ok", "rate": 1385.2, "date": "2026-08-21", "series_key": "fx_usdkrw", "publisher": "Bank of Korea", "basis_ko": "x", "basis_en": "y"}


def _fx_missing() -> dict[str, Any]:
    return {"status": "unavailable", "rate": None, "date": None, "series_key": "fx_usdkrw", "publisher": "Bank of Korea", "basis_ko": "x", "basis_en": "y"}


def test_kimchi_premiums_are_arithmetic_on_displayed_values(phase2):
    hl = FakeHl({"BTC": 76600.0, "ETH": 2380.0})
    payload = crypto_kimchi.build_crypto_kimchi(provider=FakeUpbit(), hl_provider=hl, fx_loader=_fx_ok)
    assert payload["status"] == "ok"
    usdt = payload["usdt"]
    assert usdt["krw"] == 1374.0
    assert usdt["tether_premium_percent"] == pytest.approx((1374.0 / 1385.2 - 1) * 100, abs=1e-4)
    assert usdt["official_rate_date"] == "2026-08-21"
    coins = {coin["symbol"]: coin for coin in payload["coins"]}
    assert set(coins) == {"BTC", "ETH"}  # SOL/XRP/DOGE absent from the fixture → not invented
    btc = coins["BTC"]
    assert btc["usd_via_usdt"] == pytest.approx(105640000.0 / 1374.0, rel=1e-9)
    assert btc["premium_usdt_basis_percent"] == pytest.approx(((105640000.0 / 1374.0) / 76600.0 - 1) * 100, abs=1e-4)
    assert btc["premium_official_basis_percent"] == pytest.approx(((105640000.0 / 1385.2) / 76600.0 - 1) * 100, abs=1e-4)
    assert btc["change_24h_percent"] == pytest.approx(5.0193, abs=1e-3)
    assert payload["rights"]["status"] == "pending_rights"
    assert payload["fx"]["date"] == "2026-08-21"
    assert payload["source"]["upbit"]["attribution"]["ko"] == "시세: 업비트(두나무)"


def test_kimchi_nulls_fields_whose_inputs_are_missing(phase2):
    # No official FX → tether premium and official-basis premium are null, USDT basis survives.
    payload = crypto_kimchi.build_crypto_kimchi(provider=FakeUpbit(), hl_provider=FakeHl({"BTC": 76600.0}), fx_loader=_fx_missing)
    assert payload["usdt"]["tether_premium_percent"] is None
    btc = next(coin for coin in payload["coins"] if coin["symbol"] == "BTC")
    assert btc["premium_official_basis_percent"] is None
    assert btc["premium_usdt_basis_percent"] is not None
    eth = next(coin for coin in payload["coins"] if coin["symbol"] == "ETH")
    assert eth["oracle_usd"] is None and eth["premium_usdt_basis_percent"] is None and eth["status"] == "no_reference"

    # Hyperliquid outage → KRW prices still shown, premiums null.
    class DownHl:
        def fetch_dex(self, dex: str) -> dict[str, Any]:
            raise DataUnavailable("down")

    payload = crypto_kimchi.build_crypto_kimchi(provider=FakeUpbit(), hl_provider=DownHl(), fx_loader=_fx_ok)
    assert payload["status"] == "ok"
    assert all(coin["premium_usdt_basis_percent"] is None for coin in payload["coins"])

    # Upbit outage → empty, labelled, nothing invented.
    payload = crypto_kimchi.build_crypto_kimchi(provider=FakeUpbit(error=RateLimited("slow")), hl_provider=FakeHl({}), fx_loader=_fx_ok)
    assert payload["status"] == "rate_limited" and payload["coins"] == [] and payload["usdt"] is None


def test_kimchi_route_is_withheld_until_the_gate_opens(db, hip3_public_display, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/crypto/kimchi").json()["detail"]["code"] == "crypto_section_disabled"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    response = client.get("/api/crypto/kimchi")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "upbit_quotation_pending_rights"
    assert response.json()["detail"]["status"] == "pending_rights"
    monkeypatch.setattr(config, "UPBIT_ENABLED", True)
    monkeypatch.setattr(crypto_kimchi, "_DEFAULT_UPBIT", FakeUpbit())
    monkeypatch.setattr(crypto_kimchi, "_HL_PROVIDER", FakeHl({"BTC": 76600.0}))
    response = client.get("/api/crypto/kimchi")
    assert response.status_code == 200
    body = response.json()
    assert body["usdt"]["krw"] == 1374.0
    assert response.headers["x-data-source"].startswith("Upbit")


def test_lane_report_names_phase2_gates(db, monkeypatch):
    report = data_rights.lane_report()
    assert report["coinmarketcap"]["status"] == "disabled"
    assert report["upbit"]["status"] == "pending_rights"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CMC_ENABLED", True)
    monkeypatch.setattr(config, "CMC_API_KEY", "")
    monkeypatch.setattr(config, "UPBIT_ENABLED", True)
    report = data_rights.lane_report()
    assert report["coinmarketcap"]["status"] == "enabled"
    assert report["coinmarketcap"]["fetch_key"] == "absent_in_this_process"
    assert report["upbit"]["status"] == "enabled"


def test_crypto_page_has_phase2_sections(db):
    page = TestClient(app).get("/crypto").text
    assert 'id="crypto-kimchi"' in page and 'id="crypto-structure"' in page
