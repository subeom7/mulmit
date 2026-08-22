"""One search box over three stored rosters — ranking, isolation, and the route."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, kr_stocks, search, store
from app.main import app
from app.providers.base import DataUnavailable


def _market(symbol: str, *, volume: str, delisted: bool = False) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "dex": "main",
        "metadata": {"name": symbol, **({"isDelisted": True} if delisted else {})},
        "context": {"markPx": "1", "prevDayPx": "1", "dayNtlVlm": volume, "openInterest": "1"},
    }


MARKETS = [
    _market("BTC", volume="7000000000"),
    _market("BNB", volume="900000000"),
    _market("ARB", volume="5000000000"),   # substring match on "b"
    _market("BLAST", volume="12000"),      # prefix match, nearly no volume
    _market("BUSD", volume="8000000000", delisted=True),
]


class FixtureProvider:
    def __init__(self, markets: list[dict[str, Any]], *, error: Exception | None = None) -> None:
        self.markets = markets
        self.error = error

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        assert dex == "main"
        if self.error is not None:
            raise self.error
        return {"dex": dex, "as_of": "2026-08-22T01:00:00Z", "markets": self.markets}


@pytest.fixture
def rosters(db, monkeypatch, hip3_public_display):
    """All three lanes on, each reading the same stores the site reads."""
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(search, "_DEFAULT_PROVIDER", FixtureProvider(MARKETS))

    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "test-key")
    kr_stocks._recent_failures.clear()
    db.save_kr_listings(
        [
            {"srtn_cd": "282330", "itms_nm": "BGF리테일", "mrkt_ctg": "KOSPI",
             "clpr": 121000.0, "flt_rt": -1.5, "mrkt_tot_amt": 2.1e12},
            {"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
             "clpr": 268000.0, "flt_rt": 4.89, "mrkt_tot_amt": 1.6e15},
        ],
        "2026-08-21",
    )

    db.save_insider_filings("BAC", cik="0000070858", name="Bank of America Corp",
                            exchange="NYSE", filings_seen=1, transactions=[])
    db.save_insider_filings("AAPL", cik="0000320193", name="Apple Inc.",
                            exchange="Nasdaq", filings_seen=1, transactions=[])
    return db


def test_score_ranks_exact_then_prefix_then_substring():
    assert search._score("btc", "BTC") == 0
    assert search._score("bt", "BTC") == 10
    assert search._score("tc", "BTC") == 20
    assert search._score("xrp", "BTC", None) is None
    # Earlier fields win a tie: the symbol column outranks the name column.
    assert search._score("sol", "SOL", "솔라나") < search._score("솔라나", "SOL", "솔라나")


def test_coin_hits_rank_by_match_quality_then_liquidity(rosters):
    symbols = [hit["symbol"] for hit in search._coin_hits("b", 10)]
    assert symbols == ["BTC", "BNB", "BLAST", "ARB"]   # prefixes by volume, then the substring
    assert "BUSD" not in symbols                       # delisted stays out
    hits = search._coin_hits("b", 10)
    assert hits[0]["hub"] == "/crypto/BTC" and hits[0]["name"] == "비트코인"
    # Korean names are searchable; a coin outside the curated list falls back to its symbol.
    assert [hit["symbol"] for hit in search._coin_hits("비트", 10)] == ["BTC"]
    assert search._coin_hits("arb", 10)[0]["name"] == "ARB"
    assert len(search._coin_hits("b", 2)) == 2


def test_all_three_rosters_answer_the_same_needle(rosters):
    payload = search.search("b")
    assert [group["kind"] for group in payload["groups"]] == ["crypto", "kr_stock", "us_stock"]
    assert payload["count"] == sum(len(group["results"]) for group in payload["groups"])

    by_kind = {group["kind"]: group["results"] for group in payload["groups"]}
    assert by_kind["kr_stock"] == [{"kind": "kr_stock", "symbol": "282330", "name": "BGF리테일",
                                    "market": "KOSPI", "change_percent": -1.5, "hub": "/stock/282330"}]
    assert by_kind["us_stock"] == [{"kind": "us_stock", "symbol": "BAC", "name": "Bank of America Corp",
                                    "market": "NYSE", "hub": "/stock/BAC"}]
    assert payload["groups"][0]["label"]["ko"] == "코인"


def test_a_needle_only_one_roster_knows_drops_the_others(rosters):
    assert [group["kind"] for group in search.search("blast")["groups"]] == ["crypto"]
    assert [group["kind"] for group in search.search("삼성")["groups"]] == ["kr_stock"]
    assert [group["kind"] for group in search.search("apple")["groups"]] == ["us_stock"]


def test_kr_roster_receives_the_query_as_typed(rosters, monkeypatch):
    """Case-folding the needle before the KR roster hid every Latin-letter name.

    The coin and US rosters compare in Python and fold their own fields, but the
    Korean roster matches in SQL — and `LIKE` is case-sensitive on PostgreSQL,
    so "BGF" arrived as "bgf" and matched nothing on the live database.
    """
    seen: list[tuple[str, int]] = []
    real = kr_stocks.search
    monkeypatch.setattr(kr_stocks, "search", lambda query, limit: (seen.append((query, limit)), real(query, limit))[1])

    assert [hit["symbol"] for hit in search.search("BGF")["groups"][0]["results"]] == ["282330"]
    assert seen == [("BGF", search.DEFAULT_LIMIT)]

    assert [hit["symbol"] for hit in search._kr_hits("bgf", 5)] == ["282330"]


def test_us_hits_put_the_closer_match_first(rosters):
    hits = search._us_hits("a", 10)
    assert [hit["symbol"] for hit in hits] == ["AAPL", "BAC"]   # ticker prefix beats a substring


def test_one_roster_failing_never_empties_the_others(rosters, monkeypatch):
    monkeypatch.setattr(search, "_DEFAULT_PROVIDER", FixtureProvider([], error=DataUnavailable("upstream")))
    assert [group["kind"] for group in search.search("b")["groups"]] == ["kr_stock", "us_stock"]

    def boom(query, limit=10):
        raise RuntimeError("roster table is mid-migration")

    monkeypatch.setattr(store, "search_kr_listings", boom)
    assert [group["kind"] for group in search.search("b")["groups"]] == ["us_stock"]


def test_disabled_crypto_section_hides_only_the_coin_group(rosters, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", False)
    assert [group["kind"] for group in search.search("b")["groups"]] == ["kr_stock", "us_stock"]


def test_kr_lane_off_drops_its_group(rosters, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", False)
    with pytest.raises(kr_stocks.KrStockDisabled):
        kr_stocks.search("b", 5)
    assert [group["kind"] for group in search.search("b")["groups"]] == ["crypto", "us_stock"]


def test_blank_query_searches_nothing(rosters):
    for query in ("", "   "):
        payload = search.search(query)
        assert payload["groups"] == [] and payload["count"] == 0


def test_route_validates_serves_and_names_its_sources(rosters):
    client = TestClient(app)
    assert client.get("/api/search").status_code == 422           # q is required
    assert client.get("/api/search?q=").status_code == 422        # and non-empty
    assert client.get("/api/search?q=btc&limit=99").status_code == 422

    response = client.get("/api/search?q=btc")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=120"
    assert "Hyperliquid" in response.headers["X-Data-Source"]
    body = response.json()
    assert body["query"] == "btc"
    assert body["groups"][0]["results"][0]["hub"] == "/crypto/BTC"
    assert "Hyperliquid" in body["basis"]["en"] and "금융위" in body["basis"]["ko"]

    assert len(client.get("/api/search?q=b&limit=2").json()["groups"][0]["results"]) == 2
