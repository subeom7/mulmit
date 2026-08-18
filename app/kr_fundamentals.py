"""국내 상장사 연간 재무제표 — DART 주요계정(fnlttSinglAcnt)의 원문 전달.

미국 EDGAR 재무 패널(:mod:`app.us_fundamentals`)의 한국 대응물이다. 구조는
:mod:`app.kr_insider`와 같다: 요청 기반 조회, 캐시 미스에서만 프로세스 전역
잠금 아래 한 번 조회, 이후 요청은 저장소 읽기.

**연간(사업보고서)만 다룬다.** DART 분기 보고서의 손익 항목은 누적(YTD)과
분기값 구분이 API 응답에 없어, 미국 쪽처럼 기간 길이로 가를 수 없다 — 추측
대신 범위를 좁힌다. 한 요청이 당기·전기·전전기 세 해를 담으므로 두 요청이면
최대 6개 사업연도가 나온다.

연결(CFS)을 우선하고 없으면 별도(OFS)를 쓰며, 어느 쪽을 썼는지 응답에
명시한다. 금융사는 매출액 대신 영업수익을 쓰므로 계정명 사다리를 두고, 실제
사용한 계정명을 그대로 싣는다. 파생값은 마진 둘뿐이다(이익 ÷ 매출, 같은
보고서의 두 값).
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Any

from . import config, store
from .kr_insider import ensure_corp_codes
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

ANNUAL_REPORT_CODE = "11011"
MAX_YEARS = 5
# 계정명 사다리: 일반 제조업 → 금융업 순.
ACCOUNT_LADDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("revenue", ("매출액", "영업수익")),
    ("operating_income", ("영업이익", "영업이익(손실)")),
    ("net_income", ("당기순이익(손실)", "당기순이익", "연결당기순이익")),
    ("assets", ("자산총계",)),
    ("equity", ("자본총계",)),
)

_KST = dt.timezone(dt.timedelta(hours=9))
_fetch_lock = threading.Lock()
_recent_failures: dict[str, float] = {}
FAILURE_MEMO_SECONDS = 60.0


class KrFundamentalsDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


class KrFundamentalsUnknown(RuntimeError):
    """종목코드가 DART 상장 법인 매핑에 없다."""


def _require_lane() -> None:
    if not config.DART_ENABLED:
        raise KrFundamentalsDisabled("disabled")
    if not config.DART_API_KEY:
        raise KrFundamentalsDisabled("not_configured")


def _provider() -> DartProvider:
    return DartProvider(
        config.DART_API_KEY,
        timeout=config.DART_TIMEOUT,
        retries=config.DART_RETRIES,
        request_interval=config.DART_REQUEST_INTERVAL,
    )


def _cache_key(corp_code: str) -> str:
    return f"dart_fund_{corp_code}"


def _pick(rows: list[dict[str, Any]], fs_div: str, names: tuple[str, ...]) -> dict[str, Any] | None:
    for name in names:
        for row in rows:
            if row["fs_div"] == fs_div and row["sj_div"] in ("BS", "IS", "CIS") \
                    and row["account_nm"] == name:
                return row
    return None


def _year_rows(rows: list[dict[str, Any]], bsns_year: int) -> list[dict[str, Any]]:
    """한 응답(3개년)을 사업연도별 행으로 편다. 연결 우선, 없으면 별도."""
    fs_div = "CFS" if any(r["fs_div"] == "CFS" for r in rows) else "OFS"
    picked: dict[str, dict[str, Any] | None] = {
        metric: _pick(rows, fs_div, names) for metric, names in ACCOUNT_LADDERS
    }
    out = []
    for offset, column in ((0, "thstrm_amount"), (1, "frmtrm_amount"), (2, "bfefrmtrm_amount")):
        year = bsns_year - offset
        values = {
            metric: (row.get(column) if row else None)
            for metric, row in picked.items()
        }
        if all(value is None for value in values.values()):
            continue
        revenue = values.get("revenue")
        operating = values.get("operating_income")
        net = values.get("net_income")
        out.append({
            "year": year,
            "fs_div": fs_div,
            "revenue": revenue,
            "revenue_account": (picked["revenue"] or {}).get("account_nm") if picked.get("revenue") else None,
            "operating_income": operating,
            "net_income": net,
            "assets": values.get("assets"),
            "equity": values.get("equity"),
            "operating_margin": _margin(operating, revenue),
            "net_margin": _margin(net, revenue),
            "report_url": DART_REPORT_URL.format(rcept_no=(picked["revenue"] or {}).get("rcept_no"))
            if picked.get("revenue") and (picked["revenue"] or {}).get("rcept_no") else None,
        })
    return out


def _margin(income: float | None, revenue: float | None) -> float | None:
    if income is None or not revenue:
        return None
    return round(income / revenue * 100, 1)


def _fetch_payload(provider: DartProvider, corp_code: str, corp_name: str, code: str) -> dict:
    latest_year = dt.datetime.now(_KST).year - 1
    rows_by_year: dict[int, dict[str, Any]] = {}
    base_year = None
    for candidate in (latest_year, latest_year - 1):
        fetched = provider.fetch_major_accounts(corp_code, candidate, reprt_code=ANNUAL_REPORT_CODE)
        if fetched:
            base_year = candidate
            for row in _year_rows(fetched, candidate):
                rows_by_year[row["year"]] = row
            break
    if base_year is None:
        raise DataUnavailable(f"DART has no annual major accounts for {code}")

    # 한 요청이 3개년이므로, 3년 전 보고서 하나로 최대 6개년을 채운다.
    older = provider.fetch_major_accounts(corp_code, base_year - 3, reprt_code=ANNUAL_REPORT_CODE)
    for row in _year_rows(older, base_year - 3):
        rows_by_year.setdefault(row["year"], row)

    annual = [rows_by_year[year] for year in sorted(rows_by_year, reverse=True)][:MAX_YEARS]
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "code": code,
        "company": corp_name,
        "corp_code": corp_code,
        "unit": "KRW",
        "annual": annual,
        "statement": {"CFS": "연결재무제표", "OFS": "별도재무제표"}.get(
            annual[0]["fs_div"] if annual else "CFS", "연결재무제표"
        ),
        "basis_ko": (
            "DART 사업보고서의 주요계정을 그대로 전달합니다(연간·연결 우선, 없으면 "
            "별도). 분기 손익은 누적·분기 구분이 없어 다루지 않습니다. 파생값은 "
            "마진 둘뿐입니다(이익 ÷ 매출, 같은 보고서의 두 값). 금액 단위 KRW."
        ),
        "basis_en": (
            "Key accounts from DART annual reports, relayed as filed (consolidated "
            "preferred, separate otherwise). Quarterly income lines are omitted "
            "because the API does not distinguish cumulative from in-quarter "
            "figures. The only derived values are the two margins. Amounts in KRW."
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


def get_report(stock_code: str) -> dict[str, Any]:
    """한 종목의 연간 재무 패널. DB·캐시 우선, 미스에서만 단발 조회."""
    _require_lane()
    stock_code = stock_code.strip().upper()

    ensure_corp_codes()
    mapping = store.get_dart_corp_code(stock_code)
    if mapping is None:
        raise KrFundamentalsUnknown(stock_code)
    corp_code = mapping["corp_code"]

    cached = store.load_report(_cache_key(corp_code), config.DART_MAX_AGE)
    if cached is None:
        failed_at = _recent_failures.get(corp_code, 0.0)
        if time.time() - failed_at > FAILURE_MEMO_SECONDS:
            with _fetch_lock:
                cached = store.load_report(_cache_key(corp_code), config.DART_MAX_AGE)
                if cached is None:
                    try:
                        cached = _fetch_payload(
                            _provider(), corp_code, mapping["corp_name"], stock_code
                        )
                        store.save_report(_cache_key(corp_code), cached)
                        _recent_failures.pop(corp_code, None)
                    except (DataUnavailable, RateLimited, DataError) as exc:
                        _recent_failures[corp_code] = time.time()
                        log.warning("DART 재무 조회 실패 %s: %s", corp_code, exc)
    if cached is None:
        raise DataUnavailable(f"DART fundamentals unavailable for {stock_code}")
    return cached
