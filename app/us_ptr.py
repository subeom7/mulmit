"""미 하원 의원 주기거래보고(PTR) — house_fd lane의 배치 경로.

국민연금 lane(:mod:`app.kr_pension`)과 같은 구조다: 수집은 ingest 배치에서만
돌고(연간 인덱스 1요청 + 신규 PDF 건당 1요청, 1초 간격), web은 저장된 결과만
읽는다. PDF 상세는 블롭 안에서 doc_id로 증분 재사용해 같은 원문을 두 번
받지 않는다.

표시 원칙은 EDGAR·DART와 같다 — 보고된 값을 가공 없이 전달한다. 거래 금액이
구간(range)으로만 공시된다는 것, 전자 제출분만 거래 표가 추출된다는 것, 그리고
EIGA §105(c) 사용 제한이 응답에 함께 실린다는 것이 이 lane의 고유한 사실이다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, store
from .providers.base import DataError, DataUnavailable, RateLimited
from .providers.house_fd import (
    EIGA_105C_NOTICE_EN,
    EIGA_105C_NOTICE_KO,
    HOUSE_FD_ATTRIBUTION,
    HOUSE_FD_PROVIDER_ID,
    HOUSE_FD_PUBLISHER,
    HOUSE_FD_PUBLISHER_URL,
    HOUSE_FD_SEARCH_URL,
    HouseFdProvider,
)

log = logging.getLogger(__name__)

# v2: 파서가 줄 중간 서명과 오염 검증을 배우면서 기존 상세를 전부 재파싱한다.
CACHE_KEY = "house_ptr_v2"
WINDOW_DAYS = 45
MAX_FILINGS = 40
# 한 주기에 새로 받는 PDF 수 상한. 나머지는 pending으로 남아 다음 주기에 채워진다.
MAX_NEW_DETAILS = 25


class UsPtrDisabled(RuntimeError):
    pass


def _require_lane() -> None:
    if not config.US_PTR_ENABLED:
        raise UsPtrDisabled


def _provider() -> HouseFdProvider:
    return HouseFdProvider(
        timeout=config.US_PTR_TIMEOUT,
        retries=config.US_PTR_RETRIES,
        request_interval=config.US_PTR_REQUEST_INTERVAL,
    )


def refresh(provider: HouseFdProvider | None = None, *, today: dt.date | None = None) -> dict:
    """창 안의 PTR 인덱스를 걷고, 신규 건의 거래 상세를 붙여 저장한다."""
    _require_lane()
    provider = provider or _provider()
    today = today or dt.date.today()
    begin = today - dt.timedelta(days=WINDOW_DAYS)

    rows: list[dict[str, Any]] = []
    for year in sorted({begin.year, today.year}):
        rows.extend(provider.fetch_ptr_index(year))
    in_window = [row for row in rows if begin.isoformat() <= row["filed_date"] <= today.isoformat()]
    in_window.sort(key=lambda row: (row["filed_date"], row["doc_id"]), reverse=True)
    kept = in_window[:MAX_FILINGS]

    # 이전 블롭의 상세를 doc_id로 재사용한다 — 원문 PDF를 두 번 받지 않는다.
    previous = store.load_report(CACHE_KEY, config.US_PTR_MAX_AGE * 8) or {}
    known: dict[str, dict[str, Any]] = {
        filing["doc_id"]: filing
        for filing in previous.get("filings") or []
        if filing.get("detail_status") in ("ok", "partial", "unavailable")
    }

    fetched = 0
    rate_limited = False
    filings = []
    for row in kept:
        cached = known.get(row["doc_id"])
        if cached is not None:
            filings.append({**row, **{k: cached[k] for k in (
                "transactions", "transaction_count", "detail_status") if k in cached}})
            continue
        if rate_limited or fetched >= MAX_NEW_DETAILS:
            filings.append({**row, "transactions": [], "transaction_count": None,
                            "detail_status": "pending"})
            continue
        fetched += 1
        try:
            result = provider.fetch_ptr_transactions(row["doc_id"], row["year"])
        except RateLimited:
            rate_limited = True
            log.warning("House Clerk 요청 제한 — 남은 PTR 상세는 다음 주기에")
            filings.append({**row, "transactions": [], "transaction_count": None,
                            "detail_status": "pending"})
            continue
        except (DataUnavailable, DataError) as exc:
            log.warning("PTR 상세 실패 %s: %s", row["doc_id"], exc)
            filings.append({**row, "transactions": [], "transaction_count": None,
                            "detail_status": "pending"})
            continue
        if result is None:
            # 스캔 제출분 — 추출 불가는 사실이므로 원문 링크만 남긴다.
            filings.append({**row, "transactions": [], "transaction_count": None,
                            "detail_status": "unavailable"})
            continue
        transactions, signatures = result
        status = "ok" if len(transactions) == signatures and signatures > 0 else (
            "partial" if transactions else "unavailable")
        filings.append({**row, "transactions": transactions,
                        "transaction_count": len(transactions), "detail_status": status})

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "chamber": "house",
        "window": {"from": begin.isoformat(), "to": today.isoformat(), "days": WINDOW_DAYS},
        "filings": filings,
        "count": len(filings),
        "total_in_window": len(in_window),
        "basis_ko": (
            "STOCK Act에 따른 미 하원 의원 주기거래보고(PTR)를 그대로 옮깁니다. 금액은 "
            "구간으로만 공시되며, 전자 제출분만 거래 표가 추출되고 수기 제출분은 원문 "
            "링크로 안내합니다. 상원은 수집 경로가 막혀 있어 포함되지 않습니다."
        ),
        "basis_en": (
            "U.S. House periodic transaction reports (STOCK Act), relayed verbatim. "
            "Amounts are disclosed only as ranges; transaction tables are extracted "
            "from electronic filings, while scanned paper filings link to the "
            "original. The Senate is not included."
        ),
        "legal": {"notice": EIGA_105C_NOTICE_EN, "notice_ko": EIGA_105C_NOTICE_KO},
        "source": {
            "provider": HOUSE_FD_PROVIDER_ID,
            "provider_name": HOUSE_FD_PUBLISHER,
            "publisher": HOUSE_FD_PUBLISHER,
            "publisher_url": HOUSE_FD_PUBLISHER_URL,
            "url": HOUSE_FD_SEARCH_URL,
            "notice": HOUSE_FD_ATTRIBUTION,
        },
        "rights": {"status": "approved", "notice": HOUSE_FD_ATTRIBUTION},
    }
    store.save_report(CACHE_KEY, payload)
    detailed = sum(1 for f in filings if f["detail_status"] in ("ok", "partial"))
    return {
        "filings": len(filings),
        "total_in_window": len(in_window),
        "detailed": detailed,
        "pdf_fetched": fetched,
        "rate_limited": rate_limited,
    }


def get_filings() -> dict:
    """저장된 결과만 읽는다. 요청 경로에서 하원 서버를 호출하지 않는다."""
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("House PTR filings not collected yet")
    return cached
