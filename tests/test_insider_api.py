"""Insider-filing storage, assembly and the public API contract."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config, ingest, store
from app.insider_filings import InsiderDataDisabled, build_insider_report
from app.main import app

FILING_URL = "https://www.sec.gov/Archives/edgar/data/320193/0001261/form4.xml"


def _row(**overrides):
    row = {
        "accession_number": "0001-26-1",
        "sequence": 0,
        "form_type": "4",
        "filing_date": dt.date(2026, 8, 13),
        "transaction_date": dt.date(2026, 8, 11),
        "owner_name": "Newstead Jennifer",
        "owner_cik": "0001780525",
        "owner_title": "SVP, GC and Secretary",
        "is_director": False,
        "is_officer": True,
        "is_ten_percent_owner": False,
        "security_title": "Common Stock",
        "transaction_code": "S",
        "acquired_disposed": "D",
        "is_derivative": False,
        "shares": 1439.0,
        "price_per_share": 307.75,
        "shares_owned_after": 40107.0,
        "direct_or_indirect": "D",
        "filing_url": FILING_URL,
    }
    row.update(overrides)
    return row


def _seed(db, rows=None, **company):
    db.save_insider_filings(
        company.pop("ticker", "AAPL"),
        cik=company.pop("cik", "320193"),
        name=company.pop("name", "Apple Inc."),
        exchange=company.pop("exchange", "Nasdaq"),
        filings_seen=company.pop("filings_seen", 3),
        transactions=rows if rows is not None else [_row()],
    )


def test_report_separates_open_market_trades_from_compensation_mechanics(db, sec_edgar):
    _seed(db, [
        _row(),
        _row(accession_number="0001-26-2", sequence=0, transaction_code="M",
             acquired_disposed="A", shares=30104.0, price_per_share=None,
             transaction_date=dt.date(2026, 6, 15)),
        _row(accession_number="0001-26-2", sequence=1, transaction_code="F",
             acquired_disposed="D", shares=16238.0, price_per_share=296.42,
             transaction_date=dt.date(2026, 6, 15)),
        _row(accession_number="0001-26-3", sequence=0, transaction_code="P",
             acquired_disposed="A", shares=100.0, price_per_share=200.0,
             transaction_date=dt.date(2026, 5, 1)),
    ])

    report = build_insider_report("AAPL")
    summary = report["summary"]

    # The 30,104-share exercise and the 16,238-share tax withholding dwarf the
    # real trades. Folding them in would invent an enormous fake signal.
    assert summary["open_market"]["purchase"] == {"filings": 1, "shares": 100.0, "value": 20000.0}
    assert summary["open_market"]["sale"]["filings"] == 1
    assert summary["open_market"]["sale"]["shares"] == 1439.0
    assert summary["non_open_market_lines"] == 2
    assert summary["counted_codes"] == ["P", "S"]
    assert "never netted" in summary["basis"]


def test_transaction_payload_keeps_filed_values_verbatim(db, sec_edgar):
    _seed(db)

    item = build_insider_report("AAPL")["transactions"][0]

    assert item["owner"] == {
        "name": "Newstead Jennifer",
        "cik": "0001780525",
        "title": "SVP, GC and Secretary",
        "roles": ["officer"],
    }
    assert item["transaction"]["code"] == "S"
    assert item["transaction"]["open_market"] is True
    assert item["transaction"]["label"]["ko"]
    assert item["shares"] == 1439.0
    assert item["price_per_share"] == 307.75
    assert item["value"] == pytest.approx(442852.25)
    assert item["filing_url"] == FILING_URL


def test_missing_price_never_becomes_zero(db, sec_edgar):
    _seed(db, [_row(transaction_code="A", price_per_share=None, shares=500.0)])

    item = build_insider_report("AAPL")["transactions"][0]

    assert item["price_per_share"] is None
    assert item["value"] is None
    assert build_insider_report("AAPL")["summary"]["open_market"]["purchase"]["filings"] == 0


def test_unseen_ticker_is_queued_instead_of_fetched(db, sec_edgar):
    report = build_insider_report("KO")

    assert report["coverage"]["status"] == "queued"
    assert report["transactions"] == []
    # The request is remembered so the batch collects it next cycle.
    assert store.get_insider_company("KO")["request_count"] == 1
    assert "KO" in store.stale_insider_tickers([], config.SEC_EDGAR_MAX_AGE, 5)


def test_ticker_absent_from_edgar_is_reported_as_such(db, sec_edgar):
    store.mark_insider_error("EWY", "not listed", status="unavailable")

    report = build_insider_report("EWY")

    assert report["coverage"]["status"] == "unknown_to_edgar"
    # A permanently unknown ticker must not be retried by the batch forever.
    assert "EWY" not in store.stale_insider_tickers([], 0, 10)


def test_refresh_keeps_previously_collected_filings(db, sec_edgar):
    _seed(db, [_row()])
    _seed(db, [_row(accession_number="0001-26-9", transaction_date=dt.date(2026, 8, 20))])

    accessions = {row["accession_number"] for row in store.load_insider_transactions("AAPL")}

    assert accessions == {"0001-26-1", "0001-26-9"}


def test_recollecting_the_same_filing_is_idempotent(db, sec_edgar):
    _seed(db, [_row()])
    _seed(db, [_row()])

    assert len(store.load_insider_transactions("AAPL")) == 1


def test_error_keeps_the_rows_already_collected(db, sec_edgar):
    _seed(db)
    store.mark_insider_error("AAPL", "EDGAR timeout")

    report = build_insider_report("AAPL")

    assert report["coverage"]["status"] == "stale"
    assert report["coverage"]["error"] == "EDGAR timeout"
    assert len(report["transactions"]) == 1


def test_watchlist_is_refreshed_before_visitor_requests(db, sec_edgar):
    store.touch_insider_request("KO")

    queue = store.stale_insider_tickers(["AAPL", "MSFT"], 0, 5)

    assert queue[:2] == ["AAPL", "MSFT"]
    assert "KO" in queue


def test_api_serves_filings_with_source_and_rights(db, sec_edgar):
    _seed(db)

    response = TestClient(app).get("/api/insider/aapl")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["company"]["name"] == "Apple Inc."
    assert body["source"]["publisher"] == "U.S. Securities and Exchange Commission"
    assert body["source"]["forms"] == ["3", "4", "5"]
    assert body["source"]["terms_url"].startswith("https://www.sec.gov/")
    assert body["rights"]["status"] == "approved"
    assert body["rights"]["notice_localized"]["ko"]
    assert response.headers["x-data-source"] == "SEC EDGAR"


def test_api_limit_is_bounded_and_validated(db, sec_edgar):
    _seed(db, [_row(sequence=index, accession_number=f"a-{index}") for index in range(5)])
    client = TestClient(app)

    assert len(client.get("/api/insider/AAPL?limit=2").json()["transactions"]) == 2
    assert client.get("/api/insider/AAPL?limit=0").status_code == 422
    assert client.get("/api/insider/AAPL?limit=9999").status_code == 422


def test_api_fails_closed_when_the_lane_is_off(db):
    _seed(db)

    response = TestClient(app).get("/api/insider/AAPL")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "insider_data_disabled"
    assert response.headers["cache-control"] == "no-store"
    assert "Newstead" not in response.text


def test_api_fails_closed_without_a_declared_contact(db, monkeypatch):
    """SEC fair access treats an undeclared client as an unclassified bot."""
    _seed(db)
    monkeypatch.setattr(config, "SEC_EDGAR_ENABLED", True)
    monkeypatch.setattr(config, "SEC_EDGAR_USER_AGENT", "")

    response = TestClient(app).get("/api/insider/AAPL")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "insider_data_not_configured"
    assert "Newstead" not in response.text


def test_assembler_refuses_even_when_a_route_is_bypassed(db):
    _seed(db)

    with pytest.raises(InsiderDataDisabled):
        build_insider_report("AAPL")


def test_ingest_never_calls_edgar_while_the_lane_is_closed(db, monkeypatch):
    monkeypatch.setattr(
        "app.ingest.SecEdgarProvider",
        lambda *_a, **_k: pytest.fail("EDGAR must not be constructed while gated"),
    )

    assert ingest.refresh_insider_filings()["skipped"] == "disabled"

    monkeypatch.setattr(config, "SEC_EDGAR_ENABLED", True)
    monkeypatch.setattr(config, "SEC_EDGAR_USER_AGENT", "")
    assert ingest.refresh_insider_filings()["skipped"] == "not_configured"


def test_ingest_marks_a_non_filer_without_retrying_it(db, sec_edgar, monkeypatch):
    class Provider:
        def __init__(self, *_args, **_kwargs):
            pass

        def fetch_ticker_map(self):
            return {"AAPL": ("320193", "Apple Inc.")}

        def fetch_company(self, *_args, **_kwargs):  # pragma: no cover - not reached
            raise AssertionError("unknown tickers must not be fetched")

    monkeypatch.setattr(config, "SEC_EDGAR_TICKERS", ["EWY"])
    monkeypatch.setattr("app.ingest.SecEdgarProvider", Provider)

    result = ingest.refresh_insider_filings()

    assert result["unknown"] == 1
    assert store.get_insider_company("EWY")["status"] == "unavailable"


def test_status_reports_the_edgar_lane(db, sec_edgar):
    lanes = TestClient(app).get("/api/status").json()["data_lanes"]

    assert lanes["sec_edgar"]["status"] == "enabled"
    assert "SEC_EDGAR_USER_AGENT" in lanes["sec_edgar"]["gate"]
