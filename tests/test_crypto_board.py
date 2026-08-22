"""Hyperliquid-wide market board — sorting and sums over one snapshot, thin markets filtered where stated."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_board
from app.main import app
from app.providers.base import DataUnavailable


def _market(symbol: str, mark: str, prev: str, *, volume: str, oi: str, funding: str = "0.0000125", delisted: bool = False) -> dict[str, Any]:
    return {
        "symbol": symbol, "dex": "main",
        "metadata": {"name": symbol, **({"isDelisted": True} if delisted else {})},
        "context": {"markPx": mark, "oraclePx": mark, "prevDayPx": prev, "dayNtlVlm": volume, "openInterest": oi, "funding": funding},
    }


class FixtureProvider:
    def __init__(self, markets: list[dict[str, Any]], *, error: Exception | None = None) -> None:
        self.markets = markets
        self.error = error

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        assert dex == "main"
        if self.error is not None:
            raise self.error
        return {"dex": dex, "fetched_at": "2026-08-22T01:00:00Z", "as_of": "2026-08-22T01:00:00Z", "cached": False, "stale": False, "age_seconds": 0.0, "markets": self.markets}


MARKETS = [
    _market("BTC", "77000", "70000", volume="7000000000", oi="33000", funding="0.0000125"),      # +10%
    _market("ETH", "2500", "2600", volume="3000000000", oi="500000", funding="-0.00002"),       # −3.85%
    _market("SOL", "90", "75", volume="500000000", oi="4000000", funding="0.00004"),           # +20%
    _market("THIN", "1", "0.5", volume="30000", oi="1000", funding="0.001"),                   # +100% but below the volume floor
    _market("DEAD", "5", "4", volume="9000000", oi="100", delisted=True),                      # delisted → ignored
    _market("NOPREV", "3", None, volume="2000000", oi="10"),                                   # no 24h reference
]


@pytest.fixture
def crypto_on(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)


def test_board_sorts_filters_and_sums(crypto_on):
    payload = crypto_board.build_crypto_board(FixtureProvider(MARKETS), limit=2)
    assert payload["totals"]["markets"] == 5  # delisted excluded, NOPREV counted
    assert payload["totals"]["open_interest_usd"] == pytest.approx(33000 * 77000 + 500000 * 2500 + 4000000 * 90 + 1000 * 1 + 10 * 3)
    assert payload["totals"]["volume_24h_usd"] == pytest.approx(7e9 + 3e9 + 5e8 + 30000 + 2000000)
    gainers = [row["symbol"] for row in payload["movers"]["gainers"]]
    assert gainers == ["SOL", "BTC"]  # THIN (+100%) is below the $1M floor; NOPREV has no change
    assert [row["symbol"] for row in payload["movers"]["losers"]] == ["ETH", "BTC"]
    assert [row["symbol"] for row in payload["leaders"]["open_interest"]] == ["BTC", "ETH"]
    assert [row["symbol"] for row in payload["leaders"]["volume"]] == ["BTC", "ETH"]
    assert [row["symbol"] for row in payload["funding"]["highest"]] == ["SOL", "BTC"]  # THIN's 0.001 excluded by the floor
    assert [row["symbol"] for row in payload["funding"]["lowest"]] == ["ETH", "BTC"]
    sol = payload["movers"]["gainers"][0]
    assert sol["change_24h_percent"] == pytest.approx(20.0)
    assert sol["funding_apr_percent"] == pytest.approx(0.00004 * 24 * 365 * 100, rel=1e-6)
    assert sol["funding_side"] == "longs_pay"
    assert payload["filters"]["min_volume_usd_for_movers_and_funding"] == 1_000_000.0
    assert payload["rights"]["status"] == "provider_terms_apply"


def test_board_outage_is_empty_and_labelled(crypto_on):
    payload = crypto_board.build_crypto_board(FixtureProvider([], error=DataUnavailable("down")))
    assert payload["provider"]["error"] == "unavailable"
    assert payload["movers"]["gainers"] == [] and payload["totals"]["markets"] == 0


def test_board_route_gates_and_serves(db, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/crypto/board").json()["detail"]["code"] == "crypto_section_disabled"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    assert client.get("/api/crypto/board").json()["detail"]["code"] == "hip3_public_display_pending_rights"
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", True)
    monkeypatch.setattr(crypto_board, "_DEFAULT_PROVIDER", FixtureProvider(MARKETS))
    response = client.get("/api/crypto/board")
    assert response.status_code == 200
    assert response.json()["leaders"]["open_interest"][0]["symbol"] == "BTC"
    assert response.headers["x-data-source"] == "Hyperliquid"
    assert 'id="crypto-board"' in client.get("/crypto").text
