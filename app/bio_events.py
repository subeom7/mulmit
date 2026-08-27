"""식약처 허가 그 후 — 국내 상장 제약·바이오의 허가 이벤트 주가 추적.

5% 스코어보드(kr_scoring)의 바이오판이다. 범위는 실측(2026-08-27)이 정했다:
워치리스트 국내 12곳만으로는 30일 8건뿐이라 보드가 서지 않고, FDA 승인은
같은 창에 국내 상장 0건이다. 반면 식약처 허가 123건 중 70건이 상장사 이름
매칭으로 붙는다 — 그래서 v1의 이벤트 원천은 **식약처 허가 전체 × 국내 상장
매칭**이고, FDA·자문위는 기존 표시 lane으로 남는다.

수집은 이미 저장된 mfds blob에서 뽑는다 — 이 lane을 위해 상류를 부르지
않는다(같은 걷기, 넓은 서빙). 채점은 kr_scoring의 공용 함수와 같은 규칙
(기준가 동결·(1+fltRt) 연쇄곱·거래정지 감지·미도래 horizon 보류)을 그대로
쓴다 — 두 벌이면 반드시 어긋난다.

이름 매칭의 함정(지수명·켄 피셔 동명이인 클래스)은 두 겹으로 막는다:
정규화 후 **정확 일치**만 쓰고, 정규화 이름이 로스터에서 **유일할 때만**
매칭한다 — 두 상장사가 같은 정규화명이면 매칭하지 않는다(오매칭보다 결측이
낫다). 그 사실을 payload methodology가 말한다.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from . import bio, config, data_rights, store
from .kr_scoring import (
    BASE_WINDOW_DAYS,
    FULL_SCORE_WINDOW_DAYS,
    HORIZONS,
    _as_date,
    _bench_lookup,
    _checkpoint_row,
    _fsc,
)
from .providers.base import DataError, DataUnavailable, RateLimited
from .providers.fsc import FSC_ATTRIBUTION, FscProvider

log = logging.getLogger(__name__)

CACHE_KEY = "bio_events_board_v1"
#: 보드 payload의 모양 번호 — 렌더러 기대 모양이 바뀌면 이 번호를 올린다.
SCHEMA = 1

BOARD_EVENTS = 60
#: mfds blob이 배치 실패로 늦어도 이벤트 수집은 이어져야 한다 — 원천이 30일
#: 롤링 창이라 며칠 묵은 blob에서 걷어도 놓치는 것이 없다.
SOURCE_BLOB_TTL = 60 * 60 * 24 * 7

_KST = dt.timezone(dt.timedelta(hours=9))

_MARKET_BY_CTG = {"KOSPI": "Y", "KOSDAQ": "K", "KONEX": "N"}

_NAME_NOISE = re.compile(r"\(주\)|㈜|주식회사|\s+")


class BioEventsUnavailable(Exception):
    """``reason``은 ``disabled`` 또는 ``collecting`` — 라우트가 503으로 옮긴다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    """원천(mfds)과 가격(FSC) 둘 다 있어야 성립한다."""
    if not data_rights.mfds_serving_enabled():
        raise BioEventsUnavailable("disabled")
    if not (config.FSC_ENABLED and config.FSC_API_KEY):
        raise BioEventsUnavailable("disabled")


def _norm(name: Any) -> str:
    return _NAME_NOISE.sub("", str(name or "")).strip().lower()


def roster_map() -> dict[str, tuple[str, str | None]]:
    """정규화 종목명 → (코드, 시장). 정규화명이 유일하지 않으면 버린다."""
    mapping: dict[str, tuple[str, str | None]] = {}
    collisions: set[str] = set()
    for row in store.kr_listing_names():
        key = _norm(row.get("name"))
        if not key:
            continue
        market = _MARKET_BY_CTG.get(str(row.get("market") or "").strip())
        if key in mapping and mapping[key][0] != row["code"]:
            collisions.add(key)
            continue
        mapping[key] = (row["code"], market)
    for key in collisions:
        mapping.pop(key, None)
    return mapping


