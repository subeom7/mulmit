"""코인 상세가 크롤러에게 내용을 준다 — 그리고 사이트맵에 올라간다.

2026-08-24 실측: `/crypto/BTC`가 크롤러에게 주는 본문이 **677자**였고, 코인
페이지는 사이트맵에 **아예 없었다**. 구글이 존재를 모르는 상태였다.

종목 페이지(3,000개)와 달리 코인은 10개뿐이라 페이지 수로는 작다. 다만
비트코인·이더리움은 검색량이 큰 키워드다 — 여기서는 개수가 아니라 키워드의
무게가 값을 정한다.
"""

from __future__ import annotations

import re

import pytest

from app import config, crypto_coin_page, crypto_liquidations, hip3_history, store


@pytest.fixture
def stored(db, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "HIP3_HISTORY_ENABLED", True)
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", True)
    hip3_history._cache = None
    store.save_report(hip3_history.CACHE_KEY, {
        "generated_at": "2026-08-24T00:00:00Z",
        "series": {"BTC": {"observations": [
            {"date": "2026-08-22", "value": 61000.0},
            {"date": "2026-08-23", "value": 62500.0},
            {"date": "2026-08-24", "value": 60250.0},
        ]}},
    })
    store.save_report(crypto_liquidations.CACHE_KEY, {
        "generated_at": "2026-08-24T00:00:00Z",
        "coins": [{
            "symbol": "BTC",
            "liquidations": {"window_hours": 24, "long_usd": 15_166_374.0,
                             "short_usd": 20_092_481.0, "total_usd": 35_258_855.0},
            "open_interest": {"usd": 1_200_000_000.0},
        }],
    })
    return "BTC"


def test_the_body_carries_the_stored_facts(stored):
    body = crypto_coin_page.render("BTC", label="비트코인")
    assert "비트코인 최근 90일" in body
    assert "$62,500" in body and "$60,250" in body
    assert "청산 롱 (24시간)" in body and "$15.2M" in body
    assert "미결제약정" in body


def test_it_says_what_the_number_is_not(stored):
    """현물 가격으로 읽히면 안 된다. 무기한선물이고, 청산은 집계이며 틱이 아니다."""
    body = crypto_coin_page.render("BTC", label="비트코인")
    assert "현물 거래소 가격이 아닙니다" in body
    assert "틱 피드가 아닙니다" in body


def test_nothing_stored_renders_nothing_rather_than_failing(db):
    assert crypto_coin_page.render("NOPE", label="없는코인") == ""


def test_the_render_reads_only_what_is_stored(stored, monkeypatch):
    """크롤러가 하이퍼리퀴드를 두드리게 하지 않는다."""
    def explode(*args, **kwargs):
        raise AssertionError("렌더 경로에서 상류를 불렀다")

    monkeypatch.setattr(hip3_history, "refresh_hip3_history", explode, raising=False)
    assert "비트코인 최근 90일" in crypto_coin_page.render("BTC", label="비트코인")


def test_the_coin_pages_are_in_the_sitemap(stored):
    from fastapi.testclient import TestClient

    from app.main import app

    body = TestClient(app).get("/sitemap-stocks.xml").text
    found = re.findall(r"https://mulmit\.com/crypto/([A-Z0-9]+)", body)
    assert "BTC" in found and "ETH" in found, (
        "코인 페이지가 사이트맵에 없으면 구글은 그 페이지의 존재를 모른다"
    )


def test_the_indexing_block_is_removed_only_after_a_real_render() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "static" / "crypto-coin.html").read_text(
        encoding="utf-8"
    )
    assert '<div id="ssr-body">{{SSR}}</div>' in source
    assert "if (ssr && drew) ssr.remove();" in source, (
        "값을 못 그렸는데 지우면 빈 페이지가 남는다"
    )
