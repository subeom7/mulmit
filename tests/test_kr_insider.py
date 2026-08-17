"""국내 임원·주요주주 소유보고 — DART lane.

무엇을 고정하는가: 게이트는 키와 함께 fail-closed다, 매핑에서 비상장 법인은
걸러진다, 캐시 미스는 잠금 아래 정확히 한 번 조회한다, 값은 가공 없이
전달되며 보고서 단위라는 basis가 응답에 실린다, 그리고 오류 status가 값으로
저장되지 않는다.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import config, kr_insider
from app.main import app
from app.providers.base import DataUnavailable, RateLimited
from app.providers.dart import DartAuthorizationError, DartProvider


@pytest.fixture
def dart_lane(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "test-key")
    kr_insider._recent_failures.clear()


def _corp_zip(entries) -> bytes:
    inner = "<result>" + "".join(
        f"<list><corp_code>{c}</corp_code><corp_name>{n}</corp_name>"
        f"<stock_code>{s}</stock_code><modify_date>20260101</modify_date></list>"
        for c, n, s in entries
    ) + "</result>"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", inner)
    return buffer.getvalue()


def _elestock(rows, status="000") -> bytes:
    return json.dumps({"status": status, "message": "정상", "list": rows}).encode("utf-8")


def _report_row(**overrides):
    row = {
        "rcept_no": "20260814000123", "rcept_dt": "2026-08-14", "corp_code": "00126380",
        "corp_name": "삼성전자", "repror": "박태훈", "isu_exctv_rgist_at": "비등기임원",
        "isu_exctv_ofcps": "상무", "isu_main_shrholdr": "-",
        "sp_stock_lmp_cnt": "3,501", "sp_stock_lmp_irds_cnt": "589",
        "sp_stock_lmp_rate": "0.00", "sp_stock_lmp_irds_rate": "0.00",
    }
    row.update(overrides)
    return row


def _seed_mapping(db):
    db.save_dart_corp_codes([
        {"stock_code": "005930", "corp_code": "00126380", "corp_name": "삼성전자"},
        {"stock_code": "000660", "corp_code": "00164779", "corp_name": "SK하이닉스"},
    ])


# --- provider ---------------------------------------------------------------


def test_unlisted_companies_never_enter_the_mapping():
    """corpCode.xml은 비상장 10만여 법인을 함께 담고 있다."""
    payload = _corp_zip([
        ("00126380", "삼성전자", "005930"),
        ("00999999", "비상장주식회사", " "),
    ])
    provider = DartProvider("k", http_get=lambda r, t: payload,
                            retries=0, request_interval=0.0, sleep=lambda _s: None)

    rows = provider.fetch_corp_codes()

    assert [r["stock_code"] for r in rows] == ["005930"]


def test_an_error_body_where_a_zip_should_be_is_an_error_not_a_mapping():
    body = json.dumps({"status": "020", "message": "요청 제한 초과"}).encode("utf-8")
    provider = DartProvider("k", http_get=lambda r, t: body,
                            retries=0, request_interval=0.0, sleep=lambda _s: None)

    with pytest.raises(RateLimited):
        provider.fetch_corp_codes()


def test_report_numbers_survive_commas_and_dashes():
    provider = DartProvider("k", http_get=lambda r, t: _elestock([
        _report_row(sp_stock_lmp_cnt="1,234,567", sp_stock_lmp_irds_cnt="-",
                    sp_stock_lmp_rate="12.34"),
    ]), retries=0, request_interval=0.0, sleep=lambda _s: None)

    rows = provider.fetch_ownership_reports("00126380")

    assert rows[0]["shares_owned"] == 1234567
    assert rows[0]["shares_change"] is None  # "-"는 0이 아니라 미보고다
    assert rows[0]["ownership_ratio"] == 12.34
    assert rows[0]["report_url"].endswith("rcpNo=20260814000123")


def test_a_rejected_key_is_an_authorization_error_not_empty_data():
    provider = DartProvider("k", http_get=lambda r, t: _elestock([], status="010"),
                            retries=0, request_interval=0.0, sleep=lambda _s: None)

    with pytest.raises(DartAuthorizationError):
        provider.fetch_ownership_reports("00126380")


def test_no_data_status_is_an_empty_list_not_an_error():
    provider = DartProvider("k", http_get=lambda r, t: json.dumps(
        {"status": "013", "message": "조회된 데이타가 없습니다."}).encode("utf-8"),
        retries=0, request_interval=0.0, sleep=lambda _s: None)

    assert provider.fetch_ownership_reports("00126380") == []


# --- module + route ---------------------------------------------------------


def test_reports_serve_from_cache_after_one_fetch(db, dart_lane, monkeypatch):
    _seed_mapping(db)
    calls = []

    class FakeProvider:
        def fetch_ownership_reports(self, corp_code):
            calls.append(corp_code)
            return [dict(_report_row(), rcept_no="1", report_date="2026-08-14",
                         reporter="박태훈", executive_status="비등기임원", position="상무",
                         main_shareholder="-", shares_owned=3501, shares_change=589,
                         ownership_ratio=0.0, ratio_change=0.0,
                         report_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=1")]

        def fetch_corp_codes(self):
            pytest.fail("mapping already seeded")

    monkeypatch.setattr(kr_insider, "_provider", FakeProvider)
    client = TestClient(app)

    first = client.get("/api/kr/insider/005930")
    second = client.get("/api/kr/insider/005930")

    assert first.status_code == second.status_code == 200
    assert calls == ["00126380"]
    body = second.json()
    assert body["company"] == "삼성전자"
    assert body["reports"][0]["shares_change"] == 589
    assert "보고서" in body["basis_ko"]
    assert body["source"]["provider"] == "dart"


def test_the_lane_fails_closed_without_the_flag_and_without_the_key(db, monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(config, "DART_ENABLED", False)
    response = client.get("/api/kr/insider/005930")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_insider_data_disabled"
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "")
    response = client.get("/api/kr/insider/005930")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_insider_not_configured"


def test_a_code_outside_the_mapping_is_404(db, dart_lane, monkeypatch):
    _seed_mapping(db)
    monkeypatch.setattr(kr_insider, "_provider",
                        lambda: pytest.fail("no fetch for an unknown code"))

    response = TestClient(app).get("/api/kr/insider/999999")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "kr_insider_unknown"


def test_a_failed_fetch_is_memoised(db, dart_lane, monkeypatch):
    _seed_mapping(db)
    calls = []

    class FailingProvider:
        def fetch_ownership_reports(self, corp_code):
            calls.append(corp_code)
            raise DataUnavailable("down")

    monkeypatch.setattr(kr_insider, "_provider", FailingProvider)
    client = TestClient(app)

    assert client.get("/api/kr/insider/005930").status_code == 503
    assert client.get("/api/kr/insider/005930").status_code == 503
    assert calls == ["00126380"]


def test_status_reports_the_dart_gate(db, monkeypatch):
    monkeypatch.setattr(config, "DART_ENABLED", True)
    monkeypatch.setattr(config, "DART_API_KEY", "")

    lanes = TestClient(app).get("/api/status").json()["data_lanes"]

    assert lanes["dart"]["status"] == "not_configured"
    assert "DART_API_KEY" in lanes["dart"]["gate"]
