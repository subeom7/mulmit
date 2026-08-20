"""통합 신호 피드 — "지금 일어나는 일"을 한 줄기로.

새 수집이 하나도 없다: 이미 저장된 다섯 lane(미 8-K, 한 주요사항보고, 하원
PTR, 국민연금 5%, 경제 캘린더)을 읽어 시간순 하나의 목록으로 재조립할 뿐이다.
소스 하나가 닫혀 있거나 비어 있으면 그 소스만 조용히 빠진다(fail-soft) —
피드는 지금 존재하는 것만 말한다.

정직성: 각 항목은 자기 lane의 원문 표현을 그대로 쓰고(8-K Item 표준 제목,
주요사항보고 원문 제목, PTR 금액 구간), 피드 전체가 수집 주기 기반이며 실시간
속보가 아님을 basis로 동봉한다. 미래 일정(캘린더)은 과거 항목과 섞지 않고
`upcoming`으로 분리한다 — 일어난 일과 일어날 일은 다른 종류의 문장이다.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, econ_calendar, kr_events, kr_pension, kr_press, news_feed, store, us_ptr

log = logging.getLogger(__name__)

MAX_ITEMS = 30
# 지수 급변: 3% 계단(±3·6·9…)을 "넘는 순간"만 이벤트다. 같은 구간에 머무는
# 동안은 반복하지 않고, 회복 방향의 계단 통과도 똑같이 기록한다.
MOVE_STEP = 3.0
# 회복 히스테리시스: 이탈은 선을 넘는 순간이 뉴스지만, 회복은 선 안쪽으로
# 이만큼 들어와야 인정한다 — 선 위 진동이 같은 뉴스를 반복 생성하는 것을
# 막는다(2026-08-20 아침 -3% 선 4연발 실측이 이 상수의 이유다).
MOVE_REARM = 0.5
# 워커 동시 기록 대비: 같은 선·같은 방향 이벤트가 이 간격 안에 또 오면 중복이다.
MOVE_DEDUPE_MINUTES = 10
MOVE_STATE_KEY = "feed_index_move_v1"
MOVE_HISTORY = 8
MAX_UPCOMING = 5

_KST = dt.timezone(dt.timedelta(hours=9))


def _hub_link(symbol: str | None, *, korean: bool) -> str | None:
    text = str(symbol or "").strip().upper()
    if not text:
        return None
    if korean and text.isdigit() and len(text) == 6:
        return f"/stock/{text}"
    if not korean and text.isalpha():
        return f"/stock/{text}"
    return None


def _us_8k_items() -> list[dict[str, Any]]:
    from .us_events import _items_payload

    items = []
    for row in store.load_recent_events(limit=12):
        filed = row["filed_at"]
        filed_iso = filed.isoformat() if isinstance(filed, dt.date) else str(filed)
        labels = _items_payload(row.get("items"))
        summary_ko = " · ".join(item["label"]["ko"] for item in labels) or "8-K"
        summary_en = " · ".join(item["label"]["en"] for item in labels) or "8-K"
        items.append({
            "at": str(row.get("accepted_at") or filed_iso),
            "date": filed_iso,
            "kind": "us_8k",
            "region": "us",
            "symbol": row["ticker"],
            "title": {
                "ko": f"{row['ticker']} 8-K — {summary_ko}",
                "en": f"{row['ticker']} 8-K — {summary_en}",
            },
            "url": row["url"],
            "hub": _hub_link(row["ticker"], korean=False),
        })
    return items


def _kr_material_items() -> list[dict[str, Any]]:
    blob = store.load_report(kr_events.CACHE_KEY, config.REPORT_TTL * 2)
    items = []
    for event in (blob or {}).get("events", [])[:12]:
        items.append({
            "at": str(event.get("filed_at") or ""),
            "date": str(event.get("filed_at") or ""),
            "kind": "kr_material",
            "region": "kr",
            "symbol": event.get("stock_code"),
            "title": {
                "ko": f"{event.get('company')} — {event.get('report_name')}",
                "en": f"{event.get('company')} — {event.get('report_name')}",
            },
            "url": event.get("url"),
            "hub": _hub_link(event.get("stock_code"), korean=True),
        })
    return items


def _us_ptr_items() -> list[dict[str, Any]]:
    blob = store.load_report(us_ptr.CACHE_KEY, config.REPORT_TTL * 2)
    items = []
    for filing in (blob or {}).get("filings", [])[:8]:
        count = filing.get("transaction_count") or len(filing.get("transactions") or [])
        tickers = sorted({
            str(tx.get("ticker") or "").upper()
            for tx in (filing.get("transactions") or [])
            if tx.get("ticker")
        })
        shown = ", ".join(tickers[:4]) + ("…" if len(tickers) > 4 else "")
        detail_ko = f"거래 {count}건" + (f" — {shown}" if shown else "")
        detail_en = f"{count} transactions" + (f" — {shown}" if shown else "")
        items.append({
            "at": str(filing.get("filed_date") or ""),
            "date": str(filing.get("filed_date") or ""),
            "kind": "us_ptr",
            "region": "us",
            "symbol": tickers[0] if len(tickers) == 1 else None,
            "title": {
                "ko": f"{filing.get('name')} 의원 주식거래 보고 — {detail_ko}",
                "en": f"Rep. {filing.get('name')} PTR — {detail_en}",
            },
            "url": filing.get("pdf_url"),
            "hub": _hub_link(tickers[0], korean=False) if len(tickers) == 1 else None,
        })
    return items


def _kr_pension_items() -> list[dict[str, Any]]:
    blob = store.load_report(kr_pension.CACHE_KEY, config.REPORT_TTL * 2)
    items = []
    for filing in (blob or {}).get("filings", [])[:8]:
        change = filing.get("ratio_change")
        move_ko = f" ({change:+.2f}%p)" if isinstance(change, (int, float)) else ""
        items.append({
            "at": str(filing.get("report_date") or ""),
            "date": str(filing.get("report_date") or ""),
            "kind": "kr_pension",
            "region": "kr",
            "symbol": filing.get("stock_code"),
            "title": {
                "ko": f"국민연금 5% 공시 — {filing.get('company')}{move_ko}",
                "en": f"NPS 5% filing — {filing.get('company')}{move_ko}",
            },
            "url": filing.get("report_url"),
            "hub": _hub_link(filing.get("stock_code"), korean=True),
        })
    return items


def _move_bucket(percent: float) -> int:

    if abs(percent) < MOVE_STEP:
        return 0
    magnitude = int(abs(percent) // MOVE_STEP)
    return magnitude if percent > 0 else -magnitude


def _index_move_items() -> list[dict[str, Any]]:
    """코스피 200 퍼프의 종가 대비 %가 3% 계단을 통과한 순간들.

    피드 요청이 곧 샘플링이다(응답 캐시 5분): 상태 블롭에 마지막 구간을 두고,
    구간이 바뀐 요청에서만 이벤트를 앞에 쌓는다. 서로 다른 워커의 동시 기록은
    같은 구간 비교라 최악의 경우 중복 한 건 — 만들어낸 수치는 없다.
    """
    from .kr_overnight import build_kr_overnight

    state = store.load_report(MOVE_STATE_KEY, 90 * 24 * 3600) or {"bucket": 0, "events": []}
    try:
        kro = build_kr_overnight()
        card = next(c for c in kro["cards"] if c["id"] == "kospi_200")
        percent = card["implied"]["vs_official_percent"]
        official_date = (card.get("official") or {}).get("date")
    except Exception as exc:  # noqa: BLE001 - 시세 실패 시 저장된 이력만 보여준다
        log.warning("피드: 지수 급변 샘플 실패: %s", exc)
        percent = None
        official_date = None
    if percent is not None:
        bucket = _move_bucket(float(percent))
        previous = int(state.get("bucket", 0))
        recovering = abs(bucket) < abs(previous)
        # 회복은 방금 통과한 선 안쪽으로 MOVE_REARM 이상 들어와야 확정 —
        # 그 전까지는 구간이 안 바뀐 것으로 본다(이탈은 즉시 뉴스).
        settled = (
            not recovering
            or abs(float(percent)) <= (abs(bucket) + 1) * MOVE_STEP - MOVE_REARM
        )
        if bucket != previous and settled:
            line = int(max(abs(bucket), abs(previous))) * MOVE_STEP
            direction_ko = "이탈" if not recovering else "회복"
            direction_en = "crossed below" if bucket < previous else "crossed above"
            sign = "-" if (bucket < 0 or (bucket == 0 and previous < 0)) else "+"
            now = dt.datetime.now(_KST)
            line_text = f"{sign}{line:g}%"
            newest = next(iter(state.get("events", [])), None)
            repeated = False
            if newest and newest.get("line") == line_text and newest.get("direction_ko") == direction_ko:
                try:
                    newest_at = dt.datetime.fromisoformat(str(newest.get("at")))
                    repeated = (now - newest_at) <= dt.timedelta(minutes=MOVE_DEDUPE_MINUTES)
                except ValueError:
                    repeated = False
            if not repeated:
                state["events"] = ([{
                    "at": now.isoformat(timespec="minutes"),
                    "percent": round(float(percent), 2),
                    "line": line_text,
                    "direction_ko": direction_ko,
                    "direction_en": direction_en,
                    "official_date": official_date,
                }] + list(state.get("events", [])))[:MOVE_HISTORY]
            state["bucket"] = bucket
            store.save_report(MOVE_STATE_KEY, state)
    items = []
    for event in state.get("events", []):
        date_part = str(event.get("at", ""))[:10]
        items.append({
            "at": str(event.get("at", "")),
            "date": date_part,
            "kind": "index_move",
            "region": "kr",
            "symbol": None,
            "title": {
                "ko": (
                    f"코스피 200 퍼프 {event.get('line')} 선 {event.get('direction_ko')} "
                    f"(당시 {event.get('percent'):+.1f}% · {event.get('official_date')} 종가 대비)"
                ),
                "en": (
                    f"KOSPI 200 perp {event.get('direction_en')} the {event.get('line')} line "
                    f"(at {event.get('percent'):+.1f}% vs the {event.get('official_date')} close)"
                ),
            },
            "url": "/kr",
            "hub": None,
        })
    return items


def _kr_press_items() -> list[dict[str, Any]]:
    blob = store.load_report(kr_press.CACHE_KEY, config.REPORT_TTL * 2)
    items = []
    for entry in (blob or {}).get("items", [])[:8]:
        items.append({
            "at": str(entry.get("at") or ""),
            "date": str(entry.get("at") or "")[:10],
            "kind": "kr_press",
            "region": "kr",
            "symbol": None,
            "title": {
                "ko": f"[{entry.get('agency')}] {entry.get('title')}",
                "en": f"[{entry.get('agency_en')}] {entry.get('title')}",
            },
            "url": entry.get("url"),
            "hub": None,
            # 금융위 피드는 게시일이 없어 수집 시각 기준 — 그 사실을 행에 남긴다.
            "date_basis": entry.get("date_basis"),
        })
    return items


def _news_items() -> list[dict[str, Any]]:
    blob = store.load_report(news_feed.CACHE_KEY, config.REPORT_TTL * 2)
    items = []
    for article in (blob or {}).get("articles", [])[:8]:
        tags = article.get("tags") or []
        items.append({
            "at": str(article.get("seendate") or ""),
            "date": str(article.get("seendate") or "")[:10],
            "kind": "news",
            # GDELT 축은 영문 매체 기반 — 한국 종목 태그가 붙은 기사만 한국으로 분류한다.
            "region": "kr" if any(str(tag.get("symbol", "")).isdigit() for tag in tags) else "us",
            "symbol": tags[0]["symbol"] if tags else None,
            "title": {"ko": article.get("title"), "en": article.get("title")},
            "url": article.get("url"),
            "hub": tags[0].get("hub") if tags else None,
            "domain": article.get("domain"),
            "also_on": article.get("also_on") or 0,
            "tags": tags,
        })
    return items


def _upcoming_items(today: dt.date) -> list[dict[str, Any]]:
    try:
        calendar = econ_calendar.build_calendar()
    except Exception as exc:  # noqa: BLE001 - 캘린더 실패가 피드를 막지 않는다
        log.warning("피드: 캘린더 소스 실패: %s", exc)
        return []
    items = []
    for event in calendar.get("events", []):
        date_text = str(event.get("date") or "")
        try:
            when = dt.date.fromisoformat(date_text)
        except ValueError:
            continue
        if when < today:
            continue
        items.append({
            "at": date_text,
            "date": date_text,
            "kind": "calendar",
            "d_day": (when - today).days,
            "title": event.get("name"),
            "url": event.get("source_url"),
            "region": event.get("region"),
        })
        if len(items) >= MAX_UPCOMING:
            break
    return items


def build_feed(*, today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.datetime.now(_KST).date()
    items: list[dict[str, Any]] = []
    for source in (_us_8k_items, _kr_material_items, _us_ptr_items, _kr_pension_items, _index_move_items, _news_items, _kr_press_items):
        try:
            items.extend(source())
        except Exception as exc:  # noqa: BLE001 - 소스 하나의 실패는 그 소스만 지운다
            log.warning("피드 소스 실패 %s: %s", source.__name__, exc)
    # ISO 문자열 내림차순: 같은 날짜에서는 시각이 붙은 항목(8-K acceptance)이
    # 날짜뿐인 항목보다 뒤가 아니라 앞에 오도록 문자열 비교가 그대로 맞는다.
    items = [item for item in items if item["at"]]
    items.sort(key=lambda item: item["at"], reverse=True)
    kept = items[:MAX_ITEMS]
    attribution = None
    if any(item["kind"] == "news" for item in kept):
        from .providers.gdelt import GDELT_ATTRIBUTION, GDELT_ATTRIBUTION_KO, GDELT_PUBLISHER_URL

        attribution = {
            "text": GDELT_ATTRIBUTION,
            "text_ko": GDELT_ATTRIBUTION_KO,
            "url": GDELT_PUBLISHER_URL,
        }
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "items": kept,
        "attribution": attribution,
        "upcoming": _upcoming_items(today),
        "count": min(len(items), MAX_ITEMS),
        "basis_ko": (
            "기존 공시·일정 lane의 재조립입니다 — 8-K와 주요사항보고는 원문 제목, "
            "PTR 금액은 공시 구간 그대로. 지수 급변은 퍼프 참고가의 3% 계단 통과 기록입니다. "
            "뉴스·보도자료·주요사항은 약 15분, 나머지는 시간 단위 수집 주기라 "
            "실시간 속보가 아니며, 비어 있는 소스는 표시되지 않습니다."
        ),
        "basis_en": (
            "A reassembly of existing filing and schedule lanes — 8-K and Korean "
            "material-event titles verbatim, PTR amounts as disclosed ranges. "
            "News, press releases and Korean material events refresh about every "
            "15 minutes, other lanes hourly or slower — not a live wire; "
            "empty sources simply do not appear."
        ),
    }
