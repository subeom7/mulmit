"""Read-only assembly of SEC EDGAR insider filings from local data.

The one judgement call this module makes is refusing to make one: Form 4 lumps
very different events into a single filing stream, and rolling them into a
"bought vs sold" number is where most insider-trading summaries go wrong. A
grant (``A``), an option exercise (``M``) and shares surrendered for tax
withholding (``F``) are not open-market decisions, so they are counted apart
from actual purchases (``P``) and sales (``S``) and never netted against them.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import data_rights, store
from .providers.sec_edgar import (
    EDGAR_TERMS_URL,
    SEC_BASE,
    SEC_PUBLISHER,
    SEC_PUBLISHER_URL,
    SEC_RIGHTS_NOTICE,
    SEC_RIGHTS_NOTICE_KO,
    transaction_code_label,
)

MAX_PUBLIC_TRANSACTIONS = 200
DEFAULT_TRANSACTIONS = 50
# Codes that represent a discretionary trade in the open market.
OPEN_MARKET_CODES = {"P": "purchase", "S": "sale"}


class InsiderDataDisabled(RuntimeError):
    """Raised when the SEC EDGAR lane may not be served."""

    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _utc_iso(epoch: float | None = None) -> str:
    moment = dt.datetime.fromtimestamp(epoch, tz=dt.UTC) if epoch else dt.datetime.now(dt.UTC)
    return moment.isoformat().replace("+00:00", "Z")


def _date_iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def _require_serving() -> None:
    """Second line of defence, matching the macro reader.

    The lane verdict lives in one place so a route added later cannot serve
    filings the gate would have refused.
    """
    status = data_rights.sec_edgar_status()
    if status != "enabled":
        raise InsiderDataDisabled(status)


def source_metadata(cik: str | None) -> dict[str, Any]:
    return {
        "provider": "sec_edgar",
        "publisher": SEC_PUBLISHER,
        "publisher_url": SEC_PUBLISHER_URL,
        "url": (
            f"{SEC_BASE}/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include"
            if cik
            else f"{SEC_BASE}/search-filings"
        ),
        "terms_url": EDGAR_TERMS_URL,
        "forms": ["3", "4", "5"],
    }


def rights_metadata() -> dict[str, Any]:
    return {
        "status": "approved",
        "notice": SEC_RIGHTS_NOTICE,
        "notice_localized": {"ko": SEC_RIGHTS_NOTICE_KO, "en": SEC_RIGHTS_NOTICE},
    }


def _transaction_payload(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("transaction_code") or "")
    shares = row.get("shares")
    price = row.get("price_per_share")
    roles = []
    if row.get("is_director"):
        roles.append("director")
    if row.get("is_officer"):
        roles.append("officer")
    if row.get("is_ten_percent_owner"):
        roles.append("ten_percent_owner")
    return {
        "accession_number": row.get("accession_number"),
        "sequence": row.get("sequence"),
        "form_type": row.get("form_type"),
        "filing_date": _date_iso(row.get("filing_date")),
        "transaction_date": _date_iso(row.get("transaction_date")),
        "owner": {
            "name": row.get("owner_name"),
            "cik": row.get("owner_cik") or None,
            "title": row.get("owner_title") or None,
            "roles": roles,
        },
        "security_title": row.get("security_title") or None,
        "transaction": {
            "code": code or None,
            "label": transaction_code_label(code),
            "open_market": code in OPEN_MARKET_CODES,
            "acquired_disposed": row.get("acquired_disposed") or None,
            "is_derivative": bool(row.get("is_derivative")),
        },
        "shares": shares,
        "price_per_share": price,
        # A grant has no price, so a value is only reported when the filing gave one.
        "value": (shares * price) if shares is not None and price is not None else None,
        "shares_owned_after": row.get("shares_owned_after"),
        "ownership": row.get("direct_or_indirect") or None,
        "filing_url": row.get("filing_url"),
    }


def _summary(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Count open-market activity separately from compensation mechanics."""
    buckets = {
        "purchase": {"filings": 0, "shares": 0.0, "value": 0.0},
        "sale": {"filings": 0, "shares": 0.0, "value": 0.0},
    }
    other = 0
    for item in payloads:
        code = (item["transaction"]["code"] or "").upper()
        bucket_name = OPEN_MARKET_CODES.get(code)
        if bucket_name is None:
            other += 1
            continue
        bucket = buckets[bucket_name]
        bucket["filings"] += 1
        if item["shares"] is not None:
            bucket["shares"] += item["shares"]
        if item["value"] is not None:
            bucket["value"] += item["value"]

    dates = [item["transaction_date"] for item in payloads if item["transaction_date"]]
    return {
        "open_market": buckets,
        "non_open_market_lines": other,
        "counted_codes": sorted(OPEN_MARKET_CODES),
        "basis": (
            "Only open-market purchases (P) and sales (S) are totalled. Grants (A), "
            "derivative exercises (M) and tax-withholding surrenders (F) are reported "
            "individually but never netted into these figures."
        ),
        "basis_ko": (
            "시장 매수(P)와 매도(S)만 합산합니다. 부여(A), 파생 행사(M), 세금 원천징수 "
            "상계(F)는 개별 표시하되 이 합계에 넣지 않습니다."
        ),
        "first_transaction_date": min(dates) if dates else None,
        "last_transaction_date": max(dates) if dates else None,
    }


def build_insider_report(ticker: str, limit: int = DEFAULT_TRANSACTIONS) -> dict[str, Any]:
    """Assemble one ticker's filings, queueing an unseen ticker for the batch."""
    _require_serving()
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker must not be empty")
    limit = max(1, min(limit, MAX_PUBLIC_TRANSACTIONS))

    company = store.get_insider_company(ticker)
    rows = store.load_insider_transactions(ticker, limit=limit) if company else []
    payloads = [_transaction_payload(row) for row in rows]

    if company is None or company.get("status") == "queued":
        # Request handlers never call EDGAR. Record the interest so the next
        # ingest cycle picks this ticker up, and say so plainly.
        store.touch_insider_request(ticker)
        coverage_status = "queued"
    elif company.get("status") == "unavailable":
        coverage_status = "unknown_to_edgar"
    elif company.get("status") == "error":
        coverage_status = "stale" if payloads else "error"
    elif not payloads:
        coverage_status = "no_filings"
    else:
        coverage_status = "collected"

    fetched_at = (company or {}).get("fetched_at")
    return {
        "generated_at": _utc_iso(),
        "ticker": ticker,
        "company": {
            "name": (company or {}).get("name"),
            "cik": (company or {}).get("cik"),
            "exchange": (company or {}).get("exchange"),
        },
        "source": source_metadata((company or {}).get("cik")),
        "rights": rights_metadata(),
        "coverage": {
            "status": coverage_status,
            "filings_seen": (company or {}).get("filings_seen") or 0,
            "returned": len(payloads),
            "limit": limit,
            "fetched_at": _utc_iso(fetched_at) if fetched_at else None,
            "requested_count": (company or {}).get("request_count") or 0,
            "error": (company or {}).get("error"),
        },
        "summary": _summary(payloads),
        "transactions": payloads,
    }
