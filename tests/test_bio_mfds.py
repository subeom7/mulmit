"""MFDS drug product permits (data.go.kr) — parsing, per-day refresh, serving block, gates."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import bio, config, data_rights, ingest
from app.main import app
from app.providers import mfds as mf
from app.providers.base import DataUnavailable, RateLimited

NOW = dt.datetime(2026, 8, 22, 3, 0, tzinfo=dt.UTC)  # 12:00 KST


def _item(seq: str, name: str, entp: str, day: str, *, kind: str = "허가", otc: str = "전문의약품", newdrug: str = "", rare: str = "N", ingr: str = "[M262653]에독사반토실산염수화물") -> dict[str, Any]:
    return {"ITEM_SEQ": seq, "ITEM_NAME": name, "ITEM_ENG_NAME": f"{name} EN", "ENTP_NAME": entp, "ENTP_ENG_NAME": "Co.", "ITEM_PERMIT_DATE": day,
            "PERMIT_KIND_NAME": kind, "ETC_OTC_CODE": otc, "NEWDRUG_CLASS_NAME": newdrug, "RARE_DRUG_YN": rare, "MAIN_ITEM_INGR": ingr,
            "INGR_NAME": "[M081161]크로스포비돈", "ATC_CODE": None, "MAKE_MATERIAL_FLAG": "완제의약품", "INDUTY_TYPE": "의약품", "CANCEL_NAME": "정상",
            "CANCEL_DATE": None, "CHANGE_DATE": None, "REEXAM_TARGET": None}


DAY_ROWS = {
    "20260821": [_item("202602430", "엘독사반정30밀리그램", "에이치엘비제약(주)", "20260821"), _item("202602431", "메가콘드로맥스", "동국제약(주)", "20260821", kind="신고", otc="일반의약품")],
    "20260820": [_item("202602418", "신약정", "유한양행", "20260820", newdrug="신약", ingr="[M1]레이저티닙|[M2]부형제"), _item("202602419", "희귀주", "한미약품", "20260820", rare="Y")],
}


def _body(day: str, page: int = 1, rows: int = 100) -> str:
    items = DAY_ROWS.get(day, [])
    return json.dumps({"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": {"pageNo": page, "totalCount": len(items), "numOfRows": rows, "items": items[(page - 1) * rows: page * rows]}})


def test_parse_response_maps_rows_and_error_shapes():
    parsed = mf.parse_response(200, _body("20260820"))
    assert parsed["total_count"] == 2 and [r["item_seq"] for r in parsed["permits"]] == ["202602418", "202602419"]
    row = parsed["permits"][0]
    assert row["permit_date"] == "2026-08-20" and row["newdrug_class"] == "신약" and row["main_ingredients"] == ["레이저티닙", "부형제"]
    assert row["url"] == "https://nedrug.mfds.go.kr/pbp/CCBBB01/getItemDetailCache?cacheSeq=202602418"
    assert parsed["permits"][1]["rare"] is True and parsed["permits"][1]["etc_otc"] == "전문의약품"
    with pytest.raises(DataUnavailable):
        mf.parse_response(403, json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR", "returnAuthMsg": "등록되지 않은 서비스키", "returnReasonCode": "30"}}}))
    with pytest.raises(RateLimited):
        mf.parse_response(200, json.dumps({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", "returnReasonCode": "22"}}}))
    with pytest.raises(DataUnavailable):
        mf.parse_response(200, json.dumps({"header": {"resultCode": "03", "resultMsg": "NODATA_ERROR"}, "body": {}}))
    with pytest.raises(DataUnavailable):
        mf.parse_response(200, "<xml/>")
    assert mf.normalized_key("abc%2Bdef%3D") == "abc%2Bdef%3D" and mf.normalized_key("abc+def=") == "abc%2Bdef%3D"


def test_provider_requests_day_filter_with_raw_key():
    seen: list[str] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        seen.append(url)
        return 200, _body("20260821")

    provider = mf.MfdsProvider("k+e=y", transport=transport, retries=0, rows=100)
    page = provider.fetch_permits_on(dt.date(2026, 8, 21))
    assert seen[0].startswith(f"{mf.API_BASE}/{mf.DETAIL_ENDPOINT}?serviceKey=k%2Be%3Dy&") and "item_permit_date=20260821" in seen[0] and "type=json" in seen[0]
    assert page["day"] == "2026-08-21" and len(page["permits"]) == 2
    with pytest.raises(ValueError):
        mf.MfdsProvider("")


class FakeMfds:
    def __init__(self, *, fail_days: set[str] = frozenset(), rate_limit_days: set[str] = frozenset(), rows: int = 100) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fail_days, self.rate_limit_days, self.rows = set(fail_days), set(rate_limit_days), rows

    def fetch_permits_on(self, day: dt.date, *, page: int = 1) -> dict[str, Any]:
        key = day.strftime("%Y%m%d")
        self.calls.append((key, page))
        if key in self.rate_limit_days:
            raise RateLimited("22")
        if key in self.fail_days:
            raise DataUnavailable("down")
        parsed = mf.parse_response(200, _body(key, page, self.rows))
        parsed.update(day=day.isoformat(), fetched_at="2026-08-22T03:00:00Z")
        return parsed


@pytest.fixture
def mfds_on(db, monkeypatch):
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "MFDS_ENABLED", True)
    monkeypatch.setattr(config, "MFDS_API_KEY", "test-key")
    monkeypatch.setattr(config, "MFDS_WINDOW_DAYS", 3)
    monkeypatch.setattr(config, "MFDS_PACE_SECONDS", 0.0)
    bio.clear_cache()
    yield
    bio.clear_cache()


def test_mfds_refresh_walks_the_window_and_build_counts(mfds_on):
    fake = FakeMfds(fail_days={"20260822"})
    result = bio.refresh_bio_mfds(provider=fake, now=NOW)
    assert [c[0] for c in fake.calls] == ["20260822", "20260821", "20260820"]  # KST today first, one call per day
    assert result == {"updated": 4, "days": 2, "failed_days": 1}
    assert bio.refresh_bio_mfds(provider=fake, now=NOW) == {"skipped": "fresh"}
    payload = bio.build_bio_mfds(now=NOW)
    assert [r["item_seq"] for r in payload["permits"]] == ["202602431", "202602430", "202602419", "202602418"]  # newest day first, then seq desc
    assert payload["counts"] == {"total": 4, "permit": 3, "report": 1, "rx": 3, "otc": 1, "new_drug": 1, "rare": 1}
    assert [r["item_seq"] for r in payload["notable"]] == ["202602430", "202602419", "202602418"]  # 허가·전문, 희귀, 신약 (신고·일반 excluded)
    assert payload["window"] == {"start": "2026-08-20", "end": "2026-08-22"} and payload["days"] == {"2026-08-21": 2, "2026-08-20": 2}
    assert payload["totals"]["failed_days"] == 1 and payload["attribution"]["text"].startswith("출처: 식품의약품안전처")
    assert payload["rights"]["status"] == "public_data_portal_unrestricted"


def test_mfds_refresh_pages_busy_days_and_stops_on_rate_limit(mfds_on):
    fake = FakeMfds(rows=1)
    bio.refresh_bio_mfds(provider=fake, now=NOW, force=True)
    assert fake.calls.count(("20260821", 1)) == 1 and ("20260821", 2) in fake.calls  # two rows, one per page
    limited = FakeMfds(rate_limit_days={"20260821"})
    result = bio.refresh_bio_mfds(provider=limited, now=NOW, force=True)
    assert result["days"] == 1 and result["failed_days"] == 1 and [c[0] for c in limited.calls] == ["20260822", "20260821"]  # stops after the rate limit
    with pytest.raises(DataUnavailable):
        bio.refresh_bio_mfds(provider=FakeMfds(fail_days={"20260822", "20260821", "20260820"}), now=NOW, force=True)


def test_mfds_gates_and_route(db, monkeypatch):
    bio.clear_cache()
    client = TestClient(app)
    assert client.get("/api/bio/mfds").json()["detail"]["code"] == "bio_section_disabled"
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    assert client.get("/api/bio/mfds").json()["detail"]["code"] == "bio_mfds_disabled"
    monkeypatch.setattr(config, "MFDS_ENABLED", True)
    monkeypatch.setattr(config, "MFDS_API_KEY", "")
    assert bio.refresh_bio_mfds(provider=FakeMfds()) == {"skipped": "not_configured"}
    assert ingest.refresh_bio_mfds() == {"skipped": "not_configured"}
    assert client.get("/api/bio/mfds").json()["detail"]["code"] == "bio_mfds_collecting"
    monkeypatch.setattr(config, "MFDS_API_KEY", "k")
    monkeypatch.setattr(config, "MFDS_WINDOW_DAYS", 2)
    monkeypatch.setattr(config, "MFDS_PACE_SECONDS", 0.0)
    bio.refresh_bio_mfds(provider=FakeMfds(), now=NOW)
    response = client.get("/api/bio/mfds")
    assert response.status_code == 200 and response.headers["x-data-source"] == "MFDS (data.go.kr)"
    assert 'id="bio-mfds"' in client.get("/bio").text
    report = data_rights.lane_report()
    assert report["mfds_drug_permit"]["status"] == "enabled" and report["mfds_drug_permit"]["fetch_key"] == "present"
