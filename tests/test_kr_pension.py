"""국민연금 대량보유(5%) 공시 — DART lane의 배치 경로.

무엇을 고정하는가: 공시검색은 전 페이지를 걷고 잘리면 그 사실을 알린다,
제출인 필터는 국민연금 제출분만 남긴다, 상세는 rcept_no로 조인되며 실패분은
null로 남는다("-"도 0이 아니라 null), 요청 경로는 저장소만 읽는다, 게이트는
키와 함께 fail-closed다.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app import config, ingest, kr_pension
from app.main import app
from app.providers.base import DataUnavailable, RateLimited
from app.providers.dart import DartProvider

TODAY = dt.date(2026, 8, 18)


@pytest.fixture
def dart_lane(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "test-key")


def _index_row(**overrides):
    row = {
        "rcept_no": "20260803000450", "rcept_dt": "20260803",
        "corp_code": "00413046", "corp_name": "셀트리온", "stock_code": "068270",
        "corp_cls": "Y", "report_nm": "주식등의대량보유상황보고서(약식)",
        "flr_nm": "국민연금공단",
    }
    row.update(overrides)
    return row


def _holding_row(**overrides):
    row = {
        "rcept_no": "20260803000450", "report_date": "2026-08-03",
        "report_type": "약식", "reporter": "국민연금공단",
        "shares": 16926095, "shares_change": 3391598,
        "ratio": 7.28, "ratio_change": 1.04,
        "reason": "단순추가취득/처분",
        "report_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260803000450",
    }
    row.update(overrides)
    return row


class FixtureProvider:
    """fetch_filing_index/fetch_major_holdings만 아는 대역."""

    def __init__(self, index_rows, holdings_by_corp=None, truncated=False):
        self.index_rows = index_rows
        self.holdings = holdings_by_corp or {}
        self.truncated = truncated
        self.index_calls: list[tuple] = []
        self.detail_calls: list[str] = []

    def fetch_filing_index(self, *, detail_type, bgn_de, end_de, max_pages=60):
        self.index_calls.append((detail_type, bgn_de, end_de))
        return list(self.index_rows), self.truncated

    def fetch_major_holdings(self, corp_code):
        self.detail_calls.append(corp_code)
        result = self.holdings.get(corp_code)
        if isinstance(result, Exception):
            raise result
        return result or []


# --- provider ---------------------------------------------------------------


def _pages_http_get(pages):
    def http_get(request, timeout):
        url = request.full_url
        page = int(url.split("page_no=")[1].split("&")[0])
        return json.dumps(pages[page - 1]).encode("utf-8")
    return http_get


def test_provider_walks_every_index_page():
    pages = [
        {"status": "000", "message": "정상", "total_page": 2,
         "list": [{"rcept_no": "2", "rcept_dt": "20260803", "flr_nm": "국민연금공단"}]},
        {"status": "000", "message": "정상", "total_page": 2,
         "list": [{"rcept_no": "1", "rcept_dt": "20260701", "flr_nm": "BlackRock"}]},
    ]
    provider = DartProvider("k", http_get=_pages_http_get(pages),
                            retries=0, request_interval=0.0, sleep=lambda _s: None)

    rows, truncated = provider.fetch_filing_index(
        detail_type="D001", bgn_de="20260520", end_de="20260818")

    assert [row["rcept_no"] for row in rows] == ["2", "1"]
    assert truncated is False


def test_provider_reports_truncation_at_the_page_cap():
    pages = [{"status": "000", "message": "정상", "total_page": 9,
              "list": [{"rcept_no": "9", "rcept_dt": "20260803", "flr_nm": "국민연금공단"}]}]
    provider = DartProvider("k", http_get=_pages_http_get(pages * 9),
                            retries=0, request_interval=0.0, sleep=lambda _s: None)

    rows, truncated = provider.fetch_filing_index(
        detail_type="D001", bgn_de="20260520", end_de="20260818", max_pages=1)

    assert len(rows) == 1
    assert truncated is True


def test_provider_relays_majorstock_dash_as_null_not_zero():
    body = json.dumps({"status": "000", "message": "정상", "list": [{
        "rcept_no": "20260803000450", "rcept_dt": "2026-08-03", "report_tp": "약식",
        "repror": "국민연금공단", "stkqy": "16,926,095", "stkqy_irds": "-",
        "stkrt": "7.28", "stkrt_irds": "-", "report_resn": "단순추가취득/처분",
    }]}).encode("utf-8")
    provider = DartProvider("k", http_get=lambda r, t: body,
                            retries=0, request_interval=0.0, sleep=lambda _s: None)

    rows = provider.fetch_major_holdings("00413046")

    assert rows[0]["shares"] == 16926095
    assert rows[0]["shares_change"] is None
    assert rows[0]["ratio"] == 7.28
    assert rows[0]["ratio_change"] is None


# --- refresh ----------------------------------------------------------------


def test_refresh_keeps_only_nps_filings_and_joins_details(db, dart_lane):
    provider = FixtureProvider(
        index_rows=[
            _index_row(),
            _index_row(rcept_no="20260801000111", rcept_dt="20260801",
                       corp_code="00126380", corp_name="삼성전자", stock_code="005930",
                       flr_nm="BlackRockFundAdvisors"),
        ],
        holdings_by_corp={"00413046": [_holding_row()]},
    )

    stats = kr_pension.refresh(provider, today=TODAY)

    assert stats == {"filings": 1, "total_in_window": 1, "detail_failed": 0, "truncated": False}
    assert provider.index_calls == [("D001", "20260520", "20260818")]
    assert provider.detail_calls == ["00413046"]

    payload = kr_pension.get_filings()
    filing = payload["filings"][0]
    assert filing["company"] == "셀트리온"
    assert filing["report_date"] == "2026-08-03"
    assert filing["ratio"] == 7.28
    assert filing["ratio_change"] == 1.04
    assert filing["shares_change"] == 3391598
    assert filing["reason"] == "단순추가취득/처분"
    assert filing["market"] == {"ko": "유가증권", "en": "KOSPI"}
    assert filing["detail_status"] == "ok"
    assert payload["window"] == {
        "from": "2026-05-20", "to": "2026-08-18", "days": 90, "truncated": False}
    assert payload["source"]["provider"] == "dart"


def test_refresh_sorts_newest_first_and_caps_the_list(db, dart_lane, monkeypatch):
    monkeypatch.setattr(kr_pension, "MAX_FILINGS", 2)
    provider = FixtureProvider(index_rows=[
        _index_row(rcept_no="20260601000001", rcept_dt="20260601"),
        _index_row(rcept_no="20260803000450", rcept_dt="20260803"),
        _index_row(rcept_no="20260701000599", rcept_dt="20260701"),
    ])

    stats = kr_pension.refresh(provider, today=TODAY)

    assert stats["filings"] == 2
    assert stats["total_in_window"] == 3
    payload = kr_pension.get_filings()
    assert [f["rcept_no"] for f in payload["filings"]] == [
        "20260803000450", "20260701000599"]
    # 상세는 표시분의 회사당 한 번이다.
    assert provider.detail_calls == ["00413046"]


def test_a_failed_detail_leaves_numbers_null_never_invented(db, dart_lane):
    provider = FixtureProvider(
        index_rows=[
            _index_row(),
            _index_row(rcept_no="20260731000384", rcept_dt="20260731",
                       corp_code="00877059", corp_name="삼성바이오로직스",
                       stock_code="207940"),
        ],
        holdings_by_corp={
            "00413046": [_holding_row()],
            "00877059": DataUnavailable("down"),
        },
    )

    stats = kr_pension.refresh(provider, today=TODAY)

    assert stats["detail_failed"] == 1
    rows = {f["rcept_no"]: f for f in kr_pension.get_filings()["filings"]}
    assert rows["20260803000450"]["ratio"] == 7.28
    failed = rows["20260731000384"]
    assert failed["ratio"] is None
    assert failed["shares"] is None
    assert failed["reason"] is None
    assert failed["detail_status"] == "unavailable"
    assert failed["report_url"].endswith("rcpNo=20260731000384")


def test_a_rate_limit_mid_details_saves_what_was_honestly_fetched(db, dart_lane):
    provider = FixtureProvider(
        index_rows=[
            _index_row(),
            _index_row(rcept_no="20260731000384", rcept_dt="20260731",
                       corp_code="00877059", corp_name="삼성바이오로직스"),
        ],
        holdings_by_corp={
            "00413046": RateLimited("throttled"),
            "00877059": [_holding_row(rcept_no="20260731000384")],
        },
    )

    kr_pension.refresh(provider, today=TODAY)

    # 첫 회사에서 허용량이 끊겼으니 남은 상세도 시도하지 않는다.
    assert provider.detail_calls == ["00413046"]
    payload = kr_pension.get_filings()
    assert all(f["detail_status"] == "unavailable" for f in payload["filings"])


# --- serving ----------------------------------------------------------------


def test_the_request_path_reads_the_store_only(db, dart_lane, monkeypatch):
    provider = FixtureProvider(index_rows=[_index_row()],
                               holdings_by_corp={"00413046": [_holding_row()]})
    kr_pension.refresh(provider, today=TODAY)
    monkeypatch.setattr(kr_pension, "_provider",
                        lambda: pytest.fail("the request path must not call DART"))

    response = TestClient(app).get("/api/kr/pension")

    assert response.status_code == 200
    body = response.json()
    assert body["filings"][0]["company"] == "셀트리온"
    assert body["reporter"] == {"ko": "국민연금공단", "en": "National Pension Service"}
    assert "국민연금공단" in body["basis_ko"]
    assert response.headers["cache-control"] == "public, max-age=300"


def test_the_route_is_503_before_the_first_batch(db, dart_lane):
    response = TestClient(app).get("/api/kr/pension")

    assert response.status_code == 503
    assert "not collected" in response.json()["detail"]


def test_the_lane_fails_closed_without_the_flag_and_without_the_key(db, monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(config, "DART_ENABLED", False)
    response = client.get("/api/kr/pension")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_pension_data_disabled"
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "")
    response = client.get("/api/kr/pension")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_pension_not_configured"


# --- ingest -----------------------------------------------------------------


def test_ingest_respects_the_gate_and_freshness(db, dart_lane, monkeypatch):
    calls = []
    monkeypatch.setattr(kr_pension, "refresh", lambda: calls.append(1) or {"filings": 0})

    monkeypatch.setattr(config, "DART_ENABLED", False)
    assert ingest.refresh_kr_pension() == {"skipped": "disabled"}
    monkeypatch.setattr(config, "DART_ENABLED", True)

    assert ingest.refresh_kr_pension() == {"filings": 0}
    assert calls == [1]

    # 신선한 결과가 있으면 배치는 다시 걷지 않는다.
    db.save_report(kr_pension.CACHE_KEY, {"filings": []})
    assert ingest.refresh_kr_pension() == {"skipped": "fresh"}
    assert calls == [1]


def test_ingest_swallows_a_rate_limit_into_a_skip(db, dart_lane, monkeypatch):
    def throttled():
        raise RateLimited("quota")

    monkeypatch.setattr(kr_pension, "refresh", throttled)

    assert ingest.refresh_kr_pension() == {"skipped": "rate_limited"}
