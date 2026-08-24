"""8-K 피드를 종목으로 좁힐 수 있어야 한다.

종목 화면은 `/api/us/events?ticker=AAPL`을 부르고 있었는데, 라우트에 그 인자가
없었다. FastAPI는 모르는 쿼리를 조용히 무시하므로 요청은 200으로 성공했고,
화면은 **커버리지 전체의 최근 8-K**를 그 종목의 공시인 것처럼 실었다.

2026-08-24 라이브 실측: 애플(CIK 320193) 화면의 첫 8-K 링크가 CIK 12927,
보잉이었다. 에러도 빈 표도 없었다 — 남의 공시가 그 자리에 있었을 뿐이고,
원문 링크를 되살리기 전까지는 그것조차 보이지 않았다.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.us_events import build_events_feed


def _seed() -> None:
    for ticker, cik, name in (
        ("AAPL", "0000320193", "Apple Inc."),
        ("BA", "0000012927", "Boeing"),
    ):
        store.save_insider_filings(
            ticker, cik=cik, name=name, exchange="NYSE", filings_seen=0, transactions=[]
        )
    for ticker, accession in (("AAPL", "a-1"), ("BA", "b-1"), ("BA", "b-2")):
        store.save_company_events(ticker, [{
            "accession_number": accession,
            "cik": "0000000001",
            "form_type": "8-K",
            "filed_at": dt.date(2026, 8, 19),
            "accepted_at": "2026-08-19T16:31:02.000Z",
            "items": "2.02",
            "url": f"https://sec.example/{accession}",
        }])


def test_a_ticker_narrows_the_feed_to_that_company(db, sec_edgar):
    _seed()
    payload = build_events_feed(ticker="AAPL")
    assert payload["count"] == 1
    assert {event["ticker"] for event in payload["events"]} == {"AAPL"}


def test_without_a_ticker_the_feed_stays_the_whole_coverage(db, sec_edgar):
    _seed()
    payload = build_events_feed()
    assert {event["ticker"] for event in payload["events"]} == {"AAPL", "BA"}


def test_the_route_actually_accepts_the_argument(db, sec_edgar):
    """이 파일의 핵심이다 — 인자를 안 받으면 조용히 무시되고 남의 공시가 실린다."""
    _seed()
    body = TestClient(app).get("/api/us/events?ticker=AAPL").json()
    assert {event["ticker"] for event in body["events"]} == {"AAPL"}


def test_the_stock_screen_filters_by_ticker() -> None:
    """화면이 서버에 티커를 넘기는지. 넘기지 않으면 위 필터가 있어도 소용없다."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "static" / "stock.html").read_text(
        encoding="utf-8"
    )
    assert '/api/us/events?ticker=" + encodeURIComponent(SYMBOL)' in source


def test_the_ptr_feed_narrows_to_the_ticker_inside_the_filing(db, monkeypatch):
    """PTR은 티커가 보고서가 아니라 **그 안의 거래**에 붙어 있다.

    그래서 두 단계로 좁힌다 — 그 종목의 거래가 든 보고서만 남기고, 보고서
    안에서도 그 종목의 거래만 남긴다. 한 단계만 하면 다른 의원의 다른 종목
    거래가 이 종목 표에 섞인다.
    """
    from app import config, us_ptr

    monkeypatch.setattr(config, "US_PTR_ENABLED", True)
    store.save_report(us_ptr.CACHE_KEY, {"filings": [
        {"doc_id": "d1", "name": "Doe, Jane", "pdf_url": "https://clerk.example/d1",
         "transaction_count": 2,
         "transactions": [{"ticker": "AAPL", "date": "2026-08-01"},
                          {"ticker": "BA", "date": "2026-08-02"}]},
        {"doc_id": "d2", "name": "Roe, Ada", "pdf_url": "https://clerk.example/d2",
         "transaction_count": 1,
         "transactions": [{"ticker": "BA", "date": "2026-08-03"}]},
    ]})

    payload = us_ptr.get_filings(ticker="AAPL")
    assert [filing["doc_id"] for filing in payload["filings"]] == ["d1"]
    assert [t["ticker"] for t in payload["filings"][0]["transactions"]] == ["AAPL"], (
        "보고서만 거르고 거래를 안 거르면 보잉 거래가 애플 표에 남는다"
    )
    assert payload["filings"][0]["transaction_count"] == 1

    assert len(us_ptr.get_filings()["filings"]) == 2, "인자가 없으면 전체 그대로"
