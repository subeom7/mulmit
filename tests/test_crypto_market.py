"""Crypto section lanes — Hyperliquid native perps, alternative.me relay, derived volatility.

The rights posture is the point of every test here: Hyperliquid values ride the
HIP-3 display gate, the alternative.me relay is its own lane behind the section
switch and never runs in the request path, derived numbers come only from the
stored daily closes, and nothing is invented when an input is missing.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
import urllib.error
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_market, data_rights, hip3_history, ingest, store
from app.main import app
from app.providers.alternative_me import AlternativeMeProvider, parse_fear_greed
from app.providers.base import DataUnavailable, RateLimited
from app.providers.hyperliquid import _join_predicted_fundings

FETCHED_AT = "2026-08-21T12:00:00Z"


def _context(
    mark: str,
    previous: str,
    *,
    funding: str = "0.0000125",
    open_interest: str = "33325.4932",
    volume: str = "7488178726.49",
    oracle: str | None = None,
) -> dict[str, Any]:
    return {
        "markPx": mark,
        "oraclePx": oracle if oracle is not None else mark,
        "midPx": mark,
        "prevDayPx": previous,
        "funding": funding,
        "openInterest": open_interest,
        "dayNtlVlm": volume,
        "premium": "0.00055",
    }


class FixtureProvider:
    """Offline stand-in for the Hyperliquid client used by the overview."""

    def __init__(
        self,
        markets: list[tuple[str, dict[str, Any]]],
        *,
        predicted: dict[str, list[dict[str, Any]]] | None = None,
        stale: bool = False,
        error: Exception | None = None,
        predicted_error: Exception | None = None,
        delisted: set[str] | None = None,
    ) -> None:
        self.markets = markets
        self.predicted = predicted or {}
        self.stale = stale
        self.error = error
        self.predicted_error = predicted_error
        self.delisted = delisted or set()
        self.calls: list[str] = []

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        self.calls.append(f"dex:{dex}")
        if self.error is not None:
            raise self.error
        return {
            "dex": dex,
            "fetched_at": FETCHED_AT,
            "as_of": FETCHED_AT,
            "cached": False,
            "stale": self.stale,
            "age_seconds": 42.0 if self.stale else 0.0,
            "error": "DataUnavailable" if self.stale else None,
            "markets": [
                {
                    "symbol": symbol,
                    "dex": dex,
                    "metadata": {
                        "name": symbol,
                        **({"isDelisted": True} if symbol in self.delisted else {}),
                    },
                    "context": context,
                }
                for symbol, context in self.markets
            ],
        }

    def fetch_predicted_fundings(self) -> dict[str, Any]:
        self.calls.append("predicted")
        if self.predicted_error is not None:
            raise self.predicted_error
        return {"fetched_at": FETCHED_AT, "as_of": FETCHED_AT, "coins": self.predicted}


PREDICTED_BTC = [
    {"venue": "BinPerp", "funding_rate": 0.0001, "interval_hours": 8.0, "next_funding_at": "2026-08-21T16:00:00Z"},
    {"venue": "HlPerp", "funding_rate": 0.0000125, "interval_hours": 1.0, "next_funding_at": "2026-08-21T13:00:00Z"},
    {"venue": "BybitPerp", "funding_rate": 0.00005, "interval_hours": 8.0, "next_funding_at": "2026-08-21T16:00:00Z"},
]


def _two_coin_provider(**kwargs: Any) -> FixtureProvider:
    return FixtureProvider(
        [
            ("BTC", _context("76799.0", "71819.0")),
            ("ETH", _context("3250.0", "3190.0", funding="-0.00002", open_interest="500000", volume="2500000000")),
        ],
        predicted={"BTC": PREDICTED_BTC},
        **kwargs,
    )


@pytest.fixture
def crypto_section(db, hip3_public_display, monkeypatch):
    """Open the section switch, the HIP-3 display gate and the alternative.me lane."""
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "ALTERNATIVE_ME_ENABLED", True)
    crypto_market.clear_sentiment_cache()
    hip3_history.clear_cache()
    yield
    crypto_market.clear_sentiment_cache()
    hip3_history.clear_cache()


# --- overview ---------------------------------------------------------------


def test_overview_cards_carry_price_change_funding_and_relayed_predictions(crypto_section):
    payload = crypto_market.build_crypto_overview(_two_coin_provider())

    assert [card["symbol"] for card in payload["coins"]] == ["BTC", "ETH"]
    assert payload["coverage"]["available"] == 2
    assert "SOL" in payload["missing"] and "HYPE" in payload["missing"]

    btc = payload["coins"][0]
    assert btc["price"]["value"] == 76799.0
    assert btc["price"]["field"] == "markPx"
    assert btc["change_24h"]["percent"] == pytest.approx((76799.0 / 71819.0 - 1) * 100, rel=1e-6)
    # Hourly funding annualised: 0.0000125 × 24 × 365 = 10.95 %.
    assert btc["funding"]["apr_percent"] == pytest.approx(10.95)
    assert btc["funding"]["interval_hours"] == 1
    assert btc["funding"]["side"] == "longs_pay"
    assert btc["funding"]["heat"] == "normal"
    assert btc["open_interest"]["usd"] == pytest.approx(33325.4932 * 76799.0, rel=1e-9)
    assert btc["volume_24h_usd"] == pytest.approx(7488178726.49)
    assert btc["liquidity_status"] == "high"
    assert btc["source"]["publisher"] == "Hyperliquid"
    assert btc["rights"]["status"] == "provider_terms_apply"

    venues = {row["venue"]: row for row in btc["predicted_funding"]}
    assert set(venues) == {"BinPerp", "HlPerp", "BybitPerp"}
    # Binance 8h funding annualised: 0.0001 × 3 × 365 = 10.95 %.
    assert venues["BinPerp"]["apr_percent"] == pytest.approx(10.95)
    assert venues["BinPerp"]["interval_hours"] == 8.0
    assert venues["HlPerp"]["apr_percent"] == pytest.approx(10.95)
    assert venues["BybitPerp"]["apr_percent"] == pytest.approx(5.475)
    assert all(row["relayed_by"] == "Hyperliquid" for row in venues.values())
    assert "Hyperliquid 전달값" in venues["BinPerp"]["label"]["ko"]

    eth = payload["coins"][1]
    assert eth["funding"]["side"] == "shorts_pay"
    assert eth["predicted_funding"] == []

    ratio = payload["eth_btc"]
    assert ratio["pair"] == "ETH/BTC"
    assert ratio["value"] == pytest.approx(3250.0 / 76799.0, abs=1e-8)
    expected_change = ((3250.0 / 76799.0) / (3190.0 / 71819.0) - 1) * 100
    assert ratio["change_24h_percent"] == pytest.approx(expected_change, abs=1e-4)
    assert payload["predicted_funding"]["status"] == "ok"
    assert payload["provider"]["dex"] == "main"


def test_overview_skips_delisted_and_keeps_cards_when_predictions_fail(crypto_section):
    provider = _two_coin_provider(delisted={"ETH"}, predicted_error=DataUnavailable("down"))
    payload = crypto_market.build_crypto_overview(provider)

    assert [card["symbol"] for card in payload["coins"]] == ["BTC"]
    assert "ETH" in payload["missing"]
    assert payload["eth_btc"] is None
    assert payload["predicted_funding"]["status"] == "unavailable"
    assert payload["coins"][0]["predicted_funding"] == []


def test_overview_outage_reports_error_instead_of_numbers(crypto_section):
    payload = crypto_market.build_crypto_overview(_two_coin_provider(error=RateLimited("slow down")))
    assert payload["coins"] == []
    assert payload["eth_btc"] is None
    assert payload["provider"]["error"] == "rate_limited"
    assert payload["coverage"]["available"] == 0


def test_overview_stale_snapshot_marks_cards_stale(crypto_section):
    payload = crypto_market.build_crypto_overview(_two_coin_provider(stale=True))
    assert payload["provider"]["stale"] is True
    assert all(card["status"] == "stale" for card in payload["coins"])
    assert all(card["freshness"]["status"] == "stale" for card in payload["coins"])


def test_overview_route_is_gated_by_section_then_by_hip3_display(db, monkeypatch):
    client = TestClient(app)
    response = client.get("/api/crypto/overview")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "crypto_section_disabled"
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    response = client.get("/api/crypto/overview")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "hip3_public_display_pending_rights"

    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", True)
    monkeypatch.setattr(crypto_market, "_DEFAULT_PROVIDER", _two_coin_provider())
    response = client.get("/api/crypto/overview")
    assert response.status_code == 200
    assert response.headers["x-data-source"] == "Hyperliquid"
    assert response.json()["coins"][0]["symbol"] == "BTC"


def test_predicted_funding_join_drops_missing_venues_and_rejects_garbage():
    joined = _join_predicted_fundings(
        [
            [
                "0G",
                [
                    ["BinPerp", {"fundingRate": "0.00005", "nextFundingTime": 1787328000000, "fundingIntervalHours": 4}],
                    ["HlPerp", None],
                    ["BybitPerp", {"fundingRate": "nan"}],
                ],
            ],
            "junk",
            ["BTC", "not-a-list"],
        ]
    )
    assert joined == {
        "0G": [
            {
                "venue": "BinPerp",
                "funding_rate": 0.00005,
                "interval_hours": 4.0,
                "next_funding_at": "2026-08-21T16:00:00Z",
            }
        ]
    }
    with pytest.raises(DataUnavailable):
        _join_predicted_fundings({"unexpected": "object"})


def test_funding_arithmetic_and_bands():
    assert crypto_market.annualize_funding(0.0001, 8) == pytest.approx(10.95)
    assert crypto_market.annualize_funding(0.0000125, 1) == pytest.approx(10.95)
    assert crypto_market.annualize_funding(None, 8) is None
    assert crypto_market.annualize_funding(0.0001, 0) is None
    assert crypto_market.funding_heat(31.0) == "high"
    assert crypto_market.funding_heat(-16.0) == "elevated"
    assert crypto_market.funding_heat(5.0) == "normal"
    assert crypto_market.funding_heat(None) is None
    assert crypto_market.funding_side(0.0) == "balanced"
    assert crypto_market.funding_side(-1e-6) == "shorts_pay"


# --- alternative.me relay ---------------------------------------------------


def test_parse_fear_greed_sorts_dedupes_and_drops_malformed_rows():
    parsed = parse_fear_greed(
        {
            "name": "Fear and Greed Index",
            "data": [
                {"value": "72", "value_classification": "Greed", "timestamp": "1787270400", "time_until_update": "41925"},
                {"value": "62", "value_classification": "Greed", "timestamp": "1787184000"},
                {"value": "oops", "value_classification": "Fear", "timestamp": "1787097600"},
                {"value": "140", "value_classification": "Greed", "timestamp": "1787011200"},
            ],
            "metadata": {"error": None},
        },
        fetched_at=FETCHED_AT,
    )
    assert [row["date"] for row in parsed["observations"]] == ["2026-08-20", "2026-08-21"]
    assert parsed["observations"][-1]["value"] == 72
    assert parsed["next_update_in_seconds"] == 41925
    assert parsed["index_name"] == "Fear and Greed Index"

    with pytest.raises(DataUnavailable):
        parse_fear_greed({"data": [], "metadata": {"error": None}}, fetched_at=FETCHED_AT)
    with pytest.raises(DataUnavailable):
        parse_fear_greed({"data": [{"value": "1", "timestamp": "1"}], "metadata": {"error": "nope"}}, fetched_at=FETCHED_AT)
    with pytest.raises(DataUnavailable):
        parse_fear_greed(["not", "an", "object"], fetched_at=FETCHED_AT)


def test_provider_maps_http_failures_and_requests_the_limit():
    seen: list[str] = []

    def ok_transport(url: str, timeout: float) -> Any:
        seen.append(url)
        return {"data": [{"value": "50", "value_classification": "Neutral", "timestamp": "1787270400"}], "metadata": {"error": None}}

    provider = AlternativeMeProvider(transport=ok_transport, retries=0, sleep=lambda _s: None)
    result = provider.fetch_fear_greed(limit=30)
    assert result["observations"][0]["value"] == 50
    assert "limit=30" in seen[0] and "format=json" in seen[0]

    def rate_limited(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)

    with pytest.raises(RateLimited):
        AlternativeMeProvider(transport=rate_limited, retries=1, sleep=lambda _s: None).fetch_fear_greed()

    def not_found(url: str, timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)

    with pytest.raises(DataUnavailable):
        AlternativeMeProvider(transport=not_found, retries=2, sleep=lambda _s: None).fetch_fear_greed()


class FakeFearGreed:
    def __init__(self, days: int = 40, *, end: dt.date = dt.date(2026, 8, 21)) -> None:
        self.days = days
        self.end = end
        self.calls: list[int] = []

    def fetch_fear_greed(self, limit: int = 400) -> dict[str, Any]:
        self.calls.append(limit)
        rows = []
        for offset in range(self.days - 1, -1, -1):
            day = self.end - dt.timedelta(days=offset)
            stamp = int(dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC).timestamp())
            value = 40 + (self.days - offset)  # rises one point a day, latest = 40 + days
            rows.append({"date": day.isoformat(), "timestamp": stamp, "value": value, "classification": "Greed" if value >= 56 else "Neutral"})
        return {"fetched_at": "2026-08-21T11:00:00Z", "index_name": "Fear and Greed Index", "observations": rows, "next_update_in_seconds": 46800}


def test_refresh_stores_blob_and_serving_derives_changes_with_attribution(crypto_section):
    fake = FakeFearGreed()
    result = crypto_market.refresh_crypto_sentiment(provider=fake)
    assert result["updated"] == 1 and result["observations"] == 40
    assert fake.calls == [crypto_market.SENTIMENT_HISTORY_DAYS + 7]

    payload = crypto_market.build_crypto_sentiment(now=dt.datetime(2026, 8, 21, 12, 30, tzinfo=dt.UTC))
    assert payload["value"] == 80
    assert payload["as_of"] == "2026-08-21"
    assert payload["classification"] == {"ko": "탐욕", "en": "Greed"}
    assert payload["previous"]["change_points"] == 1
    assert payload["week_ago"]["change_points"] == 7
    assert payload["month_ago"]["change_points"] == 30
    assert payload["attribution"]["text"] == "Crypto Fear & Greed Index — alternative.me"
    assert payload["attribution"]["placement"] == "adjacent_to_value"
    assert payload["attribution"]["required"] is True
    assert payload["freshness"]["status"] == "fresh"
    assert payload["next_update_at"] == "2026-08-22T00:00:00Z"
    assert payload["rights"]["status"] == "approved"
    assert payload["source"]["read_path"] == "stored_daily_blob"
    assert 30 <= len(payload["observations"]) <= 91
    assert sum(item["weight_percent"] for item in payload["components"]) == 100

    # A fresh blob is not re-fetched within the refresh window.
    assert crypto_market.refresh_crypto_sentiment(provider=fake) == {"skipped": "fresh"}
    assert len(fake.calls) == 1

    # A blob older than the stale threshold is served, but says so.
    stale_payload = crypto_market.build_crypto_sentiment(now=dt.datetime(2026, 8, 23, 6, 0, tzinfo=dt.UTC))
    assert stale_payload["freshness"]["status"] == "stale"


def test_sentiment_lane_off_means_no_network_and_no_values(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "ALTERNATIVE_ME_ENABLED", False)
    crypto_market.clear_sentiment_cache()

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the alternative.me provider must not be constructed while the lane is off")

    monkeypatch.setattr(crypto_market, "AlternativeMeProvider", explode)
    assert crypto_market.refresh_crypto_sentiment() == {"skipped": "disabled"}
    assert ingest.refresh_crypto_sentiment() == {"skipped": "disabled"}
    with pytest.raises(crypto_market.CryptoSentimentUnavailable) as excinfo:
        crypto_market.build_crypto_sentiment()
    assert excinfo.value.reason == "disabled"


def test_sentiment_route_states(db, hip3_public_display, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/crypto/sentiment").json()["detail"]["code"] == "crypto_section_disabled"

    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    crypto_market.clear_sentiment_cache()
    assert client.get("/api/crypto/sentiment").json()["detail"]["code"] == "crypto_sentiment_disabled"

    monkeypatch.setattr(config, "ALTERNATIVE_ME_ENABLED", True)
    crypto_market.clear_sentiment_cache()
    response = client.get("/api/crypto/sentiment")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "crypto_sentiment_collecting"
    assert response.headers["cache-control"] == "no-store"

    crypto_market.refresh_crypto_sentiment(provider=FakeFearGreed(days=10))
    response = client.get("/api/crypto/sentiment")
    assert response.status_code == 200
    body = response.json()
    assert body["value"] == 50
    assert body["attribution"]["url"].startswith("https://alternative.me/")
    assert response.headers["x-data-source"] == "alternative.me"
    crypto_market.clear_sentiment_cache()


def test_ingest_wrapper_swallows_provider_failures(crypto_section, monkeypatch):
    def boom(**_kwargs: Any) -> dict[str, Any]:
        raise DataUnavailable("publisher down")

    monkeypatch.setattr(crypto_market, "refresh_crypto_sentiment", boom)
    result = ingest.refresh_crypto_sentiment()
    assert "failed" in result


# --- realized volatility and correlation ------------------------------------


def _closes(start: float, returns: list[float], end: dt.date = dt.date(2026, 8, 21)) -> list[dict[str, Any]]:
    rows = []
    level = start
    for offset, step in enumerate(returns):
        level *= math.exp(step)
        day = end - dt.timedelta(days=len(returns) - 1 - offset)
        rows.append({"date": day.isoformat(), "value": round(level, 6)})
    return rows


def _store_history(series: dict[str, list[dict[str, Any]]]) -> None:
    store.save_report(
        hip3_history.CACHE_KEY,
        {
            "generated_at": FETCHED_AT,
            "interval": "1d",
            "window_days": 366,
            "basis": hip3_history.BASIS,
            "series": {
                symbol: {"fetched_at": FETCHED_AT, "as_of": f"{rows[-1]['date']}T23:59:59Z", "interval": "1d", "observations": rows}
                for symbol, rows in series.items()
            },
        },
    )
    hip3_history.clear_cache()


@pytest.fixture
def history_lane(crypto_section, monkeypatch):
    monkeypatch.setattr(config, "HIP3_HISTORY_ENABLED", True)
    hip3_history.clear_cache()
    yield
    hip3_history.clear_cache()


def test_volatility_and_correlation_come_only_from_stored_closes(history_lane):
    steps = [((index % 5) - 2) * 0.01 + 0.0015 for index in range(45)]
    btc = _closes(70000.0, steps)
    sp500 = _closes(6000.0, steps)  # identical return path → correlation +1
    gold = _closes(3400.0, [-step for step in steps])  # mirror image → −1
    _store_history({"BTC": btc, "xyz:SP500": sp500, "xyz:GOLD": gold})

    payload = crypto_market.build_crypto_volatility()
    assert payload["status"] == "ok"
    assert payload["annualization_days"] == 365
    realized = {block["symbol"]: block for block in payload["realized"]}
    assert set(realized) == {"BTC"}
    windows = {row["window_days"]: row for row in realized["BTC"]["windows"]}
    log_returns = [math.log(btc[i]["value"] / btc[i - 1]["value"]) for i in range(1, len(btc))]
    expected_7 = statistics.stdev(log_returns[-7:]) * math.sqrt(365) * 100
    assert windows[7]["value"] == pytest.approx(expected_7, rel=1e-4)
    assert windows[7]["as_of"] == "2026-08-21"
    assert windows[30]["status"] == "ok" and windows[30]["value"] > 0

    correlations = {row["peer"]: row for row in payload["correlations"]}
    assert set(correlations) == {"xyz:SP500", "xyz:GOLD"}  # KR200/XYZ100 absent → not invented
    sp_windows = {row["window_days"]: row for row in correlations["xyz:SP500"]["windows"]}
    assert sp_windows[30]["value"] == pytest.approx(1.0, abs=1e-6)
    assert sp_windows[30]["points"] == 30
    assert sp_windows[90]["status"] == "ok" and sp_windows[90]["points"] == 44
    gold_windows = {row["window_days"]: row for row in correlations["xyz:GOLD"]["windows"]}
    assert gold_windows[30]["value"] == pytest.approx(-1.0, abs=1e-6)


def test_volatility_withheld_while_history_gate_is_closed(crypto_section):
    payload = crypto_market.build_crypto_volatility()
    assert payload["status"] == hip3_history.STATUS_WITHHELD
    assert payload["realized"] == [] and payload["correlations"] == []


def test_volatility_with_too_little_history_says_so(history_lane):
    _store_history({"BTC": _closes(70000.0, [0.01, -0.01, 0.02])})
    payload = crypto_market.build_crypto_volatility()
    block = payload["realized"][0]
    assert all(row["status"] == "insufficient_history" and row["value"] is None for row in block["windows"])
    assert payload["correlations"] == []


def test_history_symbols_follow_the_section_switch(db, monkeypatch):
    """크립토 섹션 전용 코인만 섹션 스위치를 따른다.

    BTC와 ETH는 홈 보드가 상시로 쓰는 자산이라 ASSETS에 있고, 그래서 섹션이
    꺼져 있어도 이력을 모은다(같은 lane·같은 게이트·같은 공급자). 섹션에만
    쓰이는 SOL은 스위치를 그대로 따른다.
    """
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", False)
    symbols = hip3_history._symbols()
    assert "BTC" in symbols and "ETH" in symbols
    assert "SOL" not in symbols
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    symbols = hip3_history._symbols()
    assert symbols.count("BTC") == 1
    assert symbols.count("ETH") == 1
    assert "SOL" in symbols


# --- page, sitemap, lane report --------------------------------------------


def test_crypto_page_nav_and_sitemap(db):
    client = TestClient(app)
    page = client.get("/crypto")
    assert page.status_code == 200
    assert 'window.MULMIT_PAGE = "crypto";' in page.text
    # 한국어 화면은 "크립토"가 아니라 "암호화폐"로 부른다. 흔히 쓰이는 말이고,
    # 검색량도 그쪽이 훨씬 많다. 코드의 식별자(/crypto, nav.crypto, .crypto-card)는
    # 그대로 두고 눈에 보이는 글만 바꾼 것이라, 여기서 지켜야 하는 것도 글이다.
    assert "암호화폐" in page.text and "Hyperliquid" in page.text
    assert "크립토" not in page.text, "옛 워딩이 화면에 남았다"
    for path in ("/", "/kr", "/us", "/crypto"):
        assert 'href="/crypto"' in client.get(path).text, path
    assert "https://mulmit.com/crypto" in client.get("/sitemap-pages.xml").text


def test_lane_report_names_the_crypto_gates(db, monkeypatch):
    report = data_rights.lane_report()
    assert report["crypto"]["status"] == "disabled"
    assert report["crypto"]["overview_gate"] == "CRYPTO_SECTION_ENABLED + HIP3_PUBLIC_DISPLAY_ENABLED"
    assert report["alternative_me"]["status"] == "disabled"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "ALTERNATIVE_ME_ENABLED", True)
    report = data_rights.lane_report()
    assert report["alternative_me"]["status"] == "enabled"
    assert report["crypto"]["overview"] == "withheld"  # HIP-3 display gate still closed


def test_every_card_coin_is_collected_so_its_trend_line_can_exist(monkeypatch):
    """카드가 있는 코인은 전부 이력 lane이 모아야 한다.

    추이선은 카드마다 필요한데, 예전에는 lane이 BTC·ETH·SOL 셋만 모았다. 코인을
    카드에 더해도 선은 영영 비어 있었을 것이다 — 그리고 그건 에러가 아니라
    "선이 없는 카드"로만 보인다.
    """
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    collected = set(crypto_market.history_symbols())
    for symbol in crypto_market.coin_symbols():
        assert symbol in collected, f"{symbol} 카드는 있는데 이력을 모으지 않는다"
    # 변동성·상관 표본은 손으로 고른 목록 그대로다. 여기에 코인이 늘면 그 표에
    # 줄이 따라 늘어나는데, 둘은 서로 다른 질문에 답한다.
    assert crypto_market.HISTORY_COINS == ("BTC", "ETH", "SOL")


def test_the_lane_stays_closed_when_the_crypto_section_is_off(monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", False)
    assert crypto_market.history_symbols() == []


def test_a_coin_without_stored_history_gets_no_invented_line(monkeypatch):
    """없는 값은 만들지 않는다 — 아직 안 모인 코인은 선 없이 카드만 선다."""
    monkeypatch.setattr(hip3_history, "enabled", lambda: True)
    monkeypatch.setattr(hip3_history, "load", lambda: {"series": {}})
    cards = [{"symbol": "BTC"}, {"symbol": "SUI"}]
    crypto_market._attach_sparklines(cards)
    assert all("observations" not in card for card in cards)


def test_a_coin_with_stored_history_carries_its_daily_closes(monkeypatch):
    rows = [{"date": f"2026-08-{day:02d}", "value": 100.0 + day} for day in range(1, 21)]
    monkeypatch.setattr(hip3_history, "enabled", lambda: True)
    monkeypatch.setattr(hip3_history, "load", lambda: {"series": {"BTC": {"observations": rows}}})
    cards = [{"symbol": "BTC"}, {"symbol": "SUI"}]
    crypto_market._attach_sparklines(cards)
    assert cards[0]["observations"], "저장된 종가가 카드에 실리지 않았다"
    assert cards[0]["observations"][-1]["value"] == 120.0
    assert "observations" not in cards[1]


def test_the_history_lane_being_shut_costs_only_the_line(monkeypatch):
    """블롭이 닫혀 있어도 카드 자체는 그대로 서야 한다."""
    monkeypatch.setattr(hip3_history, "enabled", lambda: False)
    cards = [{"symbol": "BTC", "price": {"value": 1.0}}]
    crypto_market._attach_sparklines(cards)
    assert cards == [{"symbol": "BTC", "price": {"value": 1.0}}]
