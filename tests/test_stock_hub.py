"""종목 허브 페이지와 종목 사이트맵.

고정하는 것: 서버가 종목별 타이틀·메타를 치환해 렌더하고(네이버 크롤러는
JS를 실행하지 않는다), 모르는 심볼은 404이며(쓰레기 URL 색인 방지), 이름의
HTML은 이스케이프되고, 사이트맵 인덱스가 정적 페이지와 동적 종목 목록을
모두 가리킨다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import store
from app.main import app


def _seed(db):
    store.save_kr_listings(
        [{"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
          "clpr": 268500.0, "flt_rt": -2.19, "mrkt_tot_amt": 1.6e15}],
        "20260818",
    )
    store.save_insider_filings(
        "AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq",
        filings_seen=1, transactions=[],
    )


def test_kr_hub_renders_server_side_title(db):
    _seed(db)
    response = TestClient(app).get("/stock/005930")

    assert response.status_code == 200
    body = response.text
    assert "<title>삼성전자 (005930) 주가·재무·내부자 공시 | 물밑 Mulmit</title>" in body
    assert 'canonical" href="https://mulmit.com/stock/005930"' in body
    assert "KOSPI" in body


def test_us_hub_renders_company_name(db):
    _seed(db)
    response = TestClient(app).get("/stock/AAPL")

    assert response.status_code == 200
    assert "<title>Apple Inc. (AAPL) financials, insiders &amp; 8-K | 물밑 Mulmit</title>" in response.text


def test_unknown_symbols_are_404_not_infinite_pages(db):
    _seed(db)
    client = TestClient(app)
    assert client.get("/stock/999999").status_code == 404      # 로스터 밖 국내 코드
    assert client.get("/stock/ZZZZ").status_code == 404        # 미수집 미국 티커
    assert client.get("/stock/;drop").status_code == 404       # 형식 불량


def test_listing_names_are_html_escaped(db):
    store.save_kr_listings(
        [{"srtn_cd": "000001", "itms_nm": "<script>x</script>", "mrkt_ctg": "KOSPI",
          "clpr": 100.0, "flt_rt": 0.0, "mrkt_tot_amt": 1.0}],
        "20260818",
    )
    body = TestClient(app).get("/stock/000001").text
    assert "<script>x</script>" not in body
    assert "&lt;script&gt;" in body


def test_sitemap_index_and_stock_urls(db):
    _seed(db)
    client = TestClient(app)

    index = client.get("/sitemap.xml")
    assert "sitemap-pages.xml" in index.text
    assert "sitemap-stocks.xml" in index.text

    pages = client.get("/sitemap-pages.xml")
    assert "https://mulmit.com/kr" in pages.text

    stocks = client.get("/sitemap-stocks.xml")
    assert stocks.status_code == 200
    assert "https://mulmit.com/stock/AAPL" in stocks.text
    # 국내는 **값이 있는 종목만** 올린다. 005930은 로스터에만 있고 저장된 종가가
    # 없으므로 빠진다 — 빈 페이지를 광고하지 않는다(2026-08-24 판정, §사이트맵).
    assert "https://mulmit.com/stock/005930" not in stocks.text


def test_the_sitemap_carries_only_stocks_that_have_something_to_show(db):
    """빈 페이지를 3,000개 올리면 색인이 안 되는 데서 끝나지 않는다.

    2026-08-24 실측: 국내 로스터 2,873종목 중 저장된 종가가 있는 것이 19개였다.
    나머지는 방문할 때 그 자리에서 모으는 구조라 크롤러가 볼 때 비어 있다.
    좁힌다고 페이지가 사라지지는 않는다 — 사람이 찾아오면 그때 수집한다.
    """
    import datetime as dt

    from app.kr_stocks import stock_series_spec

    _seed(db)
    store.save_kr_listings(
        [{"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
          "clpr": 268500.0, "flt_rt": -2.19, "mrkt_tot_amt": 1.6e15},
         {"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
          "clpr": 1593000.0, "flt_rt": -0.5, "mrkt_tot_amt": 1.1e15}],
        "20260818",
    )
    spec = stock_series_spec("000660", "SK하이닉스")
    store.save_economic_series(
        spec.series_key, provider_id="fsc", provider_series_id="000660",
        metadata_fields={"title": "SK하이닉스", "units": "KRW", "units_short": "원",
                         "frequency": "Daily", "frequency_short": "D"},
        observations=[(dt.date(2026, 8, 20), 1_593_000.0)],
        publisher="금융위원회", publisher_url="https://www.fsc.go.kr/",
        series_url="https://www.data.go.kr/data/15094808/openapi.do",
        rights_status="approved",
    )

    body = TestClient(app).get("/sitemap-stocks.xml").text
    assert "https://mulmit.com/stock/000660" in body, "값이 있는 종목은 올린다"
    assert "https://mulmit.com/stock/005930" not in body, "값이 없는 종목은 안 올린다"
