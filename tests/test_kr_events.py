"""주요사항보고 공시 속보 피드.

고정하는 것: 상장사(Y·K)만 남고 비상장·기타법인은 걸러지며, rcept_no로
중복이 제거되고 최신순으로 잘린다. 제목은 공시 원문 제목 그대로다. web은
저장된 결과만 읽고, 첫 배치 전에는 503으로 답한다.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, kr_events
from app.main import app


class FixtureDart:
    def __init__(self, rows, truncated=False):
        self.rows = rows
        self.truncated = truncated
        self.calls = []

    def fetch_filing_index(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows, self.truncated


ROWS = [
    {"rcept_no": "20260819000111", "rcept_dt": "20260819", "corp_name": "삼성전자",
     "corp_code": "00126380", "stock_code": "005930", "corp_cls": "Y", "flr_nm": "삼성전자",
     "report_nm": "주요사항보고서(자기주식취득결정)"},
    {"rcept_no": "20260819000222", "rcept_dt": "20260819", "corp_name": "코스닥회사",
     "corp_code": "11111111", "stock_code": "123456", "corp_cls": "K", "flr_nm": "코스닥회사",
     "report_nm": "주요사항보고서(유상증자결정)"},
    # 비상장 기타법인은 종목 맥락이 없어 걸러진다.
    {"rcept_no": "20260819000333", "rcept_dt": "20260819", "corp_name": "비상장",
     "corp_code": "22222222", "stock_code": "", "corp_cls": "E", "flr_nm": "비상장",
     "report_nm": "주요사항보고서(해산사유발생)"},
    # 같은 rcept_no 중복은 한 번만.
    {"rcept_no": "20260819000111", "rcept_dt": "20260819", "corp_name": "삼성전자",
     "corp_code": "00126380", "stock_code": "005930", "corp_cls": "Y", "flr_nm": "삼성전자",
     "report_nm": "주요사항보고서(자기주식취득결정)"},
    {"rcept_no": "20260818000444", "rcept_dt": "20260818", "corp_name": "어제회사",
     "corp_code": "33333333", "stock_code": "654321", "corp_cls": "Y", "flr_nm": "어제회사",
     "report_nm": "주요사항보고서(소송등의제기)"},
]


@pytest.fixture
def dart(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "k" * 40)


def test_refresh_keeps_listed_filings_newest_first(dart):
    provider = FixtureDart(ROWS)
    result = kr_events.refresh(provider, today=dt.date(2026, 8, 19))

    assert result == {"events": 3, "total_in_window": 3, "truncated": False}
    assert provider.calls[0]["broad_type"] == "B"

    payload = kr_events.get_events()
    assert [event["rcept_no"] for event in payload["events"]] == [
        "20260819000222", "20260819000111", "20260818000444",
    ]
    first = payload["events"][1]
    assert first["company"] == "삼성전자"
    assert first["report_name"] == "주요사항보고서(자기주식취득결정)"
    assert first["market"] == {"ko": "유가증권", "en": "KOSPI"}
    assert first["url"].endswith("20260819000111")
    assert "실시간 속보가 아닙니다" in payload["basis_ko"]


def test_route_serves_stored_feed_and_503s_before_first_batch(dart):
    client = TestClient(app)

    empty = client.get("/api/kr/events")
    assert empty.status_code == 503  # 첫 배치 전

    kr_events.refresh(FixtureDart(ROWS), today=dt.date(2026, 8, 19))
    ok = client.get("/api/kr/events")
    assert ok.status_code == 200
    assert ok.json()["count"] == 3
    assert ok.headers["X-Data-Source"] == "FSS DART"


def test_gate_closed_reads_as_503(db):
    response = TestClient(app).get("/api/kr/events")
    assert response.status_code == 503


def test_ingest_respects_its_own_fresh_window(dart, monkeypatch):
    kr_events.refresh(FixtureDart(ROWS), today=dt.date(2026, 8, 19))
    from app import ingest

    monkeypatch.setattr(
        ingest, "kr_events",
        type("M", (), {"CACHE_KEY": kr_events.CACHE_KEY, "refresh": lambda: pytest.fail("must not refetch")}),
    )
    assert ingest.refresh_kr_events()["skipped"] == "fresh"
