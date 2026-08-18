"""ETF 보드 — FSC 증권상품시세정보 lane.

무엇을 고정하는가: 스냅샷 파서는 NAV 0을 결측으로 다룬다, 괴리율은 같은
기준일의 공표값 두 개에서만 계산되고 한쪽이 없으면 null이다, 보드는 거래대금
내림차순 상위만 싣는다, 게이트는 기존 FSC lane과 함께 fail-closed다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import config, kr_stocks
from app.main import app
from app.providers.fsc import FscProvider


@pytest.fixture
def fsc_lane(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "test-key")
    kr_stocks._recent_failures.clear()


def _etf_item(**overrides):
    row = {
        "basDt": "20260814", "srtnCd": "069500", "itmsNm": "KODEX 200",
        "clpr": "42000", "vs": "500", "fltRt": "1.2", "nav": "41850.55",
        "trqu": "5000000", "trPrc": "210000000000", "mrktTotAmt": "6500000000000",
        "nPptTotAmt": "6400000000000", "bssIdxIdxNm": "코스피 200", "bssIdxClpr": "1071.24",
    }
    row.update(overrides)
    return row


def _envelope(items, total):
    return json.dumps({
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"totalCount": total, "items": {"item": items}},
        }
    }).encode("utf-8")


def test_provider_parses_the_etf_snapshot_and_zero_nav_is_missing():
    items = [
        _etf_item(),
        _etf_item(srtnCd="466920", itmsNm="신규상장ETF", nav="0", trPrc="1000"),
    ]

    def http_get(request, timeout):
        if "numOfRows=1&" in request.full_url or "numOfRows=1?" in request.full_url:
            return _envelope([items[0]], total=2)
        return _envelope(items, total=2)

    provider = FscProvider("test-key", http_get=http_get,
                           retries=0, request_interval=0.0, sleep=lambda _s: None)

    bas_dt, rows = provider.fetch_etf_day_snapshot()

    assert bas_dt.startswith("20") and len(bas_dt) == 10
    by_code = {row["srtn_cd"]: row for row in rows}
    assert by_code["069500"]["clpr"] == 42000.0
    assert by_code["069500"]["nav"] == 41850.55
    assert by_code["069500"]["bss_idx_idx_nm"] == "코스피 200"
    # 신규 상장분의 NAV 0은 값이 아니다.
    assert by_code["466920"]["nav"] is None


def test_board_computes_premium_only_from_published_pairs(db, fsc_lane):
    db.save_kr_etf_snapshot([
        {"srtn_cd": "069500", "itms_nm": "KODEX 200", "clpr": 42000.0, "vs": 500.0,
         "flt_rt": 1.2, "nav": 41850.55, "trqu": 5e6, "tr_prc": 2.1e11,
         "mrkt_tot_amt": 6.5e12, "n_ppt_tot_amt": 6.4e12,
         "bss_idx_idx_nm": "코스피 200", "bss_idx_clpr": 1071.24},
        {"srtn_cd": "466920", "itms_nm": "신규상장ETF", "clpr": 10000.0, "vs": None,
         "flt_rt": None, "nav": None, "trqu": 1.0, "tr_prc": 1000.0,
         "mrkt_tot_amt": None, "n_ppt_tot_amt": None,
         "bss_idx_idx_nm": None, "bss_idx_clpr": None},
    ], "2026-08-14")

    payload = kr_stocks.etf_board()

    assert payload["as_of"] == "2026-08-14"
    assert payload["total_listed"] == 2
    top = payload["rows"][0]
    assert top["code"] == "069500"
    assert top["premium_percent"] == round((42000.0 / 41850.55 - 1) * 100, 2)
    # NAV가 없으면 괴리율을 만들어내지 않는다.
    assert payload["rows"][1]["premium_percent"] is None


def test_board_ranks_by_traded_value_and_caps_the_list(db, fsc_lane, monkeypatch):
    monkeypatch.setattr(kr_stocks, "ETF_BOARD_LIMIT", 2)
    db.save_kr_etf_snapshot([
        {"srtn_cd": "A", "itms_nm": "가", "clpr": 1.0, "nav": 1.0, "tr_prc": 10.0},
        {"srtn_cd": "B", "itms_nm": "나", "clpr": 1.0, "nav": 1.0, "tr_prc": 30.0},
        {"srtn_cd": "C", "itms_nm": "다", "clpr": 1.0, "nav": 1.0, "tr_prc": 20.0},
    ], "2026-08-14")

    payload = kr_stocks.etf_board()

    assert [row["code"] for row in payload["rows"]] == ["B", "C"]
    assert payload["total_listed"] == 3


def test_the_request_path_reads_the_store_without_calling_the_provider(db, fsc_lane, monkeypatch):
    db.save_kr_etf_snapshot(
        [{"srtn_cd": "069500", "itms_nm": "KODEX 200", "clpr": 42000.0,
          "nav": 41850.55, "tr_prc": 2.1e11}], "2026-08-14")
    monkeypatch.setattr(kr_stocks, "_provider",
                        lambda: pytest.fail("a warm snapshot must not refetch"))

    response = TestClient(app).get("/api/kr/etf")

    assert response.status_code == 200
    body = response.json()
    assert body["rows"][0]["name"] == "KODEX 200"
    assert "data.go.kr/data/15094806" in body["source"]["url"]
    assert response.headers["cache-control"] == "public, max-age=300"


def test_the_lane_fails_closed_and_an_empty_snapshot_is_503(db, monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(config, "FSC_ENABLED", False)
    response = client.get("/api/kr/etf")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "kr_stock_data_disabled"
    assert response.headers["cache-control"] == "no-store"

    # lane은 열려 있으나 키가 없고 스냅샷도 비어 있으면 채울 수 없다.
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "")
    response = client.get("/api/kr/etf")
    assert response.status_code == 503
    assert response.json()["detail"] == "ETF snapshot unavailable"
