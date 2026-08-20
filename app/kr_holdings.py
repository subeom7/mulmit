"""대량보유(5% 룰) 공시 — 전체 보고자 lane.

kr_pension lane의 일반화다. 같은 D001 크롤(주식등의 대량보유 상황보고)이
국민연금 필터를 거치기 전의 **모든 보고자** — 자산운용사·행동주의 펀드·
외국계 펀드·대주주 — 를 여기 담는다. 크롤은 kr_pension.refresh()가 한 번만
돌고 두 blob을 함께 저장한다: 같은 걷기, 넓은 서빙.

정직성: 보고자명·보유비율·증감은 공시값 그대로이고(빠진 상세는 null),
보고 기한이 5영업일이므로 보고일 ≠ 변동일임을 basis에 명시한다. "기관이
담는 중" 류의 시그널 문장은 만들지 않는다 — 그건 독자의 몫이다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import config, store
from .providers.base import DataUnavailable
from .providers.dart import (
    DART_ATTRIBUTION,
    DART_ATTRIBUTION_EN,
    DART_PROVIDER_ID,
    DART_PUBLISHER,
    DART_PUBLISHER_URL,
    DART_TERMS_URL,
)

CACHE_KEY = "dart_majorstock_v1"
MAX_FILINGS = 40


class KrHoldingsDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    if not config.DART_ENABLED:
        raise KrHoldingsDisabled("disabled")
    if not config.DART_API_KEY:
        raise KrHoldingsDisabled("not_configured")


def save_payload(filings: list[dict[str, Any]], window: dict[str, Any], total: int) -> None:
    """kr_pension.refresh()의 크롤 결과로 전체 보고자 blob을 만든다."""
    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "window": window,
        "filings": filings,
        "count": len(filings),
        "total_in_window": total,
        "basis_ko": (
            "자본시장법 5% 룰에 따른 주식등의 대량보유 상황보고 전체를 그대로 "
            "옮깁니다(모든 보고자). 각 행은 보고서 단위의 보유비율과 증감이며 "
            "일별 매매가 아닙니다. 보고 기한이 5영업일이라 보고일은 변동일과 "
            "다를 수 있습니다. 상세 미확보 수치는 비워 둡니다 — 만들지 않습니다."
        ),
        "basis_en": (
            "Every large-holding (5% rule) report in the window, all filers, "
            "relayed verbatim from DART. Each row is a report-level holding ratio "
            "and its change, not daily trades; the filing deadline is five business "
            "days, so the report date can trail the change. Missing detail values "
            "stay null."
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


def get_holdings() -> dict:
    """저장된 결과만 읽는다. 요청 경로에서 DART를 호출하지 않는다."""
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("major-holding filings not collected yet")
    return cached
