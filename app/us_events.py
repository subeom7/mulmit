"""미국 기업 8-K 이벤트 피드 — "실시간 신호 피드"의 미국 축 첫 조각.

행은 내부자 수집이 이미 받는 EDGAR submissions 응답에서 함께 뽑혀 저장된
것이라, 이 피드를 위한 수집 요청은 하나도 없다. 커버리지는 내부자 lane과
같다(시드 + 검색된 티커). 갱신은 수집 주기를 따르므로 실시간 속보가 아니며,
그 사실을 basis로 동봉한다. Item 제목은 공식 번호의 닫힌 매핑으로만 옮기고
모르는 번호는 원문 코드 그대로 나간다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import data_rights, store
from .insider_filings import InsiderDataDisabled, rights_metadata
from .providers.sec_edgar import (
    EVENT_ITEM_LABELS,
    SEC_BASE,
    SEC_PUBLISHER,
    SEC_PUBLISHER_URL,
)

DEFAULT_EVENTS = 30
MAX_EVENTS = 60


def _require_serving() -> None:
    status = data_rights.sec_edgar_status()
    if status != "enabled":
        raise InsiderDataDisabled(status)


def _items_payload(raw: str | None) -> list[dict[str, Any]]:
    payload = []
    for code in str(raw or "").split(","):
        code = code.strip()
        if not code:
            continue
        labels = EVENT_ITEM_LABELS.get(code)
        payload.append({
            "code": code,
            "label": {"en": labels[0], "ko": labels[1]} if labels else {"en": code, "ko": code},
        })
    return payload


def build_events_feed(limit: int = DEFAULT_EVENTS) -> dict[str, Any]:
    _require_serving()
    rows = store.load_recent_events(min(max(limit, 1), MAX_EVENTS))
    events = [
        {
            "ticker": row["ticker"],
            "company": row.get("company_name") or row["ticker"],
            "form_type": row["form_type"],
            "filed_at": row["filed_at"].isoformat() if isinstance(row["filed_at"], dt.date) else row["filed_at"],
            "accepted_at": row.get("accepted_at"),
            "items": _items_payload(row.get("items")),
            "url": row["url"],
        }
        for row in rows
    ]
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "events": events,
        "count": len(events),
        "basis": {
            "ko": (
                "커버 중인 티커의 8-K(주요 이벤트 보고) 공시입니다. 수집 주기(약 1시간)로 "
                "갱신되며 실시간 속보가 아닙니다. 제목은 공식 Item 번호의 표준 제목이고, "
                "내용 판단은 원문 링크로 확인하세요."
            ),
            "en": (
                "8-K current reports for covered tickers, refreshed on the collection "
                "cycle (about hourly) — not a live wire. Titles are the standard Item "
                "headings; read the filing itself for substance."
            ),
        },
        "source": {
            "provider": "sec_edgar",
            "publisher": SEC_PUBLISHER,
            "publisher_url": SEC_PUBLISHER_URL,
            "url": f"{SEC_BASE}/cgi-bin/browse-edgar?action=getcompany&type=8-K",
            "forms": ["8-K", "8-K/A"],
        },
        "rights": rights_metadata(),
    }