def _match(entp_name: Any, roster: dict[str, tuple[str, str | None]]):
    key = _norm(entp_name)
    if not key:
        return None
    hit = roster.get(key)
    if hit is None and key.endswith("제약"):
        # "OO제약(주)"가 로스터에 "OO"로만 오르는 변형 — 반대 방향은 하지
        # 않는다(로스터 이름에 붙여 보는 것은 오매칭을 늘린다).
        hit = roster.get(key[: -len("제약")])
    return hit


# --- 수집: mfds blob → 이벤트 원장 -------------------------------------------


def collect(*, today: dt.date | None = None) -> dict[str, int]:
    blob = store.load_report(bio.MFDS_CACHE_KEY, SOURCE_BLOB_TTL)
    if not blob:
        return {"skipped": "no_source_blob"}
    roster = roster_map()
    if not roster:
        return {"skipped": "no_roster"}
    rows: list[dict[str, Any]] = []
    permits = blob.get("permits") or []
    for permit in permits:
        item_seq = str(permit.get("item_seq") or "").strip()
        event_date = _as_date(permit.get("permit_date"))
        if not item_seq or event_date is None:
            continue
        hit = _match(permit.get("entp_name"), roster)
        if hit is None:
            continue  # 비상장이거나 정규화명이 유일하지 않다 — 만들지 않는다
        code, market = hit
        rows.append({
            "event_id": f"mfds:{item_seq}"[:20],
            "source": "mfds",
            "stock_code": code,
            "market": market,
            "company": permit.get("entp_name"),
            "title": permit.get("item_name"),
            "event_date": event_date,
            "permit_kind": permit.get("permit_kind"),
            "rx": str(permit.get("etc_otc") or "") == "전문의약품",
            "newdrug_class": permit.get("newdrug_class"),
            "rare": bool(permit.get("rare")),
            "url": permit.get("url"),
        })
    saved = store.save_bio_events(rows)
    return {"permits": len(permits), "matched": saved}


# --- 채점: 이벤트당 시세 한 번 ------------------------------------------------


def score(provider: FscProvider | None = None, *, today: dt.date | None = None) -> dict[str, int]:
    provider = provider or _fsc()
    today = today or dt.datetime.now(_KST).date()
    # T+1 13시 공개 — 허가 당일·전일 이벤트는 아직 종가가 없다.
    candidates = store.bio_events_pending_base(
        config.BIO_EVENTS_SCORE_PER_RUN, before=today - dt.timedelta(days=1)
    )
    stats = {"candidates": len(candidates), "bases": 0, "no_data": 0,
             "scored": 0, "halted": 0, "waiting": 0}
    if not candidates:
        return stats
    earliest = min(
        (_as_date(e["event_date"]) or today for e in candidates), default=today
    )
    bench = _bench_lookup(provider, since=earliest, today=today)
    for event in candidates:
        event_date = _as_date(event["event_date"])
        if event_date is None:
            continue
        window_end = min(event_date + dt.timedelta(days=FULL_SCORE_WINDOW_DAYS), today)
        try:
            rows = provider.fetch_stock_rows(
                event["stock_code"], start=event_date, end=window_end
            )
        except RateLimited:
            log.warning("data.go.kr 허용량 — 남은 허가 이벤트 채점은 다음 주기에")
            break
        except (DataUnavailable, DataError) as exc:
            log.warning("허가 이벤트 시세 조회 실패 %s: %s", event["stock_code"], exc)
            continue
        if not rows:
            if (today - event_date).days >= BASE_WINDOW_DAYS + 1:
                store.set_bio_event_base(event["event_id"], status="no_data")
                stats["no_data"] += 1
            else:
                stats["waiting"] += 1  # 갓 허가된 품목 — T+1 공개를 기다린다
            continue
        base = rows[0]
        store.set_bio_event_base(
            event["event_id"],
            status="ok",
            base_date=base["date"],
            base_close=base["close"],
            base_halted=not (base.get("volume") or 0) > 0,
        )
        stats["bases"] += 1
        for horizon in HORIZONS:
            checkpoint = _checkpoint_row(
                event["event_id"], horizon, rows,
                base_date=base["date"], bench=bench(event.get("market")),
            )
            if checkpoint is None:
                continue  # 아직 안 익음 — 다음 주기가 이어받는다
            if checkpoint["status"] == "halted":
                stats["halted"] += 1
            else:
                stats["scored"] += 1
            store.save_score_checkpoint(checkpoint)
    return stats


