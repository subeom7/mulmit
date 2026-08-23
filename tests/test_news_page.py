"""전용 신호 피드 `/news`.

이 페이지를 만드는 이유의 절반이 색인이다. 그래서 검증할 것은 "200이 나온다"가
아니라 **본문이 HTML 안에 있다**는 것이다 — 크롤러는 JS를 실행하지 않는다.
`/glossary`와 같은 이유로 같은 것을 지킨다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import config, news_page, signal_feed
from app.main import app

STATIC = Path(config.STATIC_DIR)


def _page() -> str:
    response = TestClient(app).get("/news")
    assert response.status_code == 200
    return response.text


def test_the_body_is_in_the_html_not_fetched_by_script():
    page = _page()
    assert "{{" not in page, "치환되지 않은 자리표시자가 남았다"
    # 목록 자리는 서버가 채운다. 비어 있어도 그 사실이 HTML에 있어야 한다.
    assert 'id="news-list"' in page
    assert "news-row" in page or "news-empty" in page


def test_items_carry_their_source_and_a_link_to_the_record():
    """한 줄마다 어디서 왔는지가 붙는다. 그게 이 사이트가 뉴스를 다루는 방식이다."""
    rendered = news_page.render()
    body = rendered["ITEMS"]
    if "news-empty" in body:
        return  # 수집 전이면 검증할 항목이 없다
    for row in re.findall(r'<li class="news-row".*?</li>', body, re.S):
        assert 'class="feed-kind' in row, "종류 배지가 없다"
        assert "<time" in row, "시각이 없다"


def test_an_item_without_a_record_is_not_dressed_as_a_link():
    """원문이 없으면 링크로 만들지 않는다.

    빈 href는 눌리기만 하고 아무 데도 가지 않는다 — 링크처럼 보이는 것이
    링크가 아닌 상태다.
    """
    html = news_page._item_html(
        {"kind": "news", "region": "us", "title": {"ko": "제목", "en": "Title"}, "url": ""}
    )
    assert "<a " not in html.split('class="news-title"')[1].split("</p>")[0]


def test_the_page_asks_for_more_than_the_home_widget():
    """홈은 30건 요약, 이 페이지는 더 길다. 한도가 한 곳에 묶여 있으면 안 된다."""
    assert news_page.PAGE_ITEMS > signal_feed.MAX_ITEMS


def test_the_feed_limit_is_the_callers_choice():
    assert signal_feed.build_feed(limit=3)["count"] <= 3


def test_structured_data_names_the_page_without_republishing_the_items():
    """항목의 원문은 남의 것이다. 구조화 데이터에 본문을 싣지 않는다."""
    payload = json.loads(news_page.json_ld().replace("<" + chr(92) + "/", "</"))
    assert payload["@type"] == "CollectionPage"
    assert payload["url"].endswith("/news")
    assert "hasPart" not in payload and "itemListElement" not in payload


def test_the_page_is_reachable_and_listed():
    """고아 페이지가 되면 크롤러가 못 찾는다."""
    client = TestClient(app)
    assert "https://mulmit.com/news" in client.get("/sitemap-pages.xml").text
    linked = [
        page.name for page in STATIC.glob("*.html")
        if 'href="/news"' in page.read_text(encoding="utf-8")
    ]
    assert len(linked) >= 5, f"푸터 링크가 너무 적다: {linked}"


def test_the_kind_labels_match_the_screen():
    """같은 항목을 홈 피드와 이 페이지가 다르게 부르면 안 된다."""
    monitor = (STATIC / "monitor.js").read_text(encoding="utf-8")
    block = monitor[monitor.index("const FEED_KIND = {"):]
    block = block[: block.index("\n};")]
    on_screen = set(re.findall(r"^\s{2}(\w+):", block, re.M))
    assert on_screen, "FEED_KIND 추출이 깨졌다"
    assert on_screen <= set(news_page.KIND_LABELS), (
        f"화면에는 있는데 /news가 모르는 종류: {sorted(on_screen - set(news_page.KIND_LABELS))}"
    )
