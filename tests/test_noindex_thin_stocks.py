"""값이 없는 종목 페이지는 색인 대기열에서 뺀다 (2026-08-27).

왜. Search Console 실측:

    발견했으나 색인 안 됨   2,954
    색인됨                      5

그리고 서버 실측:

    KRX 상장목록   2,875   ← 전부 /stock/{코드}가 200을 낸다
    시세 있음        320   ← 사이트맵이 광고하는 것
    시세 없음      2,555   ← 구글 대기열의 89%

크롤 예산의 대부분이 우리가 스스로 "올릴 값이 없다"고 판단한 페이지에 쓰이고
있었다. 응답 속도를 60배 올린 것(#267)과 방향이 같다 — 같은 예산으로 더 많은
**진짜** 페이지를 가져가게 한다. 속도만 고치고 대기열을 그대로 두면 빨라진
만큼 빈 페이지를 더 빨리 훑을 뿐이다.

404로 막지 않는다. 그 페이지들은 고장 난 것이 아니다 — 종목은 실재하고
이름·시장 구분은 나온다. 값이 아직 없을 뿐이다.

이 파일이 지키는 것은 하나다: **사이트맵과 색인 판정이 절대 어긋나지 않는다.**
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import covered_pages, store
from app.kr_stocks import stock_series_spec
from app.main import app


@pytest.fixture
def two_stocks(db):
    """하나는 시세가 있고 하나는 없다 — 로스터에는 둘 다 있다."""
    store.save_kr_listings(
        [
            {"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
             "clpr": 1.0, "flt_rt": 0.0, "mrkt_tot_amt": 2.0},
            {"srtn_cd": "000111", "itms_nm": "값없는종목", "mrkt_ctg": "KOSPI",
             "clpr": 1.0, "flt_rt": 0.0, "mrkt_tot_amt": 1.0},
        ],
        "20260826",
    )
    spec = stock_series_spec("000660", "SK하이닉스")
    store.save_economic_series(
        spec.series_key, provider_id="fsc", provider_series_id="000660",
        metadata_fields={"title": "SK하이닉스", "units": "KRW", "units_short": "원",
                         "frequency": "Daily", "frequency_short": "D"},
        observations=[(dt.date(2026, 8, 25), 1.0), (dt.date(2026, 8, 26), 1.1)],
        publisher="금융위원회", publisher_url="https://www.fsc.go.kr/",
        series_url="https://www.data.go.kr/data/15094808/openapi.do",
        rights_status="approved",
    )
    return TestClient(app)


def test_a_stock_with_values_is_indexable(two_stocks) -> None:
    """값이 있으면 막지 않는다 — 이 페이지들이 색인돼야 할 것들이다."""
    page = two_stocks.get("/stock/000660").text
    assert "noindex" not in page, "값이 있는 종목을 색인에서 뺐다"


def test_a_stock_without_values_is_not_indexable(two_stocks) -> None:
    """값이 없으면 대기열에서 뺀다. 사람에게는 그대로 보인다."""
    response = two_stocks.get("/stock/000111")
    assert response.status_code == 200, "404가 아니다 — 종목은 실재한다"
    assert 'content="noindex,follow"' in response.text, "빈 페이지가 색인 대기열에 남는다"
    assert "값없는종목" in response.text, "사람이 볼 내용까지 지우면 안 된다"


def test_follow_is_kept_so_links_still_carry(two_stocks) -> None:
    """`nofollow`까지 걸면 이 페이지를 지나는 링크가 끊긴다.

    종목 페이지에는 대시보드·용어 사전으로 가는 링크가 있다. 색인만 막고
    링크는 살린다.
    """
    page = two_stocks.get("/stock/000111").text
    assert "nofollow" not in page


def test_the_sitemap_and_the_index_rule_can_never_disagree(two_stocks) -> None:
    """둘이 따로 판단하면 어긋난다 — 사이트맵은 광고하는데 페이지는 색인을 막는다.

    그래서 같은 함수를 쓴다. 이 테스트가 그 사실을 고정한다.
    """
    listed = {url.rsplit("/", 1)[-1] for url in covered_pages.urls() if "/stock/" in url}
    assert "000660" in listed, "값이 있는 종목이 사이트맵에 없다"
    assert "000111" not in listed, "값이 없는 종목이 사이트맵에 올랐다"

    for code in listed:
        assert covered_pages.is_covered(code, korean=code.isdigit()), (
            f"사이트맵에 올렸는데 색인 판정은 False다: {code}"
        )
    assert not covered_pages.is_covered("000111", korean=True)


def test_the_route_asks_the_shared_rule(two_stocks) -> None:
    """규칙이 호출부에 없으면 위 테스트들이 우연히 통과할 수 있다."""
    import inspect

    from app import main

    source = inspect.getsource(main.stock_hub)
    assert "covered_pages.is_covered(" in source, (
        "라우트가 사이트맵과 다른 기준으로 색인을 판정하고 있다"
    )
