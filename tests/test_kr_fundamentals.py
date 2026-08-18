"""국내 연간 재무제표 — DART 주요계정 lane.

무엇을 고정하는가: 연결(CFS)을 우선하고 사용한 재무제표·계정명을 응답에 남긴다,
한 응답의 3개년이 사업연도 행으로 펴지고 두 요청이 이어 붙는다, 금융사 계정명
사다리(영업수익)가 동작한다, 마진은 같은 보고서 두 값의 나눗셈뿐이다, 최신
연도에 보고서가 없으면 한 해 전으로 물러난다, 게이트는 fail-closed다.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app import config, kr_fundamentals
from app.main import app
from app.providers.dart import DartProvider

THIS_YEAR = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).year
BASE = THIS_YEAR - 1  # 서비스가 먼저 시도하는 최신 사업연도


@pytest.fixture
def dart_lane(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "test-key")
    kr_fundamentals._recent_failures.clear()


def _seed_mapping(db):
    db.save_dart_corp_codes([
        {"stock_code": "005930", "corp_code": "00126380", "corp_name": "삼성전자"},
    ])


def _acct(fs_div, sj_div, name, cur, prev, prev2, rcept="20260311000001"):
    return {"fs_div": fs_div, "sj_div": sj_div, "account_nm": name,
            "thstrm_amount": cur, "frmtrm_amount": prev, "bfefrmtrm_amount": prev2,
            "currency": "KRW", "rcept_no": rcept}


def _standard_rows(scale=1.0):
    return [
        _acct("CFS", "IS", "매출액", 300 * scale, 290 * scale, 280 * scale),
        _acct("CFS", "IS", "영업이익", 45 * scale, 40 * scale, 35 * scale),
        _acct("CFS", "IS", "당기순이익(손실)", 30 * scale, 28 * scale, 26 * scale),
        _acct("CFS", "BS", "자산총계", 500 * scale, 480 * scale, 460 * scale),
        _acct("CFS", "BS", "자본총계", 350 * scale, 340 * scale, 330 * scale),
        # 별도도 같이 오지만 연결이 이겨야 한다.
        _acct("OFS", "IS", "매출액", 1, 1, 1),
    ]


class FakeProvider:
    def __init__(self, by_year):
        self.by_year = by_year
        self.calls: list[int] = []

    def fetch_major_accounts(self, corp_code, bsns_year, *, reprt_code="11011"):
        self.calls.append(bsns_year)
        return self.by_year.get(bsns_year, [])


def test_provider_parses_comma_amounts_and_both_statements():
    body = json.dumps({"status": "000", "message": "정상", "list": [{
        "fs_div": "CFS", "sj_div": "IS", "account_nm": "매출액",
        "thstrm_amount": "333,605,938,000,000", "frmtrm_amount": "300,870,903,000,000",
        "bfefrmtrm_amount": "-", "currency": "KRW", "rcept_no": "20260311000123",
    }]}).encode("utf-8")
    provider = DartProvider("k", http_get=lambda r, t: body,
                            retries=0, request_interval=0.0, sleep=lambda _s: None)

    rows = provider.fetch_major_accounts("00126380", 2025)

    assert rows[0]["thstrm_amount"] == 333_605_938_000_000
    assert rows[0]["bfefrmtrm_amount"] is None  # "-"는 0이 아니라 결측


def test_two_requests_become_five_consolidated_years(db, dart_lane, monkeypatch):
    _seed_mapping(db)
    provider = FakeProvider({BASE: _standard_rows(), BASE - 3: _standard_rows(0.5)})
    monkeypatch.setattr(kr_fundamentals, "_provider", lambda: provider)

    payload = kr_fundamentals.get_report("005930")

    assert provider.calls == [BASE, BASE - 3]
    years = [row["year"] for row in payload["annual"]]
    assert years == [BASE, BASE - 1, BASE - 2, BASE - 3, BASE - 4]
    top = payload["annual"][0]
    assert top["fs_div"] == "CFS"
    assert top["revenue"] == 300
    assert top["operating_margin"] == 15.0
    assert top["net_margin"] == 10.0
    assert payload["statement"] == "연결재무제표"
    # 겹치는 연도(BASE-3)는 첫 요청분이 이긴다 — scale 1.0의 전전기가 아니라
    # 두 번째 요청의 당기인데, 첫 응답엔 BASE-3이 없으므로 두 번째 값이 들어간다.
    assert payload["annual"][3]["revenue"] == 150


def test_financial_firms_use_the_operating_revenue_ladder(db, dart_lane, monkeypatch):
    _seed_mapping(db)
    rows = [
        _acct("CFS", "IS", "영업수익", 100, 90, 80),
        _acct("CFS", "IS", "당기순이익", 20, 18, 16),
        _acct("CFS", "BS", "자산총계", 900, 880, 860),
    ]
    provider = FakeProvider({BASE: rows})
    monkeypatch.setattr(kr_fundamentals, "_provider", lambda: provider)

    payload = kr_fundamentals.get_report("005930")

    top = payload["annual"][0]
    assert top["revenue"] == 100
    assert top["revenue_account"] == "영업수익"
    assert top["operating_income"] is None  # 없는 계정은 만들지 않는다
    assert top["net_margin"] == 20.0


def test_a_missing_latest_year_falls_back_one_year(db, dart_lane, monkeypatch):
    _seed_mapping(db)
    provider = FakeProvider({BASE - 1: _standard_rows(), BASE - 4: []})
    monkeypatch.setattr(kr_fundamentals, "_provider", lambda: provider)

    payload = kr_fundamentals.get_report("005930")

    assert provider.calls == [BASE, BASE - 1, BASE - 4]
    assert payload["annual"][0]["year"] == BASE - 1


def test_the_cache_prevents_refetching(db, dart_lane, monkeypatch):
    _seed_mapping(db)
    provider = FakeProvider({BASE: _standard_rows()})
    monkeypatch.setattr(kr_fundamentals, "_provider", lambda: provider)

    client = TestClient(app)
    first = client.get("/api/kr/fundamentals/005930")
    second = client.get("/api/kr/fundamentals/005930")

    assert first.status_code == second.status_code == 200
    assert provider.calls == [BASE, BASE - 3]
    assert second.json()["company"] == "삼성전자"


def test_the_lane_fails_closed_and_unknown_codes_are_404(db, dart_lane, monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(config, "DART_ENABLED", False)
    response = client.get("/api/kr/fundamentals/005930")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_fundamentals_disabled"
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(config, "DART_ENABLED", True)
    _seed_mapping(db)
    monkeypatch.setattr(kr_fundamentals, "_provider",
                        lambda: pytest.fail("no fetch for an unknown code"))
    response = client.get("/api/kr/fundamentals/999999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "kr_fundamentals_unknown"
