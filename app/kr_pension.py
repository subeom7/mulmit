"""국민연금 대량보유(5%) 공시 — DART lane의 배치 경로.

hlkr '연기금 매매' 섹션의 대응물이다. KRX 투자자별 매매 데이터는 재배포 권리가
없어 쓰지 않고, 자본시장법 5% 룰에 따라 국민연금공단이 제출하는 주식등의
대량보유 상황보고(D001)를 그대로 전달한다. 보고서 단위이며 일별 매매가 아니다.
국민연금은 통상 한 달치 변동을 월초에 일괄 보고하고 사이사이 개별 보고가 낀다
(2026-08 관찰: 90일 창 140건 중 121건이 7/1 하루).

수집은 ingest 배치에서만 돈다: 공시검색(list.json)에는 제출인 필터가 없어 창
전체를 페이징으로 걷어야 하고(90일 ≈ 40여 요청), 표시분에는 majorstock 상세를
회사별로 한 번씩 더 붙인다. 이 비용은 요청 경로에 둘 수 없으므로 web은 저장된
결과만 읽고, 배치가 실패하면 섹션은 데이터 없음으로 닫힌다.

이 크롤은 두 blob을 만든다(2026-08-20): 국민연금 필터 전의 **전체 보고자**
목록이 kr_holdings lane으로 함께 저장된다 — 같은 걷기, 넓은 서빙.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, kr_holdings, store
from .providers.base import DataError, DataUnavailable, RateLimited
from .providers.dart import (
    DART_ATTRIBUTION,
    DART_ATTRIBUTION_EN,
    DART_PROVIDER_ID,
    DART_PUBLISHER,
    DART_PUBLISHER_URL,
    DART_REPORT_URL,
    DART_TERMS_URL,
    DartProvider,
)

log = logging.getLogger(__name__)

CACHE_KEY = "dart_nps_majorstock_v1"
DETAIL_TYPE_MAJOR_HOLDINGS = "D001"  # 공시검색 상세유형: 주식등의대량보유상황보고서
REPORTER_KEYWORD = "국민연금"
WINDOW_DAYS = 90
MAX_FILINGS = 30
MAX_INDEX_PAGES = 60

_KST = dt.timezone(dt.timedelta(hours=9))

# corp_cls는 닫힌 어휘다: Y 유가증권, K 코스닥, N 코넥스, E 기타.
_MARKET_LABELS = {
    "Y": {"ko": "유가증권", "en": "KOSPI"},
    "K": {"ko": "코스닥", "en": "KOSDAQ"},
    "N": {"ko": "코넥스", "en": "KONEX"},
    "E": {"ko": "기타", "en": "Other"},
}


class KrPensionDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    if not config.DART_ENABLED:
        raise KrPensionDisabled("disabled")
    if not config.DART_API_KEY:
        raise KrPensionDisabled("not_configured")


def _provider() -> DartProvider:
    return DartProvider(
        config.DART_API_KEY,
        timeout=config.DART_TIMEOUT,
        retries=config.DART_RETRIES,
        request_interval=config.DART_REQUEST_INTERVAL,
    )


def _iso_date(value: str | None) -> str | None:
    """list.json은 YYYYMMDD, majorstock은 YYYY-MM-DD — 둘 다 ISO로 통일한다."""
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text or None


def refresh(provider: DartProvider | None = None, *, today: dt.date | None = None) -> dict:
    """창 전체를 걷어 국민연금 제출분만 남기고 상세를 붙여 저장한다."""
    _require_lane()
    provider = provider or _provider()
    today = today or dt.datetime.now(_KST).date()
    begin = today - dt.timedelta(days=WINDOW_DAYS)

    rows, truncated = provider.fetch_filing_index(
        detail_type=DETAIL_TYPE_MAJOR_HOLDINGS,
        bgn_de=begin.strftime("%Y%m%d"),
        end_de=today.strftime("%Y%m%d"),
        max_pages=MAX_INDEX_PAGES,
    )

    seen: set[str] = set()
    everyone: list[dict[str, Any]] = []
    for row in rows:
        if row["rcept_no"] in seen:
            continue
        seen.add(row["rcept_no"])
        everyone.append(row)
    everyone.sort(key=lambda row: (row["rcept_dt"], row["rcept_no"]), reverse=True)
    nps = [row for row in everyone if REPORTER_KEYWORD in row["flr_nm"]]
    kept = nps[:MAX_FILINGS]
    kept_all = everyone[:kr_holdings.MAX_FILINGS]

    # 상세는 회사당 한 번: majorstock 응답이 그 회사의 전 보고서를 담으므로
    # rcept_no로 조인한다. 실패한 회사의 수치는 null로 남는다 — 만들어내지 않는다.
    # 두 산출물(국민연금·전체)의 회사 합집합을 한 번에 걷는다.
    details: dict[str, dict[str, Any]] = {}
    detail_failed = 0
    for corp_code in dict.fromkeys(row["corp_code"] for row in [*kept, *kept_all]):
        try:
            for holding in provider.fetch_major_holdings(corp_code):
                details[holding["rcept_no"]] = holding
        except RateLimited:
            detail_failed += 1
            log.warning("DART 허용량 — 남은 대량보유 상세는 다음 주기에")
            break
        except (DataUnavailable, DataError) as exc:
            detail_failed += 1
            log.warning("대량보유 상세 조회 실패 %s: %s", corp_code, exc)

    def _filing_row(row: dict[str, Any]) -> dict[str, Any]:
        holding = details.get(row["rcept_no"])
        return {
            "rcept_no": row["rcept_no"],
            "report_date": _iso_date(row["rcept_dt"]),
            "company": row["corp_name"],
            "stock_code": row["stock_code"] or None,
            "market": _MARKET_LABELS.get(row["corp_cls"]),
            "filing_name": row["report_nm"],
            "report_type": holding["report_type"] if holding else None,
            "reporter": holding["reporter"] if holding else row["flr_nm"],
            "shares": holding["shares"] if holding else None,
            "shares_change": holding["shares_change"] if holding else None,
            "ratio": holding["ratio"] if holding else None,
            "ratio_change": holding["ratio_change"] if holding else None,
            "reason": holding["reason"] if holding else None,
            "report_url": DART_REPORT_URL.format(rcept_no=row["rcept_no"]),
            "detail_status": "ok" if holding else "unavailable",
        }

    filings = [_filing_row(row) for row in kept]

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "reporter": {"ko": "국민연금공단", "en": "National Pension Service"},
        "window": {
            "from": begin.isoformat(),
            "to": today.isoformat(),
            "days": WINDOW_DAYS,
            "truncated": truncated,
        },
        "filings": filings,
        "count": len(filings),
        "total_in_window": len(nps),
        "basis_ko": (
            "자본시장법 5% 룰에 따른 주식등의 대량보유 상황보고 중 국민연금공단 "
            "제출분을 그대로 옮깁니다. 각 행은 보고서 단위의 보유비율과 증감이며, "
            "일별 매매 내역이 아닙니다. 국민연금은 통상 한 달치 변동을 월초에 "
            "일괄 보고합니다."
        ),
        "basis_en": (
            "Large-holding (5% rule) reports filed by the National Pension Service, "
            "relayed verbatim from DART. Each row is a report-level holding ratio "
            "and its change, not daily trades. The NPS usually files a month of "
            "changes in one early-month batch."
        ),
        "source": {
            "provider": DART_PROVIDER_ID,
            "provider_name": DART_PUBLISHER,
            "publisher": DART_PUBLISHER,
            "publisher_url": DART_PUBLISHER_URL,
            "url": DART_TERMS_URL,
            "notice": DART_ATTRIBUTION,
            "notice_en": DART_ATTRIBUTION_EN,
        },
        "rights": {"status": "approved", "notice": DART_ATTRIBUTION},
    }
    store.save_report(CACHE_KEY, payload)

    # 같은 크롤의 두 번째 산출물: 전체 보고자 lane.
    kr_holdings.save_payload(
        [_filing_row(row) for row in kept_all],
        {"from": begin.isoformat(), "to": today.isoformat(),
         "days": WINDOW_DAYS, "truncated": truncated},
        total=len(everyone),
    )
    return {
        "filings": len(filings),
        "holdings": len(kept_all),
        "total_in_window": len(nps),
        "detail_failed": detail_failed,
        "truncated": truncated,
    }


def get_filings() -> dict:
    """저장된 결과만 읽는다. 요청 경로에서 DART를 호출하지 않는다."""
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("NPS major-holding filings not collected yet")
    return cached
