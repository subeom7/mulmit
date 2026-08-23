"""뉴스 필터 — 실제로 화면에 올라왔던 제목들로 지킨다.

2026-08-24 라이브에서 홈 피드 최상단이 "Netflix's Outer Banks Finale Shatters
An IMDb Series Record"였다. 시장 화면에서 가장 눈에 띄는 자리다. 저장된 40건을
읽어 보니 세 가지가 섞여 있었다:

1. **템플릿으로 찍어 낸 종목 기사** 7건. 같은 배당 공시가 동사만 바꿔 세 번
   실려 있었다("Declares" / "to Issue" / "Plans").
2. **연예·쇼핑 기사**가 회사 이름 때문에 종목 태그를 달고 들어왔다.
3. **부분 문자열 매칭 버그**: 키워드 "iran"이 인도 정치인 이름 "Smriti Irani"를
   잡아 국내 정치 기사를 시장 화면에 올렸다.

아래 제목은 전부 실제로 관측된 것이다. 지어내지 않았다.
"""

from __future__ import annotations

import pytest

from app.news_feed import (
    _has_business_context,
    _is_generated,
    _matches_keyword,
    _tags_for,
    admits,
)


def admitted(title: str) -> bool:
    """`refresh()`가 이 제목을 남기는가 — **운영 함수를 그대로** 부른다.

    규칙을 테스트에서 다시 구현하면 둘이 어긋나도 아무도 모른다.
    """
    return admits(title, _tags_for(title))


# --- 부분 문자열 매칭 버그 -------------------------------------------------

def test_a_persons_name_containing_a_keyword_is_not_market_news():
    """키워드 "iran"이 "Smriti Irani"를 잡고 있었다."""
    assert not admitted("After Rahul's Pune outreach, Smriti Irani dares him to back 33% women's quota")


@pytest.mark.parametrize("title", [
    "Iran Warns of 'Seismic' Retaliation",
    "Greece moves Patriot system to Crete amid tensions with Iran",
    "Iraq PMF law risks entrenching Iran-backed militias as parallel force",
])
def test_real_iran_coverage_still_gets_through(title: str):
    assert admitted(title)


def test_plural_keywords_still_match():
    """단어 경계만 두면 "tariff"가 "tariffs"를 놓쳐 관세 기사가 통째로 빠졌다."""
    assert admitted("Trump's new 50% tariffs on Canadian goods: What to know")
    assert admitted("Trump moves to ease beef tariffs as US cattle producers object")
    assert admitted("Canada's leader lashes US for trade war tariff attack")


# --- 템플릿 종목 기사 ------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Critical Review: Seven Hills Realty Trust (NASDAQ:SEVN) & Granite Point Mortgage",
    "Critical Contrast: Franklin Wireless (NASDAQ:FKWL) and Ituran Location and Control",
    "Financial Analysis: Advent Technologies (NASDAQ:ADNWW) and Power Solutions",
    "Reviewing Pegasystems (NASDAQ:PEGA) and BTCS (NASDAQ:BTCS)",
    "SATA Technology Co., Ltd. Declares Dividend of $0.05 (NASDAQ:SATA)",
    "SATA Technology Co., Ltd. to Issue Dividend of $0.05 (NASDAQ:SATA)",
    "SATA Technology Co., Ltd. Plans Dividend of $0.05 (NASDAQ:SATA)",
])
def test_template_generated_stock_articles_are_dropped(title: str):
    assert _is_generated(title)
    assert not admitted(title)


# --- 연예·쇼핑 -------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Netflix's Outer Banks Finale Shatters An IMDb Series Record",
    "Disney Plus Fall 2026 Schedule: All The New Movies And TV Shows Coming Soon",
    "One Piece Season 3 Cast: New Actors Join Battle Of Alabasta On Netflix",
    "Amazon early Labor Day deals on tools and tech",
    "Four Korean Teams Fight for Worlds 2026 Spots in LA, Dallas, New York",
])
def test_entertainment_and_shopping_are_dropped(title: str):
    assert not admitted(title)


