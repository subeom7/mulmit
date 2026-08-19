"""통합 신호 피드.

고정하는 것: 네 공시 소스가 시간순 하나로 합쳐지고(시각 있는 항목이 같은 날짜
안에서 앞에 온다), 소스 하나의 실패·부재는 그 소스만 지우며, 미래 일정은
과거 항목과 섞이지 않고 upcoming으로 분리되고, 종목 허브 링크는 형식이 맞는
심볼에만 붙는다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import kr_events, kr_overnight, kr_pension, signal_feed, store, us_ptr
from app.main import app

TODAY = dt.date(2026, 8, 19)


@pytest.fixture(autouse=True)
def quiet_index_move(monkeypatch):
    """지수 급변 소스가 테스트에서 실망 네트워크를 부르지 않게 기본 무음."""
    monkeypatch.setattr(
        kr_overnight, "build_kr_overnight",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in tests")),
    )


def _seed(db):
    store.save_insider_filings("AAPL", cik="1", name="Apple Inc.", exchange="Nasdaq",
                               filings_seen=0, transactions=[])
    store.save_company_events("AAPL", [{
        "accession_number": "a-1", "cik": "1", "form_type": "8-K",
        "filed_at": dt.date(2026, 8, 18), "accepted_at": "2026-08-18T16:31:02.000Z",
        "items": "2.02", "url": "https://sec.example/a-1",
    }])
    store.save_report(kr_events.CACHE_KEY, {"events": [{
        "rcept_no": "r1", "filed_at": "2026-08-18", "company": "삼성전자",
        "stock_code": "005930", "report_name": "주요사항보고서(자기주식취득결정)",
        "url": "https://dart.example/r1",
    }]})
    store.save_report(us_ptr.CACHE_KEY, {"filings": [{
        "doc_id": "d1", "name": "Doe, Jane", "filed_date": "2026-08-17",
        "pdf_url": "https://clerk.example/d1", "transaction_count": 2,
        "transactions": [{"ticker": "NVDA"}, {"ticker": "NVDA"}],
    }]})
    store.save_report(kr_pension.CACHE_KEY, {"filings": [{
        "rcept_no": "p1", "report_date": "2026-08-16", "company": "카카오",
        "stock_code": "035720", "ratio_change": -0.5,
        "report_url": "https://dart.example/p1",
    }]})


def test_sources_merge_newest_first_with_hub_links(db):
    _seed(db)
    feed = signal_feed.build_feed(today=TODAY)

    kinds = [item["kind"] for item in feed["items"]]
    assert kinds == ["us_8k", "kr_material", "us_ptr", "kr_pension"]
    # 같은 날짜(8/18)에서 acceptance 시각이 붙은 8-K가 날짜뿐인 항목보다 앞이다.
    assert feed["items"][0]["at"].startswith("2026-08-18T")

    first = feed["items"][0]
    assert first["hub"] == "/stock/AAPL"
    assert "실적 발표" in first["title"]["ko"]
    material = feed["items"][1]
    assert material["hub"] == "/stock/005930"
    ptr = feed["items"][2]
    assert ptr["hub"] == "/stock/NVDA"  # 단일 티커 보고라 허브가 붙는다
    assert "거래 2건" in ptr["title"]["ko"]
    assert "실시간 속보가 아니" in feed["basis_ko"]


def test_missing_sources_simply_do_not_appear(db):
    # 아무 소스도 시드하지 않았다 — 피드는 비어 있고, 예외는 없다.
    feed = signal_feed.build_feed(today=TODAY)
    assert feed["items"] == []
    assert feed["count"] == 0


def test_route_serves_and_upcoming_stays_separate(db):
    _seed(db)
    response = TestClient(app).get("/api/feed")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 4
    past_dates = {item["date"] for item in body["items"]}
    for event in body["upcoming"]:
        assert event["date"] not in past_dates or event["kind"] == "calendar"
        assert event["d_day"] >= 0


def _kro_with(percent):
    return lambda *a, **k: {"cards": [{
        "id": "kospi_200",
        "implied": {"vs_official_percent": percent},
        "official": {"date": "2026-08-18"},
    }]}


def test_index_move_records_threshold_crossings_once(db, monkeypatch):
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-5.4))
    feed = signal_feed.build_feed(today=TODAY)
    moves = [item for item in feed["items"] if item["kind"] == "index_move"]
    assert len(moves) == 1
    assert "-3% 선 이탈" in moves[0]["title"]["ko"]
    assert "-5.4%" in moves[0]["title"]["ko"]

    # 같은 구간에 머무는 동안은 이벤트가 늘지 않는다.
    feed = signal_feed.build_feed(today=TODAY)
    assert sum(1 for i in feed["items"] if i["kind"] == "index_move") == 1

    # 회복 방향의 계단 통과도 기록된다.
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-1.2))
    feed = signal_feed.build_feed(today=TODAY)
    moves = [item for item in feed["items"] if item["kind"] == "index_move"]
    assert len(moves) == 2
    assert "회복" in moves[0]["title"]["ko"]