def score_pending_checkpoints(
    provider: FscProvider | None = None, *, today: dt.date | None = None
) -> dict[str, int]:
    """기준가는 있는데 덜 익은 horizon이 남은 이벤트를 다시 살핀다.

    허가 이벤트는 전부 최근(30일 창)이라 처음엔 어떤 horizon도 안 익는다 —
    시간이 지나며 여기서 하나씩 떨어진다. 후보 판별은 저장된 이벤트와 공유
    체크포인트 표를 그대로 읽어 한다.
    """
    provider = provider or _fsc()
    today = today or dt.datetime.now(_KST).date()
    events = store.load_bio_events(BOARD_EVENTS)
    ripe = [
        e for e in events
        if e.get("base_status") == "ok"
        and len(e.get("checkpoints") or []) < len(HORIZONS)
        # 달력 필터 — 정확한 판정은 가격 행 수가 한다.
        and (today - (_as_date(e.get("base_date")) or today)).days >= 30
    ][: config.BIO_EVENTS_SCORE_PER_RUN]
    stats = {"candidates": len(ripe), "scored": 0, "halted": 0}
    if not ripe:
        return stats
    earliest = min(
        (_as_date(e["base_date"]) or today for e in ripe), default=today
    )
    bench = _bench_lookup(provider, since=earliest, today=today)
    for event in ripe:
        base_date = _as_date(event["base_date"])
        if base_date is None:
            continue
        done = {c["horizon"] for c in event.get("checkpoints") or []}
        try:
            rows = provider.fetch_stock_rows(
                event["stock_code"], start=base_date, end=today
            )
        except RateLimited:
            break
        except (DataUnavailable, DataError) as exc:
            log.warning("허가 이벤트 재채점 실패 %s: %s", event["stock_code"], exc)
            continue
        if not rows or rows[0]["date"] != base_date:
            continue
        for horizon in HORIZONS:
            if horizon in done:
                continue
            checkpoint = _checkpoint_row(
                event["event_id"], horizon, rows,
                base_date=base_date, bench=bench(event.get("market")),
            )
            if checkpoint is None:
                continue
            if checkpoint["status"] == "halted":
                stats["halted"] += 1
            else:
                stats["scored"] += 1
            store.save_score_checkpoint(checkpoint)
    return stats


# --- 보드 ---------------------------------------------------------------------


def _live_reference(event: dict[str, Any]) -> dict[str, Any] | None:
    base_close = event.get("base_close")
    base_date = _as_date(event.get("base_date"))
    if not base_close or base_date is None:
        return None
    listing = store.get_kr_listing(event["stock_code"])
    if not listing:
        return None
    close = listing.get("clpr")
    as_of = _as_date(listing.get("bas_dt"))
    if not close or as_of is None or as_of <= base_date:
        return None
    return {
        "close": close,
        "as_of": as_of.isoformat(),
        "vs_base_percent": round((close / base_close - 1.0) * 100.0, 2),
        "basis": "raw_close_ratio",
    }