# --- 태그만으로는 부족하다 -------------------------------------------------

@pytest.mark.parametrize("title", [
    "Alfonso Herrera leads Netflix Action Thriller Facing El Chapo",
    "An ultra-rare piece of Microsoft history could be hiding on your shelf",
])
def test_a_company_name_alone_does_not_make_it_market_news(title: str):
    assert _tags_for(title), "이 제목들은 태그가 붙는다 — 그게 통과의 이유였다"
    assert not admitted(title)


@pytest.mark.parametrize("title", [
    "Tesla recalls nearly 3M vehicles over doors that may be difficult to open",
    "Amazon's Free Cash Flow Went Negative by $7.6 Billion Even as Operating Cash Rose",
    "Nvidia Earnings, Jackson Hole, and the Fed: What to Watch",
    "Forget Broadcom: Nvidia (NVDA) Is Still the Top Semiconductor Stock",
])
def test_real_company_news_survives_without_a_macro_keyword(title: str):
    """거시 키워드를 요구했다면 테슬라 리콜이 빠졌을 것이다."""
    assert admitted(title)


def test_the_tesla_recall_has_no_macro_keyword_at_all():
    """앞 테스트가 무엇을 지키는지 못 박아 둔다."""
    assert not _matches_keyword("Tesla recalls nearly 3M vehicles over doors")
    assert _has_business_context("Tesla recalls nearly 3M vehicles over doors")


# --- 필터가 전부를 지우지는 않는다 -----------------------------------------

def test_the_filter_keeps_most_of_a_real_day():
    """실측 40건 중 24건이 남았다. 다 지우는 필터는 필터가 아니다."""
    observed = [
        "Trump's new 50% tariffs on Canadian goods: What to know",
        "Iran Warns of 'Seismic' Retaliation",
        "Nvidia Earnings, Jackson Hole, and the Fed: What to Watch",
        "Tesla recalls nearly 3M vehicles over doors that may be difficult to open",
        "Netflix's Outer Banks Finale Shatters An IMDb Series Record",
        "Critical Review: Seven Hills Realty Trust (NASDAQ:SEVN) & Granite Point",
    ]
    kept = [title for title in observed if admitted(title)]

    assert len(kept) == 4, kept


# --- 이미 저장된 기사도 같은 문을 지난다 ---------------------------------

def test_stored_articles_are_filtered_again_on_refresh(monkeypatch):
    """블롭은 이전 기사를 URL로 이어받아 병합한다.

    그 경로에 판정이 없으면, 필터를 켠 날 화면이 그대로다 — 이미 실려 있는
    연예 기사는 새로 수집되는 것이 아니라 **이어받아지는** 것이기 때문이다.
    """
    from app import news_feed

    stored = {
        "articles": [
            {"url": "https://a", "title": "Netflix's Outer Banks Finale Shatters An IMDb Series Record",
             "seendate": "20260824T000000Z", "domain": "screenrant.com", "tags": [{"symbol": "NFLX"}]},
            {"url": "https://b", "title": "Trump's new 50% tariffs on Canadian goods",
             "seendate": "20260824T000000Z", "domain": "wcvb.com", "tags": []},
        ]
    }
    monkeypatch.setattr(news_feed.config, "GDELT_ENABLED", True)
    monkeypatch.setattr(news_feed.store, "load_report", lambda *_a, **_k: stored)
    saved: dict = {}
    monkeypatch.setattr(news_feed.store, "save_report", lambda _key, payload: saved.update(payload))

    class _Silent:
        def fetch_latest_gkg_titles(self):
            return []

    news_feed.refresh(_Silent())

    kept = [article["url"] for article in saved["articles"]]
    assert kept == ["https://b"], "저장돼 있던 연예 기사가 그대로 살아남았다"


def test_the_admission_rule_has_one_definition():
    """수집 경로와 이어받기 경로가 같은 함수를 부른다."""
    import inspect

    from app import news_feed

    source = inspect.getsource(news_feed.refresh)
    assert source.count("admits(") == 2, "두 경로 중 하나가 자기만의 판정을 쓴다"
