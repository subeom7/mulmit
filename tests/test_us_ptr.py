"""미 하원 PTR — house_fd lane의 배치 경로.

무엇을 고정하는가: 파서는 실제 전자 PTR 추출 텍스트의 구조적 잡음(뭉개진 제목,
연결된 날짜, 줄바꿈으로 쪼개진 금액 구간)을 그대로 다루고, 서명과 자산이 모두
있는 거래만 싣는다. 스캔 제출분은 목록·링크만 남는다. 상세는 doc_id로 증분
재사용되고 주기당 신규 PDF 수가 상한을 넘지 않는다. 게이트는 fail-closed다.

파서 픽스처는 실제 신고서(2026년, Clerk 공개 PDF)에서 추출한 텍스트를 그대로
줄인 것이다 — 구조를 손보면 테스트가 현실을 잃는다.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import config, ingest, us_ptr
from app.main import app
from app.providers.house_fd import HouseFdProvider, parse_ptr_text

TODAY = dt.date(2026, 8, 18)


@pytest.fixture
def ptr_lane(db, monkeypatch):
    monkeypatch.setattr(config, "US_PTR_ENABLED", True)


# 실제 신고서 20033779(Miller)의 추출 텍스트를 두 거래로 줄인 것.
MILLER_TEXT = """P        T           R
Clerk of the House of Representatives • Legislative Resource Center • B81 Cannon Building • Washington, DC 20515
F     I
Name: Hon. Carol Devine Miller
Status: Member
State/District:WV01
T
ID Owner Asset Transaction
Type
Date Notification
Date
Amount Cap.
Gains >
$200?
2000134514SP Pfizer, Inc. Common Stock (PFE)
[ST]
S 03/10/202504/11/2025 $15,001 -
$50,000
F      S     : Amended
S          O : United Bank Brokerage Account
2000134527SP U.S. Bancorp Common Stock (USB)
[ST]
S 03/10/202504/11/2025 $15,001 -
$50,000
F      S     : Amended
S          O : United Bank Brokerage Account
* For the complete list of asset type abbreviations, please visit https://fd.house.gov/reference/asset-type-codes.aspx.
Digitally Signed: Hon. Carol Devine Miller , 08/13/2026
"""

# 실제 신고서 20033910(Thanedar): 본인 소유, 일부 매도, 금액이 줄바꿈 없이 붙는 형태.
THANEDAR_TEXT = """P        T           R
F     I
Name: Hon. Shri Thanedar
T
ID Owner Asset Transaction
Type
Amount Cap.
Apple Inc. - Common Stock (AAPL)
[ST]
S (partial) 01/09/202601/09/2026$100,001 -
$250,000
F      S     : New
Strategy Inc - Class A Common Stock
(MSTR) [ST]
S 10/21/202510/21/2025 $15,001 -
$50,000
F      S     : New
"""


def test_parse_relays_the_electronic_table_verbatim():
    transactions, signatures = parse_ptr_text(MILLER_TEXT)

    assert signatures == 2
    assert len(transactions) == 2
    first = transactions[0]
    assert first["owner"] == "SP"
    assert first["ticker"] == "PFE"
    assert first["asset_code"] == "ST"
    assert first["type"] == "S"
    assert first["date"] == "2025-03-10"
    assert first["notification_date"] == "2025-04-11"
    assert first["amount"] == "$15,001 - $50,000"
    assert transactions[1]["ticker"] == "USB"


def test_parse_handles_partial_sales_and_self_ownership():
    transactions, signatures = parse_ptr_text(THANEDAR_TEXT)

    assert signatures == 2
    kinds = [(t["type"], t["ticker"], t["owner"]) for t in transactions]
    assert kinds == [("S (partial)", "AAPL", None), ("S", "MSTR", None)]
    assert transactions[0]["amount"] == "$100,001 - $250,000"


def test_parse_withholds_what_it_cannot_anchor():
    # 서명 없는 텍스트(스캔 잔여물)는 아무것도 만들지 않는다.
    assert parse_ptr_text("random noise\nwithout a table") == ([], 0)
    # 자산명이 비어 있는 서명은 세되, 거래로 싣지 않는다.
    orphan = "T           \nP 07/13/202607/13/2026$15,001 - $50,000\n"
    transactions, signatures = parse_ptr_text(orphan)
    assert signatures == 1
    assert transactions == []


# 운영 서버 추출에서 실제로 관측된 세 가지 오염 레이아웃 (2026-08-18, PR #41 직후).
def test_parse_finds_signatures_mid_line_and_carries_the_remainder():
    # Hern 20035134: 자산과 서명이 한 줄, 뒤이어 다음 거래의 소유자·자산이 붙는다.
    text = (
        "Diageo plc Common Stock (DEO) S 08/05/202608/05/2026$1,001 - $15,000 "
        "JT Kenvue Inc. Common Stock (KVUE) S 08/05/202608/05/2026$1,001 - $15,000\n"
    )
    transactions, signatures = parse_ptr_text(text)

    assert signatures == 2
    assert [(t["ticker"], t["owner"]) for t in transactions] == [("DEO", None), ("KVUE", "JT")]
    assert all(t["amount"] == "$1,001 - $15,000" for t in transactions)


def test_parse_strips_joined_headings_and_filing_id_residue():
    # Keating 20034898 서버 추출: 뭉개진 구역 제목들이 자산 앞에 한 줄로 붙는다.
    text = (
        "P        T           R      F     I           T            "
        "CAPITAL ONE FINL CORP NOTE 7.62400% [CS]\n"
        "P 06/30/202608/11/2026$1,001 - $15,000\n"
        "Filing ID #20035134 JT Kenvue Inc. Common Stock (KVUE) [ST]\n"
        "S 08/05/202608/05/2026$1,001 - $15,000\n"
    )
    transactions, signatures = parse_ptr_text(text)

    assert signatures == 2
    assert transactions[0]["asset"].startswith("CAPITAL ONE FINL CORP")
    kenvue = transactions[1]
    assert kenvue["owner"] == "JT"
    assert kenvue["ticker"] == "KVUE"
    assert "Filing ID" not in kenvue["asset"]


def test_parse_scrubs_nul_laced_headings():
    # 운영 pypdf는 머리글 글자 사이에 NUL을 끼운다: "P\x00\x00 T\x00 …".
    text = (
        "P\x00\x00\x00 T\x00\x00 R\x00 F\x00 I\x00 T\x00 SP Pinterest, Inc. Class A Common Stock (PINS) [ST]\n"
        "S 08/07/202608/07/2026$15,001 - $50,000\n"
    )
    transactions, signatures = parse_ptr_text(text)

    assert signatures == 1
    assert transactions[0]["owner"] == "SP"
    assert transactions[0]["ticker"] == "PINS"
    assert transactions[0]["asset"] == "Pinterest, Inc. Class A Common Stock (PINS)"


def test_parse_withholds_interleaved_two_column_rows():
    # Johnson 20035035: 자산명이 서명 좌우로 쪼개지고 유형 글자가 자산에 붙는다
    # ("CommonP"). 쪼개서 복원하려는 추측 대신 해당 거래를 버리고 개수로 남긴다.
    text = (
        "CMS Energy Corporation CommonP 12/08/202501/09/2026$1,001 - $15,000 "
        "Stock (CMS)  JT Deere & Company Common StockS 10/21/202511/06/2025 $1,001 - $15,000\n"
    )
    transactions, signatures = parse_ptr_text(text)

    # 글자에 붙은 서명은 서명으로 세지 않고, 오염된 자산은 싣지 않는다.
    assert transactions == []
    assert signatures == 0


def _index_zip(rows: list[dict]) -> bytes:
    inner = "﻿<FinancialDisclosure>" + "".join(
        "<Member>" + "".join(f"<{k}>{v}</{k}>" for k, v in row.items()) + "</Member>"
        for row in rows
    ) + "</FinancialDisclosure>"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("2026FD.xml", inner.encode("utf-8"))
    return buffer.getvalue()


def test_provider_reads_only_ptr_rows_from_the_index():
    payload = _index_zip([
        {"Prefix": "Hon.", "Last": "Yakym", "First": "Rudy C.", "Suffix": "III",
         "FilingType": "P", "StateDst": "IN02", "Year": "2026",
         "FilingDate": "7/13/2026", "DocID": "20034984"},
        {"Prefix": "Hon.", "Last": "Someone", "First": "Else", "Suffix": "",
         "FilingType": "A", "StateDst": "CA01", "Year": "2026",
         "FilingDate": "7/1/2026", "DocID": "999"},
    ])
    provider = HouseFdProvider(http_get=lambda r, t: payload,
                               retries=0, request_interval=0.0, sleep=lambda _s: None)

    rows = provider.fetch_ptr_index(2026)

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Hon. Rudy C. Yakym III"
    assert row["filed_date"] == "2026-07-13"
    assert row["pdf_url"].endswith("/ptr-pdfs/2026/20034984.pdf")


class FixtureProvider:
    def __init__(self, index_rows, details):
        self.index_rows = index_rows
        self.details = details
        self.index_calls: list[int] = []
        self.detail_calls: list[str] = []

    def fetch_ptr_index(self, year):
        self.index_calls.append(year)
        return [row for row in self.index_rows if row["year"] == year]

    def fetch_ptr_transactions(self, doc_id, year):
        self.detail_calls.append(doc_id)
        result = self.details.get(doc_id)
        if isinstance(result, Exception):
            raise result
        return result


def _filing(doc_id, filed, name="Hon. A Member"):
    return {"doc_id": doc_id, "name": name, "state_district": "TX01",
            "filed_date": filed, "year": 2026,
            "pdf_url": f"https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/{doc_id}.pdf"}


def _tx(ticker="PFE"):
    return {"owner": "SP", "asset": f"Stock ({ticker})", "ticker": ticker,
            "asset_code": "ST", "type": "S", "date": "2026-08-01",
            "notification_date": "2026-08-10", "amount": "$15,001 - $50,000"}


def test_refresh_windows_sorts_and_marks_scans(db, ptr_lane):
    provider = FixtureProvider(
        index_rows=[
            _filing("100", "2026-08-13"),
            _filing("200", "2026-08-01"),
            _filing("300", "2026-01-01"),  # 창 밖
        ],
        details={"100": ([_tx()], 1), "200": None},
    )

    stats = us_ptr.refresh(provider, today=TODAY)

    assert stats["filings"] == 2
    assert stats["total_in_window"] == 2
    payload = us_ptr.get_filings()
    assert [f["doc_id"] for f in payload["filings"]] == ["100", "200"]
    assert payload["filings"][0]["detail_status"] == "ok"
    assert payload["filings"][0]["transactions"][0]["ticker"] == "PFE"
    # 스캔 제출분은 거래 없이 원문 링크만 남는다.
    scanned = payload["filings"][1]
    assert scanned["detail_status"] == "unavailable"
    assert scanned["transactions"] == []
    assert "105(c)" in payload["legal"]["notice"]


def test_refresh_reuses_details_and_caps_new_pdfs(db, ptr_lane, monkeypatch):
    monkeypatch.setattr(us_ptr, "MAX_NEW_DETAILS", 1)
    provider = FixtureProvider(
        index_rows=[_filing("100", "2026-08-13"), _filing("200", "2026-08-12"),
                    _filing("300", "2026-08-11")],
        details={"200": ([_tx("USB")], 1),
                 "300": AssertionError("cached detail must not refetch")},
    )
    db.save_report(us_ptr.CACHE_KEY, {"filings": [
        {**_filing("300", "2026-08-11"), "transactions": [_tx("TGT")],
         "transaction_count": 1, "detail_status": "ok"},
    ]})

    us_ptr.refresh(provider, today=TODAY)

    # 캐시된 300은 재사용, 신규는 상한 1건(100)만 받고 200은 pending.
    assert provider.detail_calls == ["100"]
    payload = us_ptr.get_filings()
    by_id = {f["doc_id"]: f for f in payload["filings"]}
    assert by_id["300"]["transactions"][0]["ticker"] == "TGT"
    assert by_id["200"]["detail_status"] == "pending"


def test_the_request_path_reads_the_store_only(db, ptr_lane, monkeypatch):
    provider = FixtureProvider([_filing("100", "2026-08-13")], {"100": ([_tx()], 1)})
    us_ptr.refresh(provider, today=TODAY)
    monkeypatch.setattr(us_ptr, "_provider",
                        lambda: pytest.fail("the request path must not call the Clerk"))

    response = TestClient(app).get("/api/us/ptr")

    assert response.status_code == 200
    body = response.json()
    assert body["chamber"] == "house"
    assert body["filings"][0]["transactions"][0]["amount"] == "$15,001 - $50,000"
    assert "105(c)" in body["legal"]["notice"]
    assert response.headers["cache-control"] == "public, max-age=300"


def test_the_lane_fails_closed_and_an_empty_store_is_503(db, monkeypatch):
    client = TestClient(app)

    response = client.get("/api/us/ptr")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "us_ptr_disabled"
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(config, "US_PTR_ENABLED", True)
    response = client.get("/api/us/ptr")
    assert response.status_code == 503
    assert "not collected" in response.json()["detail"]


def test_ingest_respects_the_gate_and_freshness(db, monkeypatch):
    calls = []
    monkeypatch.setattr(us_ptr, "refresh", lambda: calls.append(1) or {"filings": 0})

    assert ingest.refresh_us_ptr() == {"skipped": "disabled"}

    monkeypatch.setattr(config, "US_PTR_ENABLED", True)
    assert ingest.refresh_us_ptr() == {"filings": 0}
    assert calls == [1]

    db.save_report(us_ptr.CACHE_KEY, {"filings": []})
    assert ingest.refresh_us_ptr() == {"skipped": "fresh"}
    assert calls == [1]
