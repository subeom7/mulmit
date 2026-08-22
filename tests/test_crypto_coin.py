"""Per-coin detail — symbol resolution, candle window, payload shape, gates and the server-rendered page."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_coin
from app.main import app
from app.providers.base import DataUnavailable, RateLimited

NOW = dt.datetime(2026, 8, 22, 6, 0, tzinfo=dt.UTC)


def _market(symbol: str, *, mark: str = "77000", prev: str = "70000", delisted: bool = False) -> dict[str, Any]:
    return {
        "symbol": symbol, "dex": "main",
        "metadata": {"name": symbol, **({"isDelisted": True} if delisted else {})},
        "context": {"markPx": mark, "oraclePx": mark, "midPx": mark, "prevDayPx": prev,
                    "dayNtlVlm": "7000000000", "openInterest": "33000", "funding": "0.0000125", "premium": "0.0004"},
    }


SNAPSHOT = {
    "dex": "main", "fetched_at": "2026-08-22T06:00:00Z", "as_of": "2026-08-22T06:00:00Z",
    "cached": False, "stale": False, "age_seconds": 0.0,
    "markets": [_market("BTC"), _market("kPEPE", mark="0.00423", prev="0.004"), _market("DEAD", delisted=True)],
}


def _candle(ms: int, o: float, h: float, low: float, c: float, v: float = 10.0) -> dict[str, Any]:
    return {"t": ms, "T": ms + 3_600_000 - 1, "s": "BTC", "i": "1h", "o": str(o), "h": str(h), "l": str(low), "c": str(c), "v": str(v), "n": 900}


BASE_MS = 1_787_000_000_000
RAW_CANDLES = [
    _candle(BASE_MS, 70000, 71000, 69500, 70500),
    _candle(BASE_MS + 3_600_000, 70500, 78000, 70400, 77000, 25.5),
    _candle(BASE_MS + 7_200_000, 77000, 77500, 68000, 76000, 12.0),
]


class FakeProvider:
    def __init__(self, *, snapshot: dict[str, Any] = SNAPSHOT, candles: list[dict[str, Any]] | None = None,
                 dex_error: Exception | None = None, candle_error: Exception | None = None) -> None:
        self.snapshot, self.dex_error, self.candle_error = snapshot, dex_error, candle_error
        self.candles = RAW_CANDLES if candles is None else candles
        self.candle_calls: list[tuple[str, str, int]] = []
        self.dex_calls = 0

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        self.dex_calls += 1
        if self.dex_error is not None:
            raise self.dex_error
        return self.snapshot

    def fetch_predicted_fundings(self) -> dict[str, Any]:
        raise DataUnavailable("predicted funding is an enrichment")

    def fetch_candles(self, symbol: str, *, interval: str, start: dt.datetime, end: dt.datetime) -> dict[str, Any]:
        self.candle_calls.append((symbol, interval, round((end - start).total_seconds())))
        if self.candle_error is not None:
            raise self.candle_error
        return {"symbol": symbol, "interval": interval, "candles": self.candles, "as_of": "2026-08-22T05:59:59Z", "fetched_at": "2026-08-22T06:00:00Z"}


@pytest.fixture
def crypto_on(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)


def test_parse_candles_sorts_drops_malformed_and_keeps_volume():
    rows = crypto_coin.parse_candles([
        _candle(BASE_MS + 7_200_000, 1, 2, 0.5, 1.5),
        {"t": "nope", "o": "1", "h": "2", "l": "1", "c": "1"},
        {"t": BASE_MS, "o": "1", "h": "2", "l": "1"},  # no close
        _candle(BASE_MS, 1, 2, 0.5, 1.9, 3.0),
    ])
    assert [row["t"] for row in rows] == [BASE_MS, BASE_MS + 7_200_000]
    assert rows[0]["c"] == 1.9 and rows[0]["v"] == 3.0 and rows[0]["trades"] == 900
    assert crypto_coin.parse_candles(None) == []
    many = crypto_coin.parse_candles([_candle(BASE_MS + i * 60_000, 1, 1, 1, 1) for i in range(crypto_coin.MAX_CANDLES + 40)])
    assert len(many) == crypto_coin.MAX_CANDLES and many[-1]["t"] == BASE_MS + (crypto_coin.MAX_CANDLES + 39) * 60_000


def test_resolve_symbol_is_case_insensitive_and_refuses_delisted_or_unknown():
    resolved, market = crypto_coin.resolve_symbol("kpepe", SNAPSHOT)
    assert resolved == "kPEPE" and market["symbol"] == "kPEPE"
    assert crypto_coin.resolve_symbol("btc", SNAPSHOT)[0] == "BTC"
    for bad in ("DEAD", "NOTLISTED", "", "  "):
        with pytest.raises(crypto_coin.CoinNotFound):
            crypto_coin.resolve_symbol(bad, SNAPSHOT)


def test_coin_spec_labels_curated_and_falls_back_to_symbol():
    assert crypto_coin.coin_spec("btc").label_ko == "비트코인"
    plain = crypto_coin.coin_spec("kPEPE")
    assert plain.label_ko == "kPEPE" and plain.label_en == "kPEPE"


def test_build_coin_reuses_the_card_builder_and_summarises_the_window(crypto_on):
    fake = FakeProvider()
    payload = crypto_coin.build_crypto_coin("btc", interval="1h", provider=fake, now=NOW)
    assert payload["symbol"] == "BTC" and payload["curated"] is True and payload["label"]["ko"] == "비트코인"
    market = payload["market"]
    assert market["price"]["value"] == 77000.0 and market["change_24h"]["percent"] == pytest.approx(10.0)
    assert market["funding"]["apr_percent"] == pytest.approx(0.0000125 * 24 * 365 * 100, rel=1e-6)
    assert market["open_interest"]["usd"] == pytest.approx(33000 * 77000)
    assert market["predicted_funding"] == []  # the enrichment failed; the rest still serves
    chart = payload["chart"]
    assert chart["interval"] == "1h" and chart["omitted"] is False and chart["error"] is None
    assert [row["t"] for row in chart["candles"]] == [BASE_MS, BASE_MS + 3_600_000, BASE_MS + 7_200_000]
    # The chart window plus the daily window the regime signal always uses.
    assert fake.candle_calls == [("BTC", "1h", 14 * 24 * 3600), ("BTC", "1d", 400 * 24 * 3600)]
    # This fixture only has three candles, so the regime read refuses rather than guessing.
    assert payload["signal"]["status"] == "insufficient_data"
    stats = chart["stats"]
    def at(offset_ms: int) -> str:
        return dt.datetime.fromtimestamp((BASE_MS + offset_ms) / 1000, dt.UTC).isoformat().replace("+00:00", "Z")

    assert stats == {
        "candles": 3, "open": 70000.0, "close": 76000.0, "high": 78000.0, "low": 68000.0,
        "change_percent": pytest.approx(8.5714, abs=1e-3),
        "high_at": at(3_600_000), "low_at": at(7_200_000),
        "volume_base": pytest.approx(47.5), "from": at(0), "to": at(7_200_000 + 3_600_000 - 1),
    }
    assert [option["id"] for option in chart["intervals"]] == ["15m", "1h", "4h", "1d"]
    assert payload["links"]["venue"] == "https://app.hyperliquid.xyz/trade/BTC"
    assert payload["rights"]["status"] and payload["methodology"]["ko"].startswith("가격·캔들은")


def test_candles_can_be_omitted_and_outages_are_labelled(crypto_on):
    light = FakeProvider()
    payload = crypto_coin.build_crypto_coin("BTC", interval="4h", include_candles=False, provider=light, now=NOW)
    # No chart window, but the daily window for the signal is still read (cached upstream).
    assert light.candle_calls == [("BTC", "1d", 400 * 24 * 3600)]
    assert payload["chart"]["omitted"] is True and payload["chart"]["candles"] == []
    assert payload["chart"]["stats"]["candles"] == 0 and payload["market"]["price"]["value"] == 77000.0

    degraded = crypto_coin.build_crypto_coin("BTC", provider=FakeProvider(candle_error=RateLimited("slow")), now=NOW)
    assert degraded["chart"]["error"] == "rate_limited" and degraded["chart"]["candles"] == []
    assert degraded["signal"]["status"] == "unavailable"  # no candles, so no invented regime
    assert degraded["market"]["price"]["value"] == 77000.0  # the price still serves without candles

    with pytest.raises(crypto_coin.CoinUnavailable) as excinfo:
        crypto_coin.build_crypto_coin("BTC", provider=FakeProvider(dex_error=DataUnavailable("down")), now=NOW)
    assert excinfo.value.reason == "unavailable"
    with pytest.raises(crypto_coin.CoinNotFound):
        crypto_coin.build_crypto_coin("NOTLISTED", provider=FakeProvider(), now=NOW)
    with pytest.raises(ValueError):
        crypto_coin.build_crypto_coin("BTC", interval="7m", provider=FakeProvider(), now=NOW)


def test_page_symbol_resolution_falls_back_to_curated_when_the_venue_is_down():
    assert crypto_coin.resolve_page_symbol("btc", provider=FakeProvider()) == "BTC"
    down = FakeProvider(dex_error=DataUnavailable("down"))
    assert crypto_coin.resolve_page_symbol("eth", provider=down) == "ETH"  # curated roster still renders
    with pytest.raises(crypto_coin.CoinUnavailable):
        crypto_coin.resolve_page_symbol("kPEPE", provider=FakeProvider(dex_error=DataUnavailable("down")))


def test_routes_gate_serve_and_render_the_page(db, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/crypto/coin/BTC").json()["detail"]["code"] == "crypto_section_disabled"
    assert client.get("/crypto/BTC").status_code == 503
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    assert client.get("/api/crypto/coin/BTC").json()["detail"]["code"] == "hip3_public_display_pending_rights"
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", True)
    monkeypatch.setattr(crypto_coin, "_DEFAULT_PROVIDER", FakeProvider())

    response = client.get("/api/crypto/coin/btc?interval=1d")
    assert response.status_code == 200 and response.headers["x-data-source"] == "Hyperliquid"
    body = response.json()
    assert body["symbol"] == "BTC" and body["chart"]["interval"] == "1d"
    assert client.get("/api/crypto/coin/BTC?candles=false").json()["chart"]["omitted"] is True
    assert client.get("/api/crypto/coin/NOTLISTED").status_code == 404
    assert client.get("/api/crypto/coin/BTC?interval=7m").status_code == 422

    page = client.get("/crypto/kpepe")
    assert page.status_code == 200 and "kPEPE-PERP" in page.text and "/crypto/kPEPE" in page.text
    assert "무기한선물 시세·차트" in page.text
    named = client.get("/crypto/BTC")
    assert "비트코인 (BTC) 무기한선물 시세·차트" in named.text
    assert client.get("/crypto/NOTLISTED").status_code == 404
    assert client.get("/crypto/../etc").status_code == 404


def test_daily_chart_reuses_its_window_for_the_signal(crypto_on):
    fake = FakeProvider(candles=[_candle(BASE_MS + i * 86_400_000, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(120)])
    payload = crypto_coin.build_crypto_coin("BTC", interval="1d", provider=fake, now=NOW)
    assert fake.candle_calls == [("BTC", "1d", 365 * 24 * 3600)]  # one call, not two
    assert payload["signal"]["status"] == "ok" and payload["signal"]["candles_used"] == 120
    assert payload["signal"]["direction"]["band"] == "up"


def test_coin_payload_carries_the_krw_block_when_the_lane_is_open(crypto_on, monkeypatch):
    from app import crypto_kimchi

    monkeypatch.setattr(crypto_kimchi, "build_for_coin", lambda symbol, **kwargs: {"symbol": symbol, "krw": 106_000_000.0})
    payload = crypto_coin.build_crypto_coin("BTC", include_candles=False, provider=FakeProvider(), now=NOW)
    assert payload["krw"] == {"symbol": "BTC", "krw": 106_000_000.0}

    # A closed gate (or an unlisted coin) simply means no block…
    monkeypatch.setattr(crypto_kimchi, "build_for_coin", lambda symbol, **kwargs: None)
    assert crypto_coin.build_crypto_coin("BTC", include_candles=False, provider=FakeProvider(), now=NOW)["krw"] is None

    # …and a failure in that lane never takes the page down.
    def explode(symbol, **kwargs):
        raise RuntimeError("upbit down")

    monkeypatch.setattr(crypto_kimchi, "build_for_coin", explode)
    degraded = crypto_coin.build_crypto_coin("BTC", include_candles=False, provider=FakeProvider(), now=NOW)
    assert degraded["krw"] is None and degraded["market"]["price"]["value"] == 77000.0
