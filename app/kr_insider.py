"""국내 임원·주요주주 소유상황 보고 — DART lane의 요청 경로.

미국 EDGAR 패널과 화면상 동형을 이루는 한국 쪽 절반이다. 구조는
:mod:`app.kr_stocks`와 같다: 매핑은 로컬 테이블을 먼저 읽고, 캐시 미스에서만
프로세스 전역 잠금 아래 한 번 조회하며, 결과는 저장해 이후 요청을 DB 읽기로
만든다.

표시 원칙도 EDGAR와 같다 — 보고된 값을 가공 없이 전달한다. 다른 점 하나는
데이터의 단위다: elestock은 보고서 단위의 소유수량·순증감이지 Form 4처럼
개별 매매(단가 포함)가 아니므로, 합산 요약을 만들지 않고 그 사실을 basis
문장으로 응답에 싣는다.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from . import config, store
from .providers.base import DataError, DataUnavailable, RateLimited
from .providers.dart import (
    DART_ATTRIBUTION,
    DART_ATTRIBUTION_EN,
    DART_PROVIDER_ID,
    DART_PUBLISHER,
    DART_PUBLISHER_URL,
    DART_TERMS_URL,
    DartProvider,
)

log = logging.getLogger(__name__)

MAX_REPORTS = 50
_fetch_lock = threading.Lock()
_recent_failures: dict[str, float] = {}
FAILURE_MEMO_SECONDS = 60.0


class KrInsiderDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


class KrInsiderUnknown(RuntimeError):
    """종목코드가 DART 상장 법인 매핑에 없다."""


def _require_lane() -> None:
    if not config.DART_ENABLED:
        raise KrInsiderDisabled("disabled")
    if not config.DART_API_KEY:
        raise KrInsiderDisabled("not_configured")


def _provider() -> DartProvider:
    return DartProvider(
        config.DART_API_KEY,
        timeout=config.DART_TIMEOUT,
        retries=config.DART_RETRIES,
        request_interval=config.DART_REQUEST_INTERVAL,
    )


def ensure_corp_codes() -> None:
    """상장 법인코드 매핑이 없으면 한 번 받아 둔다. 배치가 주기 갱신한다."""
    if not store.dart_corp_codes_stale(config.DART_CORP_MAX_AGE):
        return
    with _fetch_lock:
        if not store.dart_corp_codes_stale(config.DART_CORP_MAX_AGE):
            return
        rows = _provider().fetch_corp_codes()
        saved = store.save_dart_corp_codes(rows)
        log.info("DART 법인코드 매핑 갱신: %d상장사", saved)


def _cache_key(corp_code: str) -> str:
    return f"dart_elestock_{corp_code}"


def get_reports(stock_code: str) -> dict[str, Any]:
    """한 종목의 소유상황 보고 목록. DB·캐시 우선, 미스에서만 단발 조회."""
    _require_lane()
    stock_code = stock_code.strip().upper()

    ensure_corp_codes()
    mapping = store.get_dart_corp_code(stock_code)
    if mapping is None:
        raise KrInsiderUnknown(stock_code)
    corp_code = mapping["corp_code"]

    cached = store.load_report(_cache_key(corp_code), config.DART_MAX_AGE)
    if cached is None:
        failed_at = _recent_failures.get(corp_code, 0.0)
        if time.time() - failed_at > FAILURE_MEMO_SECONDS:
            with _fetch_lock:
                cached = store.load_report(_cache_key(corp_code), config.DART_MAX_AGE)
                if cached is None:
                    try:
                        reports = _provider().fetch_ownership_reports(corp_code)
                        cached = {"reports": reports, "fetched_at": time.time()}
                        store.save_report(_cache_key(corp_code), cached)
                        _recent_failures.pop(corp_code, None)
                    except (DataUnavailable, RateLimited, DataError) as exc:
                        _recent_failures[corp_code] = time.time()
                        log.warning("DART 소유보고 조회 실패 %s: %s", corp_code, exc)
    if cached is None:
        raise DataUnavailable(f"DART reports unavailable for {stock_code}")

    reports = sorted(
        cached.get("reports") or [],
        key=lambda row: (row.get("report_date") or "", row.get("rcept_no") or ""),
        reverse=True,
    )[:MAX_REPORTS]

    return {
        "code": stock_code,
        "company": mapping["corp_name"],
        "corp_code": corp_code,
        "reports": reports,
        "count": len(reports),
        "basis_ko": (
            "임원·주요주주 특정증권등 소유상황 보고를 그대로 옮깁니다. 각 행은 보고서 "
            "단위의 소유수량과 순증감이며, 개별 매매 내역이나 체결 단가가 아닙니다. "
            "비율은 공시 원문 기준(소수점 2자리)이라 대형주 임원 지분은 0.005% 미만이면 "
            "<0.01%로 표시됩니다."
        ),
        "basis_en": (
            "Officer and major-shareholder ownership reports relayed verbatim. Each row "
            "is a report-level holding and net change, not individual trades or prices. "
            "Ratios follow the filing's own two-decimal precision, so large-cap officer "
            "stakes below 0.005% show as <0.01%."
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
