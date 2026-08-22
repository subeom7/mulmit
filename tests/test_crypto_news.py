"""Crypto headlines — coin tagging on titles, the filtered payload, and the route's gates."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, news_feed, store
from app.main import app


def _article(title: str, url: str, *, domain: str = "example.com", seendate: str = "2026-08-22T06:00:00Z") -> dict[str, Any]:
    return {"title": title, "url": url, "domain": domain, "seendate": seendate,
            "also_on": 0, "tags": news_feed._tags_for(title)}


ARTICLES = [
    _article("Bitcoin nears $80K as spot ETFs add $1.6B", "https://a.example/1"),
    _article("Chainlink and AVAX lead altcoin rally; XRP up 21%", "https://a.example/2"),
    _article("DOGE cuts 2,000 federal jobs", "https://a.example/3"),
    _article("ETH Zurich researchers publish a battery study", "https://a.example/4"),
    _article("Wall Street week ahead: inflation on tap", "https://a.example/5"),
    _article("Samsung Electronics and Bitcoin miners sign a chip deal", "https://a.example/6"),
]


@pytest.fixture
def news_on(db, monkeypatch):
    monkeypatch.setattr(config, "GDELT_ENABLED", True)
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    store.save_report(news_feed.CACHE_KEY, {
        "generated_at": "2026-08-22T06:00:00Z",
        "articles": ARTICLES,
        "attribution": {"required": True, "text": "GDELT Project", "text_ko": "GDELT 프로젝트", "url": "https://www.gdeltproject.org/"},
        "source": {"provider": "gdelt"},
        "rights": {"status": "approved"},
        "basis_ko": "제목·출처·링크까지만",
        "basis_en": "title, source and link only",
    })


def test_coin_tags_match_names_but_never_ambiguous_tickers():
    tag_ids = lambda title: [(tag["symbol"], tag["kind"]) for tag in news_feed._tags_for(title)]  # noqa: E731
    assert tag_ids("Bitcoin nears $80K as spot ETFs add $1.6B") == [("BTC", "crypto")]
    assert tag_ids("Ethereum staking yields fall as Solana volume climbs") == [("ETH", "crypto"), ("SOL", "crypto")]
    assert sorted(tag_ids("Chainlink and AVAX lead altcoin rally; XRP up 21%")) == [("AVAX", "crypto"), ("LINK", "crypto"), ("XRP", "crypto")]
    # Words that mean something else in 2026 news: the US government's DOGE and ETH Zurich.
    assert tag_ids("DOGE cuts 2,000 federal jobs") == []
    assert tag_ids("ETH Zurich researchers publish a battery study") == []
    assert tag_ids("A solar farm in Sol de Mañana links two grids") == []
    # Equity tags keep working and now carry their kind, and a title can hold both.
    both = tag_ids("Samsung Electronics and Bitcoin miners sign a chip deal")
    assert ("005930", "equity") in both and ("BTC", "crypto") in both


def test_crypto_keywords_let_crypto_headlines_through_the_filter():
    for keyword in ("bitcoin", "ethereum", "crypto", "stablecoin", "altcoin", "digital asset"):
        assert keyword in news_feed.TITLE_KEYWORDS


def test_crypto_articles_filters_by_tag_and_by_symbol(news_on):
    payload = news_feed.crypto_articles()
    urls = [article["url"] for article in payload["articles"]]
    assert urls == ["https://a.example/1", "https://a.example/2", "https://a.example/6"]
    assert payload["count"] == 3 and payload["attribution"]["text_ko"] == "GDELT 프로젝트"
    assert all(article["coins"] for article in payload["articles"])
    assert {coin["symbol"] for coin in payload["articles"][1]["coins"]} == {"LINK", "AVAX", "XRP"}
    assert payload["articles"][0]["coins"][0]["hub"] == "/crypto/BTC"

    only_xrp = news_feed.crypto_articles("xrp")
    assert [article["url"] for article in only_xrp["articles"]] == ["https://a.example/2"]
    assert only_xrp["symbol"] == "XRP"
    assert news_feed.crypto_articles("HYPE")["articles"] == []
    assert len(news_feed.crypto_articles(limit=1)["articles"]) == 1


def test_news_route_gates_and_serves(db, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/crypto/news").json()["detail"]["code"] == "crypto_section_disabled"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "GDELT_ENABLED", False)
    assert client.get("/api/crypto/news").json()["detail"]["code"] == "crypto_news_disabled"
    monkeypatch.setattr(config, "GDELT_ENABLED", True)
    assert client.get("/api/crypto/news").json()["detail"]["code"] == "crypto_news_collecting"
    store.save_report(news_feed.CACHE_KEY, {"generated_at": "2026-08-22T06:00:00Z", "articles": ARTICLES})
    response = client.get("/api/crypto/news?symbol=BTC&limit=5")
    assert response.status_code == 200 and response.headers["x-data-source"] == "GDELT"
    body = response.json()
    assert [article["url"] for article in body["articles"]] == ["https://a.example/1", "https://a.example/6"]
    assert 'id="crypto-news"' in client.get("/crypto").text
