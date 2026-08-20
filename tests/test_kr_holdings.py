"""대량보유(5% 룰) 전체 보고자 lane.

고정하는 것: kr_pension의 한 크롤이 두 blob을 만들고(국민연금 필터 전의 전체
보고자가 여기 담긴다), 요청 경로는 저장소만 읽으며, 피드에는 신규 진입·
보유목적 변경·큰 변동만 올라가고 국민연금 행은 중복 탑재되지 않는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config, kr_holdings, kr_overnight, kr_pension, signal_feed
from app.main import app
from tests.test_kr_pension import TODAY, FixtureProvider, _holding_row, _index_row


@pytest.fixture(autouse=True)
def quiet_index_move(monkeypatch):
    monkeypatch.setattr(
        kr_overnight, "build_kr_overnight",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in tests")),
    )


def _crawl(db):
    """국민연금 1 + 비연금 3(신규·목적변경·소폭변동) 창을 한 번 걷는다."""
    provider = FixtureProvider(
        index_rows=[
            _index_row(),  # 국민연금 — pension blob의 몫
            _index_row(rcept_no="20260817000001", rcept_dt="20260817",
                       corp_code="00126380", corp_name="삼성전자", stock_code="005930",
                       flr_nm="얼라인파트너스"),
            _index_row(rcept_no="20260816000002", rcept_dt="20260816",
                       corp_code="00164742", corp_name="현대자동차", stock_code="005380",
                       flr_nm="BlackRockFundAdvisors"),
            _index_row(rcept_no="20260815000003", rcept_dt="20260815",
                       corp_code="00877059", corp_name="삼성바이오로직스", stock_code="207940",
                       flr_nm="미래에셋자산운용"),
        ],
        holdings_by_corp={
            "00413046": [_holding_row()],
            "00126380": [_holding_row(rcept_no="20260817000001", report_type="신규",
                                      reporter="얼라인파트너스", ratio=5.02,
                                      ratio_change=None, reason="주식등의 대량취득")],
            "00164742": [_holding_row(rcept_no="20260816000002", report_type="변동",
                                      reporter="BlackRockFundAdvisors", ratio=6.11,
                                      ratio_change=-2.5, reason="보유목적 변경")],
            "00877059": [_holding_row(rcept_no="20260815000003", report_type="변동",
                                      reporter="미래에셋자산운용", ratio=5.5,
                                      ratio_change=1.04, reason="단순추가취득/처분")],
        },
    )
    return kr_pension.refresh(provider, today=TODAY)


@pytest.fixture
def dart_lane(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "k")


def test_one_crawl_fills_both_blobs(db, dart_lane):
    stats = _crawl(db)
    assert stats["filings"] == 1      # pension: 국민연금만
    assert stats["holdings"] == 4     # holdings: 전체 보고자

    holdings = kr_holdings.get_holdings()
    reporters = {f["reporter"] for f in holdings["filings"]}
    assert "국민연금공단" in reporters and "얼라인파트너스" in reporters
    assert holdings["filings"][0]["rcept_no"] == "20260817000001"  # 최신 우선
    assert kr_pension.get_filings()["count"] == 1  # pension blob은 그대로


def test_route_serves_the_store_and_fails_closed(db, dart_lane):
    client = TestClient(app)
    assert client.get("/api/kr/holdings").status_code == 503  # 첫 배치 전

    _crawl(db)
    ok = client.get("/api/kr/holdings")
    assert ok.status_code == 200
    assert ok.json()["count"] == 4
    assert ok.headers["cache-control"] == "public, max-age=300"


def test_gate_closed_reads_as_503(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", False)
    response = TestClient(app).get("/api/kr/holdings")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


def test_feed_curates_signal_not_noise(db, dart_lane):
    _crawl(db)
    feed = signal_feed.build_feed(today=TODAY)
    rows = [i for i in feed["items"] if i["kind"] == "kr_holdings"]

    titles = [r["title"]["ko"] for r in rows]
    # 신규 진입과 보유목적 변경(±2%p 이상 변동 겸)은 올라간다.
    assert any("얼라인파트너스" in t for t in titles)
    assert any("BlackRockFundAdvisors" in t and "-2.50%p" in t for t in titles)
    # 소폭 변동(+1.04%p 단순취득)은 표에만 있고 피드에는 없다.
    assert not any("미래에셋" in t for t in titles)
    # 국민연금 행은 kr_pension 소스의 몫 — 여기로 중복 탑재하지 않는다.
    assert not any("국민연금" in t for t in titles)
    assert all(r["region"] == "kr" for r in rows)
    assert rows[0]["hub"] == "/stock/005930"
