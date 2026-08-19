"""8-K 이벤트 피드.

고정하는 것: 행은 내부자 수집의 submissions 응답에서 함께 뽑혀 저장되고
(추가 요청 없음), Item 번호는 닫힌 매핑으로만 제목이 붙으며 모르는 번호는
원문 코드 그대로 나간다. 게이트가 닫히면 503, 저장이 비어도 200에 빈 목록.
"""

from __future__ import annotations

import datetime as dt
import json

from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.providers.sec_edgar import SecEdgarProvider
from app.us_events import build_events_feed


def _seed_company(ticker: str = "AAPL", name: str = "Apple Inc.") -> None:
    store.save_insider_filings(
        ticker, cik="0000320193", name=name, exchange="Nasdaq",
        filings_seen=0, transactions=[],
    )


def _seed_events(ticker: str = "AAPL") -> None:
    store.save_company_events(ticker, [
        {
            "accession_number": "0002-26-2",
            "cik": "0000320193",
            "form_type": "8-K",
            "filed_at": dt.date(2026, 8, 12),
            "accepted_at": "2026-08-12T16:31:02.000Z",
            "items": "2.02,9.01",
            "url": "https://www.sec.gov/Archives/edgar/data/320193/000226/aapl-8k.htm",
        },
        {
            "accession_number": "0002-26-9",
            "cik": "0000320193",
            "form_type": "8-K",
            "filed_at": dt.date(2026, 8, 1),
            "accepted_at": None,
            "items": "77.99",  # 매핑에 없는 번호는 코드 그대로 나가야 한다
            "url": "https://www.sec.gov/Archives/edgar/data/320193/000269/x.htm",
        },
    ])


def test_provider_extracts_events_from_the_same_submissions_payload():
    submissions = json.dumps({
        "name": "Apple Inc.",
        "filings": {"recent": {
            "form": ["4", "8-K", "8-K/A", "10-K"],
            "accessionNumber": ["0001-26-1", "0002-26-2", "0002-26-3", "0002-26-4"],
            "filingDate": ["2026-08-13", "2026-08-12", "2026-08-10", "2026-08-01"],
            "primaryDocument": ["f4.xml", "aapl-8k.htm", "aapl-8ka.htm", "aapl-10k.htm"],
            "acceptanceDateTime": ["", "2026-08-12T16:31:02.000Z", "", ""],
            "items": ["", "2.02,9.01", "8.01", ""],
        }},
    }).encode()

    calls = []

    def transport(request, timeout):
        calls.append(request.full_url)
        return submissions

    provider = SecEdgarProvider("Mulmit test admin@example.com", http_get=transport,
                                request_interval=0.0)
    company = provider.fetch_company("320193", form_limit=0)

    assert len(calls) == 1  # 이벤트 추출을 위한 추가 요청은 없다
    assert [event.accession_number for event in company.events] == ["0002-26-2", "0002-26-3"]
    first = company.events[0]
    assert first.filed_at == dt.date(2026, 8, 12)
    assert first.accepted_at == "2026-08-12T16:31:02.000Z"
    assert first.items == "2.02,9.01"
    assert first.url == "https://www.sec.gov/Archives/edgar/data/320193/0002262/aapl-8k.htm"
    # 8-K/A도 이벤트다. 10-K는 아니다.
    assert company.events[1].form_type == "8-K/A"


def test_feed_labels_items_with_the_closed_mapping(sec_edgar):
    _seed_company()
    _seed_events()

    payload = build_events_feed()

    assert payload["count"] == 2
    newest = payload["events"][0]
    assert newest["ticker"] == "AAPL"
    assert newest["company"] == "Apple Inc."
    assert [item["code"] for item in newest["items"]] == ["2.02", "9.01"]
    assert newest["items"][0]["label"]["ko"] == "실적 발표"
    unknown = payload["events"][1]["items"][0]
    assert unknown["label"] == {"en": "77.99", "ko": "77.99"}
    assert "실시간 속보가 아닙니다" in payload["basis"]["ko"]


def test_route_serves_and_gate_refuses(db, sec_edgar):
    _seed_company()
    _seed_events()
    client = TestClient(app)

    ok = client.get("/api/us/events")
    assert ok.status_code == 200
    assert ok.json()["count"] == 2
    assert ok.headers["X-Data-Source"] == "SEC EDGAR"


def test_gate_closed_reads_as_503(db):
    response = TestClient(app).get("/api/us/events")
    assert response.status_code == 503
