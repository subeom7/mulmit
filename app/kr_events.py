"""한국 기업 공시 속보 — 신호 피드의 한국 축. 미국 8-K 피드의 대칭이다.

DART 공시검색에서 **주요사항보고서(pblntf_ty=B)** 접수 목록을 그대로 옮긴다.
주요사항보고서는 합병·증자·소송·영업정지 같은 중요 이벤트의 법정 보고라
미국 8-K의 등가물이다. 제목(report_nm)은 공시 원문 제목을 그대로 쓰고,
아무것도 분류하거나 요약하지 않는다 — 내용 판단은 원문 링크의 몫이다.

수집은 ingest 배치 전용이다(kr_pension과 같은 판단): web은 저장된 결과만
읽고, 첫 배치 전에는 503으로 답한다. 갱신은 수집 주기를 따르므로 실시간
속보가 아니며 그 사실을 basis로 동봉한다. 유가증권·코스닥 상장사만 남긴다
(비상장·기타법인의 주요사항보고는 종목 화면 맥락이 없다).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, store
from .providers.base import DataUnavailable
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

CACHE_KEY = "dart_kr_events_v1"
BROAD_TYPE_MATERIAL = "B"  # 공시검색 대분류: 주요사항보고
WINDOW_DAYS = 3
MAX_EVENTS = 40
MAX_INDEX_PAGES = 12
_LISTED_MARKETS = ("Y", "K")

_KST = dt.timezone(dt.timedelta(hours=9))

_MARKET_LABELS = {
    "Y": {"ko": "유가증권", "en": "KOSPI"},
    "K": {"ko": "코스닥", "en": "KOSDAQ"},
}


class KrEventsDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    if not config.DART_ENABLED:
        raise KrEventsDisabled("disabled")
    if not config.DART_API_KEY:
        raise KrEventsDisabled("not_configured")


def _provider() -> DartProvider:
    return DartProvider(
        config.DART_API_KEY,
        timeout=config.DART_TIMEOUT,
        retries=config.DART_RETRIES,
        request_interval=config.DART_REQUEST_INTERVAL,
    )


def _iso_date(value: str | None) -> str | None:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text or None


def refresh(provider: DartProvider | None = None, *, today: dt.date | None = None) -> dict:
    """최근 창의 주요사항보고 접수 목록을 걷어 상장사분만 저장한다."""
    _require_lane()
    provider = provider or _provider()
    today = today or dt.datetime.now(_KST).date()
    begin = today - dt.timedelta(days=WINDOW_DAYS)

    rows, truncated = provider.fetch_filing_index(
        broad_type=BROAD_TYPE_MATERIAL,
        bgn_de=begin.strftime("%Y%m%d"),
        end_de=today.strftime("%Y%m%d"),
        max_pages=MAX_INDEX_PAGES,
    )

    seen: set[str] = set()
    listed: list[dict[str, Any]] = []
    for row in rows:
        if row["corp_cls"] not in _LISTED_MARKETS or not (row["stock_code"] or "").strip():
            continue
        if row["rcept_no"] in seen:
            continue
        seen.add(row["rcept_no"])
        listed.append(row)
    listed.sort(key=lambda row: (row["rcept_dt"], row["rcept_no"]), reverse=True)
    kept = listed[:MAX_EVENTS]

    events = [
        {
            "rcept_no": row["rcept_no"],
            "filed_at": _iso_date(row["rcept_dt"]),
            "company": row["corp_name"],
            "stock_code": row["stock_code"],
            "market": _MARKET_LABELS.get(row["corp_cls"]),
            # 공시 원문 제목 그대로. "주요사항보고서(유상증자결정)"처럼 이벤트가
            # 제목에 이미 들어 있어 분류를 만들 필요가 없다.
            "report_name": row["report_nm"],
            "url": DART_REPORT_URL.format(rcept_no=row["rcept_no"]),
        }
        for row in kept
    ]

    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "window": {
            "from": begin.isoformat(),
            "to": today.isoformat(),
            "days": WINDOW_DAYS,
            "truncated": truncated,
        },
        "events": events,
        "count": len(events),
        "total_in_window": len(listed),
        "basis_ko": (
            "금융감독원 DART 접수 목록의 주요사항보고서(유가증권·코스닥 상장사)를 "
            "그대로 옮깁니다. 제목은 공시 원문 제목이며, 수집 주기(약 1시간)로 "
            "갱신되는 목록이라 실시간 속보가 아닙니다. 내용 판단은 원문에서 하세요."
        ),
        "basis_en": (
            "Material-event reports (주요사항보고서) from the DART filing index for "
            "KOSPI and KOSDAQ listings, relayed verbatim. Titles are the filings' own "
            "titles; the list refreshes on the collection cycle (about hourly), not "
            "live. Read the filing itself for substance."
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
    return {"events": len(events), "total_in_window": len(listed), "truncated": truncated}


def get_events() -> dict:
    """저장된 결과만 읽는다. 요청 경로에서 DART를 호출하지 않는다."""
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("Korean material-event filings not collected yet")
    return cached