def build_board(*, today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.datetime.now(_KST).date()
    events = store.load_bio_events(BOARD_EVENTS)
    cards = []
    for event in events:
        event_date = _as_date(event["event_date"])
        base_date = _as_date(event.get("base_date"))
        cards.append({
            "event_id": event["event_id"],
            "stock_code": event["stock_code"],
            "company": event.get("company"),
            "title": event.get("title"),
            "event_date": event_date.isoformat() if event_date else None,
            "days_since": (today - event_date).days if event_date else None,
            "permit_kind": event.get("permit_kind"),
            "rx": bool(event.get("rx")),
            "newdrug_class": event.get("newdrug_class"),
            "rare": bool(event.get("rare")),
            "url": event.get("url"),
            "base": {
                "status": event.get("base_status"),
                "date": base_date.isoformat() if base_date else None,
                "close": event.get("base_close"),
                "halted": bool(event.get("base_halted")),
            },
            "live": _live_reference(event),
            "checkpoints": [
                {
                    "horizon": cp["horizon"],
                    "stock_return": cp.get("stock_return"),
                    "bench_return": cp.get("bench_return"),
                    "excess": cp.get("excess"),
                    "status": cp.get("status"),
                }
                for cp in event.get("checkpoints", [])
            ],
        })
    payload = {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "as_of": today.isoformat(),
        "events": cards,
        "counts": {
            "total": len(cards),
            "rx": sum(1 for c in cards if c["rx"]),
            "new_drug": sum(1 for c in cards if c["newdrug_class"]),
            "rare": sum(1 for c in cards if c["rare"]),
        },
        "attribution": {
            "text": "출처: 식품의약품안전처 (공공데이터포털) · 종가: 금융위원회 (data.go.kr)",
            "text_en": "Source: MFDS (data.go.kr) · closes: Financial Services Commission (data.go.kr)",
            "url": "https://www.data.go.kr/data/15095677/openapi.do",
        },
        "methodology": {
            "ko": (
                "식약처 품목허가 중 업체명이 국내 상장사와 정규화 후 정확히 일치하고 "
                "그 이름이 로스터에서 유일한 것만 종목에 연결합니다(오매칭보다 결측을 "
                "택합니다). 기준가는 허가일 이후 첫 거래일의 공식 종가로 동결하고, "
                "수익률은 일별 등락률의 연쇄곱(분할·권리락 반영), 초과는 같은 구간 "
                "코스피·코스닥 대비, 거래정지 구간은 채점하지 않고 정지로 표시합니다. "
                "공식 종가는 다음 영업일 13시 이후 공개되므로 갓 허가된 품목은 기준가 "
                "대기 상태입니다."
            ),
            "en": (
                "MFDS permits are linked to a listed company only when the normalized "
                "company name matches a roster name exactly and uniquely (a miss is "
                "preferred over a mismatch). The base is frozen at the first official "
                "close on or after the permit date; returns chain daily change rates "
                "(split-safe), excess is measured against KOSPI/KOSDAQ over the same "
                "span, and halted spans are marked rather than scored."
            ),
        },
        "disclaimer": {
            "ko": (
                "허가 이후 주가의 기록·통계이며 투자 추천이 아닙니다. 허가는 매출을 "
                "보장하지 않고, 과거의 기록은 미래를 보장하지 않습니다. '현재' 값은 "
                "최신 종가 대비 원시 비율의 참고값입니다."
            ),
            "en": (
                "A record of prices after permits — statistics, not investment advice. "
                "A permit does not guarantee sales, and past records do not guarantee "
                "future results."
            ),
        },
        "rights": {"status": "approved", "notice": FSC_ATTRIBUTION},
    }
    store.save_report(CACHE_KEY, payload)
    return payload


def refresh(
    provider: FscProvider | None = None, *, today: dt.date | None = None
) -> dict[str, Any]:
    """수집 → 채점(신규·재채점) → 보드. 단계 실패가 다음을 막지 않는다."""
    _require_lane()
    today = today or dt.datetime.now(_KST).date()
    stats: dict[str, Any] = {"collect": collect(today=today)}
    stats["score"] = score(provider, today=today)
    stats["ripen"] = score_pending_checkpoints(provider, today=today)
    board = build_board(today=today)
    stats["board_events"] = board["counts"]["total"]
    return stats


def get_board() -> dict:
    """저장된 보드만 읽는다 — 요청 경로에서 상류를 부르지 않는다."""
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise BioEventsUnavailable("collecting")
    return cached
