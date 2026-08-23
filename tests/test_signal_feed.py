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


def _seed(db, base: dt.date = TODAY):
    """씨앗은 기준일에 **상대적**으로 심는다.

    `/api/feed`는 인자를 받지 않으므로 벽시계의 오늘을 쓴다. 씨앗을 달력에 못
    박아 두면 `MAX_AGE_DAYS`(7일) 창이 하루씩 밀리면서 가장 오래된 항목부터
    조용히 빠지고, 어느 날 자정에 아무도 아무것도 안 바꿨는데 CI가 빨개진다
    (2026-08-24 실제로 그랬다). 그래서 오프셋으로 심는다.
    """
    day = lambda back: (base - dt.timedelta(days=back)).isoformat()  # noqa: E731
    store.save_insider_filings("AAPL", cik="1", name="Apple Inc.", exchange="Nasdaq",
                               filings_seen=0, transactions=[])
    store.save_company_events("AAPL", [{
        "accession_number": "a-1", "cik": "1", "form_type": "8-K",
        "filed_at": base - dt.timedelta(days=1), "accepted_at": f"{day(1)}T16:31:02.000Z",
        "items": "2.02", "url": "https://sec.example/a-1",
    }])
    store.save_report(kr_events.CACHE_KEY, {"events": [{
        "rcept_no": "r1", "filed_at": day(1), "company": "삼성전자",
        "stock_code": "005930", "report_name": "주요사항보고서(자기주식취득결정)",
        "url": "https://dart.example/r1",
    }]})
    store.save_report(us_ptr.CACHE_KEY, {"filings": [{
        "doc_id": "d1", "name": "Doe, Jane", "filed_date": day(2),
        "pdf_url": "https://clerk.example/d1", "transaction_count": 2,
        "transactions": [{"ticker": "NVDA"}, {"ticker": "NVDA"}],
    }]})
    store.save_report(kr_pension.CACHE_KEY, {"filings": [{
        "rcept_no": "p1", "report_date": day(3), "company": "카카오",
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
    # 이 하나만 라우트를 탄다 — 라우트는 `today`를 안 받으니 벽시계를 쓴다.
    _seed(db, base=dt.date.today())
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


def test_recovery_needs_hysteresis_clearance(db, monkeypatch):
    """선 위 진동은 뉴스가 아니다 — 회복은 선 안쪽 0.5%p를 확보해야 한 번 찍힌다."""
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-4.2))
    signal_feed.build_feed(today=TODAY)  # 이탈 1건

    # -2.8: 선(-3%) 위로 올라왔지만 0.5 미확보 → 이벤트 없음, 구간 유지
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-2.8))
    feed = signal_feed.build_feed(today=TODAY)
    assert sum(1 for i in feed["items"] if i["kind"] == "index_move") == 1

    # 다시 -3.1: 구간이 안 바뀐 상태였으므로 "재이탈" 이벤트도 없다
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-3.1))
    feed = signal_feed.build_feed(today=TODAY)
    assert sum(1 for i in feed["items"] if i["kind"] == "index_move") == 1

    # -2.4: 확보 → 회복 1건. 아침 4연발이 이 규칙으로 2건이 된다.
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-2.4))
    feed = signal_feed.build_feed(today=TODAY)
    moves = [i for i in feed["items"] if i["kind"] == "index_move"]
    assert len(moves) == 2
    assert "회복" in moves[0]["title"]["ko"]
    assert "-2.4%" in moves[0]["title"]["ko"]


def test_same_crossing_within_window_is_recorded_once(db, monkeypatch):
    """워커 레이스 가드: 같은 선·같은 방향이 10분 안에 겹치면 한 건이다."""
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-3.4))
    signal_feed.build_feed(today=TODAY)
    # 다른 워커가 낡은 상태(bucket=0)로 같은 이탈을 또 기록하려는 상황
    state = store.load_report(signal_feed.MOVE_STATE_KEY, 90 * 24 * 3600)
    state["bucket"] = 0
    store.save_report(signal_feed.MOVE_STATE_KEY, state)
    feed = signal_feed.build_feed(today=TODAY)
    assert sum(1 for i in feed["items"] if i["kind"] == "index_move") == 1


def test_every_item_carries_a_region(db, monkeypatch):
    monkeypatch.setattr(kr_overnight, "build_kr_overnight", _kro_with(-5.4))
    _seed(db)
    feed = signal_feed.build_feed(today=TODAY)
    regions = {i["kind"]: i["region"] for i in feed["items"]}
    assert all(r in ("kr", "us") for r in regions.values())
    for kind in [k for k in regions if k.startswith("kr_")] + ["index_move"]:
        assert regions[kind] == "kr"
    for kind in [k for k in regions if k.startswith("us_")]:
        assert regions[kind] == "us"
