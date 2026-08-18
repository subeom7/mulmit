"""미국 상장사 재무제표 — SEC EDGAR XBRL(companyconcept)의 원문 전달.

내부자 lane과 같은 티커 집합·큐·게이트를 그대로 탄다: 요청 경로는 EDGAR를
부르지 않고, 방문자가 찾은 티커는 `sec_companies` 큐에 기록돼 다음 수집
주기가 채운다. 수집은 개념별 소형 JSON(companyconcept)만 받는다 —
companyfacts 전체(수 MB)를 받지 않는다.

**XBRL의 두 함정을 여기서 처리한다.**

* 회사마다 같은 항목에 다른 태그를 쓴다(Revenues vs
  RevenueFromContractWithCustomer…). 태그 사다리를 순서대로 시도하고, 실제
  사용한 태그를 응답(`concepts_used`)에 그대로 싣는다.
* 10-Q의 흐름 항목은 분기값과 연초누계(YTD)가 한 시계열에 섞여 온다. 기간
  길이로 분류한다 — 분기는 75~105일, 연간은 340~380일 — 그리고 같은 기간이
  여러 공시에 반복되면 가장 늦게 제출된 값(정정 반영)만 남긴다.

파생값은 마진 둘뿐이며(영업·순이익 ÷ 매출, 같은 보고서의 두 값), 산식을
응답 basis에 명시한다. 가격 의존 지표(PER 등)는 미국 가격 표시 권리가 없어
만들지 않는다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, data_rights, store
from .insider_filings import rights_metadata
from .providers.base import DataUnavailable
from .providers.sec_edgar import (
    EDGAR_TERMS_URL,
    SEC_DATA_BASE,
    SEC_PUBLISHER,
    SEC_PUBLISHER_URL,
    EdgarNotFound,
    SecEdgarProvider,
)

log = logging.getLogger(__name__)

# (지표, 태그 사다리, 단위, 성격) — 성격은 흐름(기간) 또는 시점(잔액).
CONCEPTS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("revenue", (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ), "USD", "flow"),
    ("operating_income", ("OperatingIncomeLoss",), "USD", "flow"),
    ("net_income", ("NetIncomeLoss",), "USD", "flow"),
    ("eps_diluted", ("EarningsPerShareDiluted",), "USD/shares", "flow"),
    ("assets", ("Assets",), "USD", "instant"),
    ("equity", (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ), "USD", "instant"),
)

ANNUAL_ROWS = 5
QUARTERLY_ROWS = 8
_ANNUAL_DAYS = (340, 380)
_QUARTER_DAYS = (75, 105)


class UsFundamentalsDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def cache_key(ticker: str) -> str:
    return f"us_fund_{ticker.strip().upper()}"


def _require_serving() -> None:
    status = data_rights.sec_edgar_status()
    if status != "enabled":
        raise UsFundamentalsDisabled(status)


def _days(start: str | None, end: str | None) -> int | None:
    try:
        return (dt.date.fromisoformat(str(end)) - dt.date.fromisoformat(str(start))).days
    except (TypeError, ValueError):
        return None


def _dedupe_latest_filed(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """같은 (start, end) 기간이 여러 공시에 반복되면 최신 제출분만 남긴다."""
    best: dict[tuple, dict[str, Any]] = {}
    for entry in entries:
        key = (entry.get("start"), entry.get("end"))
        kept = best.get(key)
        if kept is None or str(entry.get("filed") or "") > str(kept.get("filed") or ""):
            best[key] = entry
    return list(best.values())


def _collect_concept(
    provider: SecEdgarProvider, cik: str, ladder: tuple[str, ...], unit: str
) -> tuple[str, list[dict[str, Any]]] | None:
    """사다리의 태그들 중 **가장 최신 데이터를 가진** 태그를 고른다.

    회사는 태그를 갈아탄다 — NVIDIA는 RevenueFromContractWithCustomer…를 쓰다
    끊었다(실측: 그 태그의 마지막 기간이 2022년). "존재하는 첫 태그"를 고르면
    몇 년 묵은 표가 되므로, 존재하는 태그 전부의 마지막 보고 기간을 비교한다.
    """
    candidates: list[tuple[str, str, list[dict[str, Any]]]] = []
    for tag in ladder:
        try:
            payload = provider.fetch_company_concept(cik, tag)
        except EdgarNotFound:
            continue
        entries = payload.get("units", {}).get(unit)
        if not isinstance(entries, list) or not entries:
            continue
        rows = [e for e in entries if isinstance(e, dict) and e.get("val") is not None]
        if rows:
            newest = max(str(e.get("end") or "") for e in rows)
            candidates.append((newest, tag, _dedupe_latest_filed(rows)))
    if not candidates:
        return None
    # 최신 기간 우선, 같으면 사다리 앞쪽 우선(리스트 순서가 이미 그렇다).
    newest, tag, rows = max(candidates, key=lambda item: item[0])
    return tag, rows


def _split_periods(entries: list[dict[str, Any]], kind: str) -> dict[str, dict]:
    """흐름은 기간 길이로 연간/분기를 나누고, 시점은 잔액일로 색인한다."""
    if kind == "instant":
        return {"by_end": {str(e.get("end")): e for e in entries if e.get("end")}}
    annual: dict[tuple, dict] = {}
    quarterly: dict[tuple, dict] = {}
    for entry in entries:
        days = _days(entry.get("start"), entry.get("end"))
        if days is None:
            continue
        key = (str(entry["start"]), str(entry["end"]))
        if _ANNUAL_DAYS[0] <= days <= _ANNUAL_DAYS[1]:
            annual[key] = entry
        elif _QUARTER_DAYS[0] <= days <= _QUARTER_DAYS[1]:
            quarterly[key] = entry
    return {"annual": annual, "quarterly": quarterly}


def _margin(income: float | None, revenue: float | None) -> float | None:
    if income is None or not revenue:
        return None
    return round(income / revenue * 100, 1)


def refresh_for(provider: SecEdgarProvider, ticker: str, cik: str, name: str) -> dict:
    """한 티커의 재무 패널을 수집·조립해 저장한다. 배치에서만 부른다."""
    collected: dict[str, dict] = {}
    concepts_used: dict[str, str] = {}
    for metric, ladder, unit, kind in CONCEPTS:
        found = _collect_concept(provider, cik, ladder, unit)
        if found is None:
            continue
        tag, entries = found
        concepts_used[metric] = tag
        collected[metric] = _split_periods(entries, kind)

    if "revenue" not in collected:
        # 매출조차 없으면 표가 성립하지 않는다(IFRS 제출사 등). 저장하지 않고
        # 실패로 알려 다음 주기에 재시도하게 둔다 — 빈 캐시가 12시간을 가리면 안 된다.
        raise DataUnavailable(f"EDGAR has no us-gaap revenue concept for {ticker}")

    def rows_for(period_kind: str, limit: int) -> list[dict[str, Any]]:
        periods = sorted(
            collected["revenue"][period_kind].values(),
            key=lambda e: str(e.get("end")),
        )[-limit:]
        rows = []
        for base in periods:
            key = (str(base["start"]), str(base["end"]))
            end = str(base["end"])

            def flow(metric: str) -> float | None:
                bucket = collected.get(metric, {}).get(period_kind, {})
                entry = bucket.get(key)
                return entry.get("val") if entry else None

            def instant(metric: str) -> float | None:
                entry = collected.get(metric, {}).get("by_end", {}).get(end)
                return entry.get("val") if entry else None

            revenue = base.get("val")
            operating = flow("operating_income")
            net = flow("net_income")
            rows.append({
                "start": base.get("start"),
                "end": end,
                "fiscal_year": base.get("fy"),
                "fiscal_period": base.get("fp"),
                "form": base.get("form"),
                "revenue": revenue,
                "operating_income": operating,
                "net_income": net,
                "eps_diluted": flow("eps_diluted"),
                "assets": instant("assets"),
                "equity": instant("equity"),
                "operating_margin": _margin(operating, revenue),
                "net_margin": _margin(net, revenue),
            })
        rows.reverse()  # 최신이 먼저
        return rows

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "ticker": ticker,
        "cik": cik,
        "company": name,
        "unit": "USD",
        "annual": rows_for("annual", ANNUAL_ROWS),
        "quarterly": rows_for("quarterly", QUARTERLY_ROWS),
        "concepts_used": concepts_used,
        "basis_ko": (
            "SEC EDGAR XBRL(10-K·10-Q) 공시값을 그대로 전달합니다. 분기와 연간은 "
            "보고 기간 길이로 구분하고, 정정 공시는 최신 제출분을 씁니다. 파생값은 "
            "마진 둘뿐입니다(이익 ÷ 매출, 같은 보고서의 두 값). 금액 단위 USD."
        ),
        "basis_en": (
            "XBRL figures from SEC EDGAR 10-K/10-Q filings, relayed as filed. "
            "Quarterly and annual periods are separated by reported duration, with "
            "amendments taking the latest filing. The only derived values are the "
            "two margins (income ÷ revenue from the same filing). Amounts in USD."
        ),
        "source": {
            "provider": "sec_edgar",
            "publisher": SEC_PUBLISHER,
            "publisher_url": SEC_PUBLISHER_URL,
            "url": f"{SEC_DATA_BASE}/api/xbrl/companyconcept/",
            "terms_url": EDGAR_TERMS_URL,
        },
        "rights": rights_metadata(),
    }
    store.save_report(cache_key(ticker), payload)
    return {"annual": len(payload["annual"]), "quarterly": len(payload["quarterly"])}


def build_report(ticker: str) -> dict[str, Any]:
    """저장분만 읽는다. 미수집 티커는 내부자 큐에 태워 다음 주기에 채운다."""
    _require_serving()
    ticker = ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker must not be empty")

    blob = store.load_report(cache_key(ticker), config.REPORT_TTL * 2)
    if blob is not None:
        return {**blob, "status": "collected"}

    company = store.get_insider_company(ticker)
    if company is None or company.get("status") == "queued":
        store.touch_insider_request(ticker)
        status = "queued"
    elif company.get("status") == "unavailable":
        status = "unknown_to_edgar"
    else:
        status = "queued"  # 내부자만 수집됨 — 재무는 다음 주기에 붙는다
    return {
        "ticker": ticker,
        "status": status,
        "annual": [],
        "quarterly": [],
        "rights": rights_metadata(),
    }
