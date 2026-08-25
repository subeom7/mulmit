"""사이트맵에 올린 페이지로 **링크를 따라** 갈 수 있는가.

2026-08-25 Search Console:

    Discovered — currently not indexed   2,954
    Crawled — currently not indexed          2
    Indexed                                  5

"Discovered"는 **찾았지만 한 번도 가져가지 않았다**는 뜻이다. 얇아서 버린 게
아니라 아예 안 읽었다 — 실제로 크롤된 것은 두 개뿐이다.

같은 날 재 보니 크롤러가 링크로 닿을 수 있는 종목 페이지가 **42개**였다(홈 0,
`/kr` 0, `/us` 0, `/crypto` 0, `/analytics` 6, `/news` 36). 나머지는 사이트맵에만
있었다. 사이트맵에만 있는 URL은 크롤 우선순위가 가장 낮고, 새 도메인은 크롤
예산 자체가 적다.

**페이지를 두껍게 만든 것만으로는 읽히지도 않는다.** 먼저 길이 있어야 한다.
그래서 `/analytics`가 목록을 서버에서 렌더한다 — 홈에서 한 번, 거기서 한 번.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app


@pytest.fixture
def covered(db):
    import datetime as dt

    from app.kr_stocks import stock_series_spec

    store.save_kr_listings(
        [{"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
          "clpr": 1.0, "flt_rt": 0.0, "mrkt_tot_amt": 1.0}],
        "20260825",
    )
    spec = stock_series_spec("000660", "SK하이닉스")
    store.save_economic_series(
        spec.series_key, provider_id="fsc", provider_series_id="000660",
        metadata_fields={"title": "SK하이닉스", "units": "KRW", "units_short": "원",
                         "frequency": "Daily", "frequency_short": "D"},
        observations=[(dt.date(2026, 8, 24), 1.0)],
        publisher="금융위원회", publisher_url="https://www.fsc.go.kr/",
        series_url="https://www.data.go.kr/data/15094808/openapi.do",
        rights_status="approved",
    )
    store.save_insider_filings(
        "AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq",
        filings_seen=1, transactions=[],
    )
    return TestClient(app)


def _stock_links(html: str) -> set[str]:
    return set(re.findall(r'href="(/stock/[A-Za-z0-9]+)"', html))


def test_the_hub_links_to_every_covered_page(covered) -> None:
    """사이트맵에 올린 것은 사이트 안에서도 링크로 닿아야 한다."""
    html = covered.get("/analytics").text
    links = _stock_links(html)
    assert "/stock/000660" in links, "값이 있는 국내 종목은 링크가 있어야 한다"
    assert "/stock/AAPL" in links


def test_the_hub_and_the_sitemap_read_the_same_list(covered) -> None:
    """갈라지면 구글에는 있다고 말해 놓고 사이트 안에는 길이 없는 상태가 된다."""
    hub = _stock_links(covered.get("/analytics").text)
    sitemap = {
        path.replace("https://mulmit.com", "")
        for path in re.findall(r"<loc>([^<]+)</loc>", covered.get("/sitemap-stocks.xml").text)
        if "/stock/" in path
    }
    assert sitemap, "사이트맵이 비어 있으면 이 테스트가 아무것도 안 지킨다"
    assert sitemap <= hub, f"사이트맵에만 있고 링크가 없는 페이지: {sorted(sitemap - hub)}"


def test_the_links_are_plain_anchors_not_javascript(covered) -> None:
    """자바스크립트로 그리면 크롤러가 링크를 못 본다 — 길이 없는 것과 같다.

    `/kr`·`/us`의 표에 종목 링크가 있지만 전부 JS가 그린다. 그래서 크롤러가
    본 종목 링크가 0개였다(2026-08-25 실측).
    """
    html = covered.get("/analytics").text
    body = html[html.index("<body") :]
    for block in re.findall(r"(?is)<script[^>]*>.*?</script>", body):
        body = body.replace(block, "")
    assert "/stock/000660" in body, "스크립트를 걷어내도 링크가 남아 있어야 한다"


def test_a_stock_without_data_is_not_advertised(covered) -> None:
    """빈 페이지로 가는 길을 만들지 않는다 — 사이트맵과 같은 규칙이다."""
    store.save_kr_listings(
        [{"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
          "clpr": 1.0, "flt_rt": 0.0, "mrkt_tot_amt": 2.0}],
        "20260825",
    )
    links = _stock_links(covered.get("/analytics").text)
    assert "/stock/005930" not in links
