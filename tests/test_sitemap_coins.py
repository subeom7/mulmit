"""The coin sitemap lists exactly what /crypto/{symbol} will render — and nothing else."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_coin
from app.main import app
from app.providers.base import DataUnavailable


def _market(symbol: str, *, delisted: bool = False) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "dex": "main",
        "metadata": {"name": symbol, **({"isDelisted": True} if delisted else {})},
        "context": {"markPx": "1", "prevDayPx": "1", "dayNtlVlm": "1000", "openInterest": "1"},
    }


MARKETS = [
    _market("BTC"), _market("ETH"), _market("ZRO"), _market("kPEPE"),
    _market("GONE", delisted=True),
    _market("BAD/SYMBOL"),          # the page route would not accept this path
]


class FixtureProvider:
    def __init__(self, markets: list[dict[str, Any]], *, error: Exception | None = None) -> None:
        self.markets = markets
        self.error = error

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return {"dex": dex, "as_of": "2026-08-22T01:00:00Z", "markets": self.markets}


@pytest.fixture
def venue(db, monkeypatch, hip3_public_display):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(crypto_coin, "_DEFAULT_PROVIDER", FixtureProvider(MARKETS))


def test_page_symbols_are_the_listed_markets_curated_first(venue):
    rows = crypto_coin.page_symbols()
    symbols = [symbol for symbol, _curated in rows]
    assert symbols == ["BTC", "ETH", "ZRO", "kPEPE"]        # curated first, then alphabetical
    assert dict(rows)["BTC"] is True and dict(rows)["ZRO"] is False
    assert "GONE" not in symbols                            # delisted
    assert "BAD/SYMBOL" not in symbols                      # the route would 404 on the path


def test_a_coin_the_venue_stopped_listing_is_not_added_back(venue, monkeypatch):
    """Only an outage falls back to the curated list — a successful snapshot is the truth.

    Otherwise the sitemap would advertise a URL the page route answers 404 on.
    """
    monkeypatch.setattr(crypto_coin, "_DEFAULT_PROVIDER", FixtureProvider([_market("BTC")]))
    assert [symbol for symbol, _ in crypto_coin.page_symbols()] == ["BTC"]

    client = TestClient(app)
    assert client.get("/crypto/SOL").status_code == 404
    assert "/crypto/SOL" not in client.get("/sitemap-coins.xml").text


def test_an_unreachable_venue_still_lists_the_curated_coins(venue, monkeypatch):
    monkeypatch.setattr(crypto_coin, "_DEFAULT_PROVIDER", FixtureProvider([], error=DataUnavailable("down")))
    rows = crypto_coin.page_symbols()
    assert [symbol for symbol, _ in rows] == [spec.symbol for spec in crypto_coin.COIN_SPECS]
    assert all(curated for _symbol, curated in rows)
    # And the page route agrees: a curated coin still renders during the outage.
    assert TestClient(app).get("/crypto/BTC").status_code == 200


def test_the_sitemap_serves_every_listed_coin_and_is_indexed(venue):
    client = TestClient(app)
    body = client.get("/sitemap-coins.xml")
    assert body.status_code == 200
    assert body.headers["content-type"].startswith("application/xml")
    for symbol in ("BTC", "ETH", "ZRO", "kPEPE"):
        assert f"<loc>https://mulmit.com/crypto/{symbol}</loc>" in body.text
    assert "<priority>0.7</priority>" in body.text and "<priority>0.5</priority>" in body.text

    assert "sitemap-coins.xml" in client.get("/sitemap.xml").text
    # The ten hardcoded coin rows moved out of the static sitemap; no URL is in both.
    assert "/crypto/BTC" not in client.get("/sitemap-pages.xml").text
    assert "https://mulmit.com/crypto<" in client.get("/sitemap-pages.xml").text.replace("</loc>", "<")


def test_the_section_gate_empties_the_sitemap(db, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", False)
    body = TestClient(app).get("/sitemap-coins.xml")
    assert body.status_code == 200
    assert "<urlset" in body.text and "/crypto/" not in body.text
