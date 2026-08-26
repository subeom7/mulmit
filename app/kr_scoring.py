"""대량보유(5%) 공시 스코어보드 — 채점 엔진 v0.

`docs/DIRECTION.md` §4 Phase 1의 구현이고, 규칙은 전부 착수 전 프로브
실측(`docs/PLAN_SCORING.md`)이 정했다:

* **이벤트는 원장(kr_score_events)에 쌓는다** — blob 롤링 창이 아니라 축적.
  majorstock 요약 API가 최근 약 2년 창만 돌려주는 것을 실측했으므로, 오늘
  걷어 두는 행이 시간이 지날수록 원천보다 깊어진다.
* **기준가는 공시일 이후 첫 거래일 종가로 동결**한다. FSC 공개가 T+1 13시라
  갓 생긴 카드는 "기준가 대기"가 정상 상태다 — 만들어 채우지 않는다.
* **수익률은 (1+fltRt) 연쇄곱** — 카카오 5:1 분할일 실측(+7.59%, 조정 기준가
  대비)으로 분할·권리락에 안전함을 확인했다. 원시 종가비와 0.01%p 이내로
  일치하는 것도 같은 프로브에서 확인.
* **거래정지는 trqu 0으로 감지**한다. 도부(227420)는 공시일부터 53거래일
  전부 거래량 0이었고, 감지 없이는 "0% 수익"으로 위장 채점된다.
* **표현 규칙**: 집계·이벤트 단위로만 말하고 추천 표현을 쓰지 않는다.
  보고자 단위 랭킹은 법인 명예훼손 검토 전 보류(DIRECTION §4).

수집·채점은 ingest 배치에서만 돈다. web 요청 경로는 저장된 보드만 읽는다.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from typing import Any

from . import config, store
from .providers.base import DataError, DataUnavailable, RateLimited
from .providers.dart import (
    DART_ATTRIBUTION,
    DART_PROVIDER_ID,
    DART_PUBLISHER,
    DART_PUBLISHER_URL,
    DART_REPORT_URL,
    DART_TERMS_URL,
    DartProvider,
)
from .providers.fsc import (
    FSC_ATTRIBUTION,
    FSC_PROVIDER_ID,
    FSC_PUBLISHER,
    FSC_STOCK_DATASET_URL,
    FscProvider,
)

log = logging.getLogger(__name__)

CACHE_KEY = "kr_score_board_v1"
#: 보드 payload의 모양 번호. 렌더러가 기대하는 모양이 바뀌면 **이 번호를 올린다**
#: — 캐시 키가 아니라. (배치 lane 페이로드 스키마 규칙, ROADMAP 2026-08-25)
SCHEMA = 1

DETAIL_TYPE_MAJOR_HOLDINGS = "D001"
#: FSC 시세의 실측 시작일 — 이전 이벤트는 채점하지 않는다(PLAN_SCORING §1).
FSC_FLOOR = dt.date(2020, 1, 2)
#: 체크포인트(영업일): 1개월 · 3개월 · 6개월.
HORIZONS = (21, 63, 126)
#: 영업일→달력일 1차 필터 배수. 판정은 가격 행 수가 하고, 이건 호출 절약용.
CALENDAR_FACTOR = 1.5
#: 기준가 창: 공시일부터 이 일수 안에 거래일이 하나도 없으면 no_data로 접는다.
BASE_WINDOW_DAYS = 14
#: 공시검색 창 상한 — corp_code 없는 조회는 3개월까지만(프로브 실측).
MAX_COLLECT_WINDOW_DAYS = 89

#: 소급 백필의 바닥. majorstock 요약 API의 롤링 창이 실측 시점(2026-08-26)에
#: 2024-09까지 닿았다 — 그 이전은 원문 파싱 없이는 상세를 붙일 수 없어 별도
#: 판정 전 보류다(PLAN_SCORING §3). 창은 매일 하루씩 미끄러지므로 상세는
#: 가장 오래된 쪽부터 붙인다.
BACKFILL_FLOOR = dt.date(2024, 9, 1)
#: 백필 인덱스 걷기는 한 주기에 이만큼 — 3개월 창 × 8이면 바닥까지 한 번에 간다.
BACKFILL_MAX_WINDOWS_PER_RUN = 10
#: 오래된 이벤트는 이 달력 폭 하나로 기준가와 세 체크포인트를 전부 채점한다
#: (+126영업일 ≈ 189달력일 + 휴장 여유). 시세 호출이 이벤트당 한 번이 된다.
FULL_SCORE_WINDOW_DAYS = 230

_KST = dt.timezone(dt.timedelta(hours=9))

BENCH_BY_MARKET = {"Y": "코스피", "K": "코스닥"}
MARKET_LABELS = {
    "Y": {"ko": "유가증권", "en": "KOSPI"},
    "K": {"ko": "코스닥", "en": "KOSDAQ"},
    "N": {"ko": "코넥스", "en": "KONEX"},
    "E": {"ko": "기타", "en": "Other"},
}


class KrScoringDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    """DART(이벤트)와 FSC(가격) 둘 다 있어야 채점이 성립한다."""
    if not (config.DART_ENABLED and config.FSC_ENABLED):
        raise KrScoringDisabled("disabled")
    if not (config.DART_API_KEY and config.FSC_API_KEY):
        raise KrScoringDisabled("not_configured")


def _dart() -> DartProvider:
    return DartProvider(
        config.DART_API_KEY,
        timeout=config.DART_TIMEOUT,
        retries=config.DART_RETRIES,
        request_interval=config.DART_REQUEST_INTERVAL,
    )


def _fsc() -> FscProvider:
    return FscProvider(
        config.FSC_API_KEY,
        timeout=config.FSC_TIMEOUT,
        retries=config.FSC_RETRIES,
        request_interval=config.FSC_REQUEST_INTERVAL,
    )


def _as_date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return dt.date(int(text[:4]), int(text[4:6]), int(text[6:]))
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _looks_new(report_type: str | None, reason: str | None) -> bool:
    """신규 진입 판별. report_tp가 '신규'로 오기도 하고, 실측에서는
    report_resn 자유 텍스트("매매로 인한 신규보고의무 발생…")에만 있기도 했다
    — 둘 다 본다(PLAN_SCORING §1)."""
    return "신규" in str(report_type or "") or "신규" in str(reason or "")


# --- 1) 수집: 공시검색 → 이벤트 원장 ----------------------------------------


def _ledger_rows(
    rows: list[dict[str, Any]], existing: set[str]
) -> list[dict[str, Any]]:
    """공시검색 행을 원장 행으로 — 중복·비상장은 버린다."""
    seen: set[str] = set()
    fresh: list[dict[str, Any]] = []
    for row in rows:
        rcept_no = row["rcept_no"]
        if rcept_no in seen or rcept_no in existing:
            continue
        seen.add(rcept_no)
        stock_code = (row.get("stock_code") or "").strip()
        report_date = _as_date(row.get("rcept_dt"))
        if not stock_code or report_date is None:
            continue  # 비상장 보고는 채점 대상이 아니다
        fresh.append({
            "rcept_no": rcept_no,
            "corp_code": row["corp_code"],
            "stock_code": stock_code,
            "corp_name": row["corp_name"],
            "market": (row.get("corp_cls") or "").strip() or None,
            "filing_name": row.get("report_nm"),
            "report_date": report_date,
            # 상세가 붙기 전까지는 공시검색의 제출인명이 보고자다.
            "reporter": row.get("flr_nm"),
            "detail_status": "unavailable",
            "base_status": "pending",
            "is_new": False,
        })
    return fresh


def collect(provider: DartProvider, *, today: dt.date) -> dict[str, int]:
    last = store.score_events_max_date()
    if last is None:
        start = today - dt.timedelta(days=config.KR_SCORING_COLLECT_DAYS)
    else:
        # 사흘 겹쳐 다시 걷는다 — 늦게 붙는 공시를 놓치지 않기 위해서다.
        start = last - dt.timedelta(days=3)
    start = max(start, today - dt.timedelta(days=MAX_COLLECT_WINDOW_DAYS))

    rows, truncated = provider.fetch_filing_index(
        detail_type=DETAIL_TYPE_MAJOR_HOLDINGS,
        bgn_de=start.strftime("%Y%m%d"),
        end_de=today.strftime("%Y%m%d"),
    )
    saved = store.save_score_events(_ledger_rows(rows, store.score_event_ids(start)))
    return {"indexed": len(rows), "saved": saved, "truncated": int(truncated)}


#: 백필 커서 blob. 저장된 최소 날짜로는 "바닥까지 확인했다"를 기억할 수 없다 —
#: 바닥 근처 창이 비어 있으면 min-date가 바닥에 영영 닿지 않아, 매 주기 같은
#: 빈 창을 다시 걷게 된다. 커서는 매 주기 다시 저장돼 reports 청소(48h)를
#: 넘긴다; 오래 꺼져 있다 잃으면 min-date에서 다시 유도한다(빈 창 한 바퀴 손해).
BACKFILL_CURSOR_KEY = "kr_score_backfill_cursor_v1"
_CURSOR_TTL = 10 * 365 * 24 * 3600  # 커서에 신선도 개념은 없다


def backfill_collect(provider: DartProvider, *, today: dt.date) -> dict[str, Any]:
    """원장의 최소 날짜에서 BACKFILL_FLOOR까지 3개월 창으로 거슬러 걷는다.

    커서는 걷는 동안 로컬로 전진한다 — 창에 상장 공시가 하나도 없어도
    전진해야 하므로, 저장된 최소 날짜를 창마다 다시 묻지 않는다.
    """
    blob = store.load_report(BACKFILL_CURSOR_KEY, _CURSOR_TTL) or {}
    cursor = _as_date(blob.get("cursor")) or store.score_events_min_date()
    if cursor is None:
        return {"skipped": "no_ledger"}  # 정상 수집이 먼저다
    windows = indexed = saved = 0
    while cursor > BACKFILL_FLOOR and windows < BACKFILL_MAX_WINDOWS_PER_RUN:
        end = cursor - dt.timedelta(days=1)
        start = max(end - dt.timedelta(days=MAX_COLLECT_WINDOW_DAYS - 4), BACKFILL_FLOOR)
        rows, _truncated = provider.fetch_filing_index(
            detail_type=DETAIL_TYPE_MAJOR_HOLDINGS,
            bgn_de=start.strftime("%Y%m%d"),
            end_de=end.strftime("%Y%m%d"),
        )
        indexed += len(rows)
        saved += store.save_score_events(_ledger_rows(rows, store.score_event_ids(start)))
        cursor = start
        windows += 1
    store.save_report(BACKFILL_CURSOR_KEY, {"cursor": cursor.isoformat()})
    return {
        "windows": windows,
        "indexed": indexed,
        "saved": saved,
        "done": cursor <= BACKFILL_FLOOR,
        "cursor": cursor.isoformat(),
    }


def fill_details(
    provider: DartProvider, *, limit: int | None = None, oldest_first: bool = False
) -> dict[str, int]:
    """상세 없는 이벤트에 majorstock을 회사당 한 번씩 붙인다. 실패분은 null.

    정상 주기는 최신 공시부터(보드가 먼저), 백필은 ``oldest_first``로 침식 중인
    2024-09 가장자리부터 붙인다.
    """
    if limit is None:
        limit = config.KR_SCORING_DETAIL_CORPS_PER_RUN
    corps = store.score_corps_missing_detail(limit, oldest_first=oldest_first)
    updated = failed = 0
    for corp_code in corps:
        try:
            holdings = provider.fetch_major_holdings(corp_code)
        except RateLimited:
            log.warning("DART 허용량 — 남은 대량보유 상세는 다음 주기에")
            break
        except (DataUnavailable, DataError) as exc:
            failed += 1
            log.warning("대량보유 상세 조회 실패 %s: %s", corp_code, exc)
            continue
        details: dict[str, dict[str, Any]] = {}
        for holding in holdings:
            details[holding["rcept_no"]] = {
                "reporter": holding.get("reporter"),
                "report_type": holding.get("report_type"),
                "reason": holding.get("reason"),
                "ratio": holding.get("ratio"),
                "ratio_change": holding.get("ratio_change"),
                "is_new": _looks_new(holding.get("report_type"), holding.get("reason")),
            }
        if details:
            updated += store.update_score_event_details(corp_code, details)
    return {"corps": len(corps), "updated": updated, "failed": failed}


# --- 2) 기준가 동결 ----------------------------------------------------------


def fill_bases(provider: FscProvider, *, today: dt.date) -> dict[str, int]:
    pending = store.score_events_pending_base(
        config.KR_SCORING_BASE_PER_RUN, floor=FSC_FLOOR
    )
    set_ok = set_no_data = waiting = 0
    for event in pending:
        report_date = _as_date(event["report_date"])
        if report_date is None or report_date > today:
            continue
        window_end = min(report_date + dt.timedelta(days=BASE_WINDOW_DAYS), today)
        try:
            rows = provider.fetch_stock_rows(
                event["stock_code"], start=report_date, end=window_end
            )
        except RateLimited:
            log.warning("data.go.kr 허용량 — 남은 기준가는 다음 주기에")
            break
        except (DataUnavailable, DataError) as exc:
            log.warning("기준가 조회 실패 %s: %s", event["stock_code"], exc)
            continue
        if not rows:
            # T+1 13시 공개라 갓 나온 공시는 빈 것이 정상이다. 창이 다 지나도록
            # 행이 없으면(상장폐지·이전상장 등) 더 묻지 않는다.
            if (today - report_date).days >= BASE_WINDOW_DAYS + 1:
                store.set_score_base(event["rcept_no"], status="no_data")
                set_no_data += 1
            else:
                waiting += 1
            continue
        base = rows[0]
        store.set_score_base(
            event["rcept_no"],
            status="ok",
            base_date=base["date"],
            base_close=base["close"],
            # 기준일 거래량 0 = 공시 시점에 이미 정지(도부 실측 함정).
            base_halted=not (base.get("volume") or 0) > 0,
        )
        set_ok += 1
    return {"pending": len(pending), "ok": set_ok, "no_data": set_no_data, "waiting": waiting}


# --- 3) 체크포인트 채점 ------------------------------------------------------


def _chained_return(rows: list[dict[str, Any]]) -> float | None:
    """기준일 다음 행부터의 (1+fltRt) 연쇄곱 − 1, %.

    fltRt가 빠진 날은 앞 종가 대비 비율로 그 한 걸음만 대신한다 — 값을
    만들지 않고, 이미 있는 두 종가로 계산할 수 있는 것만 계산한다.
    """
    acc = 1.0
    for index in range(1, len(rows)):
        rate = rows[index].get("flt_rt")
        if rate is None:
            prev_close = rows[index - 1].get("close")
            close = rows[index].get("close")
            if not prev_close or not close:
                return None
            rate = (close / prev_close - 1.0) * 100.0
        acc *= 1.0 + rate / 100.0
    return (acc - 1.0) * 100.0


def _bench_return(
    bench_rows: list[dict[str, Any]], *, after: dt.date, through: dt.date
) -> float | None:
    span = [row for row in bench_rows if after < row["date"] <= through]
    if not span:
        return None
    acc = 1.0
    for row in span:
        rate = row.get("flt_rt")
        if rate is None:
            return None
        acc *= 1.0 + rate / 100.0
    return (acc - 1.0) * 100.0


def _bench_lookup(provider: FscProvider, *, since: dt.date, today: dt.date):
    """시장(Y/K)별 지수 행을 주기당 한 번만 걷는 캐시."""
    cache: dict[str, list[dict[str, Any]] | None] = {}

    def lookup(market: str | None) -> list[dict[str, Any]] | None:
        idx_nm = BENCH_BY_MARKET.get(market or "")
        if idx_nm is None:
            return None
        if idx_nm not in cache:
            try:
                cache[idx_nm] = provider.fetch_index_rows(idx_nm, start=since, end=today)
            except (DataUnavailable, DataError, RateLimited) as exc:
                log.warning("벤치마크 %s 조회 실패: %s", idx_nm, exc)
                cache[idx_nm] = None
        return cache[idx_nm]

    return lookup


def _checkpoint_row(
    rcept_no: str,
    horizon: int,
    rows: list[dict[str, Any]],
    *,
    base_date: dt.date,
    bench: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """rows[0]=기준일인 시세 행에서 한 horizon의 체크포인트를 만든다.

    행이 모자라면(아직 안 익음) None — 만들지 않는다. 정상 주기와 백필이
    같은 함수를 쓴다: 두 벌이면 반드시 어긋난다.
    """
    if len(rows) <= horizon:
        return None
    segment = rows[: horizon + 1]
    end_date = segment[-1]["date"]
    traded = sum(1 for row in segment[1:] if (row.get("volume") or 0) > 0)
    checkpoint: dict[str, Any] = {
        "rcept_no": rcept_no,
        "horizon": horizon,
        "end_date": end_date,
        "traded_days": traded,
        "halted_days": horizon - traded,
    }
    if traded == 0:
        # 전 구간 정지 — 수익률 0%가 아니라 채점 불능이다(도부 실측).
        checkpoint.update(
            {"stock_return": None, "bench_return": None, "excess": None, "status": "halted"}
        )
        return checkpoint
    stock_return = _chained_return(segment)
    bench_return = (
        _bench_return(bench or [], after=base_date, through=end_date)
        if stock_return is not None
        else None
    )
    excess = (
        round(stock_return - bench_return, 4)
        if stock_return is not None and bench_return is not None
        else None
    )
    checkpoint.update({
        "stock_return": round(stock_return, 4) if stock_return is not None else None,
        "bench_return": round(bench_return, 4) if bench_return is not None else None,
        "excess": excess,
        "status": "scored",
    })
    return checkpoint


def score_checkpoints(provider: FscProvider, *, today: dt.date) -> dict[str, int]:
    due_before = {
        h: today - dt.timedelta(days=math.ceil(h * CALENDAR_FACTOR)) for h in HORIZONS
    }
    events = store.score_events_awaiting_checkpoints(
        HORIZONS, due_before=due_before, limit=config.KR_SCORING_SCORE_PER_RUN
    )
    earliest = min((e["base_date"] for e in events), default=today)
    bench = _bench_lookup(provider, since=earliest, today=today)
    scored = halted = 0
    for event in events:
        base_date = _as_date(event["base_date"])
        if base_date is None:
            continue
        try:
            rows = provider.fetch_stock_rows(
                event["stock_code"], start=base_date, end=today
            )
        except RateLimited:
            log.warning("data.go.kr 허용량 — 남은 채점은 다음 주기에")
            break
        except (DataUnavailable, DataError) as exc:
            log.warning("채점 시세 조회 실패 %s: %s", event["stock_code"], exc)
            continue
        if not rows or rows[0]["date"] != base_date:
            log.warning(
                "기준일 행 불일치 %s(%s) — 채점 보류",
                event["stock_code"], base_date,
            )
            continue
        for horizon in event["missing_horizons"]:
            checkpoint = _checkpoint_row(
                event["rcept_no"], horizon, rows,
                base_date=base_date, bench=bench(event.get("market")),
            )
            if checkpoint is None:
                continue  # 영업일이 아직 안 찼다 — 달력 필터가 낙관했을 뿐이다
            if checkpoint["status"] == "halted":
                halted += 1
            else:
                scored += 1
            store.save_score_checkpoint(checkpoint)
    return {"candidates": len(events), "scored": scored, "halted": halted}


def backfill_score(provider: FscProvider, *, today: dt.date) -> dict[str, int]:
    """오래된 무기준가 이벤트를 시세 한 번으로 끝까지 채점한다.

    기준가와 익은 체크포인트 전부가 한 번의 fetch에서 나온다 — 백필 이벤트
    대부분은 세 horizon이 이미 도래해 있어, 나눠 부르면 호출만 배가 된다.
    아직 안 익은 horizon은 만들지 않는다: 정상 주기가 때가 되면 이어받는다.
    """
    candidates = store.score_events_pending_base(
        config.KR_SCORING_BACKFILL_SCORE_PER_RUN,
        floor=FSC_FLOOR,
        # T+1 공개 대기 중인 갓 나온 공시는 정상 주기의 몫이다.
        before=today - dt.timedelta(days=BASE_WINDOW_DAYS + 1),
        oldest_first=True,
    )
    stats = {"candidates": len(candidates), "bases": 0, "no_data": 0,
             "scored": 0, "halted": 0}
    if not candidates:
        return stats
    earliest = min(
        (_as_date(e["report_date"]) or today for e in candidates), default=today
    )
    bench = _bench_lookup(provider, since=earliest, today=today)
    for event in candidates:
        report_date = _as_date(event["report_date"])
        if report_date is None:
            continue
        window_end = min(report_date + dt.timedelta(days=FULL_SCORE_WINDOW_DAYS), today)
        try:
            rows = provider.fetch_stock_rows(
                event["stock_code"], start=report_date, end=window_end
            )
        except RateLimited:
            log.warning("data.go.kr 허용량 — 남은 백필 채점은 다음 주기에")
            break
        except (DataUnavailable, DataError) as exc:
            log.warning("백필 시세 조회 실패 %s: %s", event["stock_code"], exc)
            continue
        if not rows:
            # 창이 통째로 비었다 — 상장폐지·이전상장 등. 더 묻지 않는다.
            store.set_score_base(event["rcept_no"], status="no_data")
            stats["no_data"] += 1
            continue
        base = rows[0]
        store.set_score_base(
            event["rcept_no"],
            status="ok",
            base_date=base["date"],
            base_close=base["close"],
            base_halted=not (base.get("volume") or 0) > 0,
        )
        stats["bases"] += 1
        for horizon in HORIZONS:
            checkpoint = _checkpoint_row(
                event["rcept_no"], horizon, rows,
                base_date=base["date"], bench=bench(event.get("market")),
            )
            if checkpoint is None:
                continue
            if checkpoint["status"] == "halted":
                stats["halted"] += 1
            else:
                stats["scored"] += 1
            store.save_score_checkpoint(checkpoint)
    return stats


# --- 4) 보드 조립 ------------------------------------------------------------


def _live_reference(event: dict[str, Any]) -> dict[str, Any] | None:
    """최신 종가 대비 원시 비율 — 참고값이다.

    분할·권리락이 끼면 원시 비율이 왜곡되므로 확정치(연쇄곱 체크포인트)와
    성격이 다르고, payload가 그 사실을 basis로 말한다. 최신 종가는 이미
    저장된 하루 스냅샷(kr_listings)에서 읽는다 — 이 값을 위해 상류를 부르지
    않는다.
    """
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


def build_board(*, today: dt.date) -> dict[str, Any]:
    events = store.load_score_events(config.KR_SCORING_BOARD_EVENTS)
    cards = []
    for event in events:
        report_date = _as_date(event["report_date"])
        base_date = _as_date(event.get("base_date"))
        checkpoints = [
            {
                "horizon": cp["horizon"],
                "end_date": (_as_date(cp["end_date"]) or cp["end_date"]).isoformat()
                if cp.get("end_date") else None,
                "stock_return": cp.get("stock_return"),
                "bench_return": cp.get("bench_return"),
                "excess": cp.get("excess"),
                "halted_days": cp.get("halted_days"),
                "status": cp.get("status"),
            }
            for cp in event.get("checkpoints", [])
        ]
        cards.append({
            "rcept_no": event["rcept_no"],
            "stock_code": event["stock_code"],
            "company": event["corp_name"],
            "market": MARKET_LABELS.get(event.get("market") or ""),
            "reporter": event.get("reporter"),
            "report_date": report_date.isoformat() if report_date else None,
            "days_since": (today - report_date).days if report_date else None,
            "is_new": bool(event.get("is_new")),
            "ratio": event.get("ratio"),
            "ratio_change": event.get("ratio_change"),
            "reason": event.get("reason"),
            "detail_status": event.get("detail_status"),
            "base": {
                "status": event.get("base_status"),
                "date": base_date.isoformat() if base_date else None,
                "close": event.get("base_close"),
                "halted": bool(event.get("base_halted")),
            },
            "live": _live_reference(event),
            "checkpoints": checkpoints,
            "report_url": DART_REPORT_URL.format(rcept_no=event["rcept_no"]),
        })

    payload = {
        "schema": SCHEMA,
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "as_of": today.isoformat(),
        "cards": cards,
        "count": len(cards),
        "aggregates": store.score_checkpoint_aggregates(),
        "horizons": list(HORIZONS),
        "score_floor": FSC_FLOOR.isoformat(),
        "basis_ko": (
            "대량보유(5% 룰) 공시 이후의 주가를 기록·추적한 통계이며 투자 추천이 "
            "아닙니다. 기준가는 공시일 이후 첫 거래일의 공식 종가로 동결하고, "
            "체크포인트 수익률은 일별 등락률의 연쇄곱(분할·권리락 반영), 초과수익은 "
            "같은 구간 시장 지수 대비입니다. 보고 기한이 5영업일이라 공시일은 실제 "
            "변동일과 다를 수 있고, 공식 종가는 다음 영업일 13시 이후 공개되므로 갓 "
            "올라온 카드는 기준가 대기 상태입니다. '현재' 값은 최신 종가 대비 원시 "
            "비율의 참고값으로, 분할·권리락이 있으면 확정 체크포인트와 다를 수 "
            "있습니다. 거래정지 구간은 채점하지 않고 정지로 표시합니다."
        ),
        "basis_en": (
            "A record of prices after large-holding (5% rule) filings — statistics, "
            "not investment advice. The base is frozen at the first official close on "
            "or after the filing date; checkpoint returns chain daily change rates "
            "(split-safe), and excess is measured against the market index over the "
            "same span. Filings may trail the actual trade by up to five business "
            "days, official closes publish at T+1 13:00 KST, and halted spans are "
            "marked rather than scored."
        ),
        "source": {
            "provider": DART_PROVIDER_ID,
            "provider_name": DART_PUBLISHER,
            "publisher": DART_PUBLISHER,
            "publisher_url": DART_PUBLISHER_URL,
            "url": DART_TERMS_URL,
            "notice": DART_ATTRIBUTION,
            "price_provider": FSC_PROVIDER_ID,
            "price_publisher": FSC_PUBLISHER,
            "price_url": FSC_STOCK_DATASET_URL,
            "price_notice": FSC_ATTRIBUTION,
        },
        "rights": {"status": "approved", "notice": f"{DART_ATTRIBUTION} · {FSC_ATTRIBUTION}"},
    }
    store.save_report(CACHE_KEY, payload)
    return payload


# --- 오케스트레이션 ----------------------------------------------------------


def refresh(
    dart_provider: DartProvider | None = None,
    fsc_provider: FscProvider | None = None,
    *,
    today: dt.date | None = None,
) -> dict[str, Any]:
    """수집 → 상세 → 기준가 → 채점 → 보드. 단계 실패가 다음 단계를 막지 않는다."""
    _require_lane()
    dart_provider = dart_provider or _dart()
    fsc_provider = fsc_provider or _fsc()
    today = today or dt.datetime.now(_KST).date()

    stats: dict[str, Any] = {}
    try:
        stats["collect"] = collect(dart_provider, today=today)
    except (DataUnavailable, DataError, RateLimited) as exc:
        log.warning("채점 이벤트 수집 실패: %s", exc)
        stats["collect"] = {"failed": str(exc)}
    stats["details"] = fill_details(dart_provider)
    stats["bases"] = fill_bases(fsc_provider, today=today)
    stats["checkpoints"] = score_checkpoints(fsc_provider, today=today)
    # 소급 백필 — 완주하면 셋 다 저절로 무행동이 된다(커서 조회·빈 후보).
    try:
        stats["backfill_collect"] = backfill_collect(dart_provider, today=today)
    except (DataUnavailable, DataError, RateLimited) as exc:
        log.warning("백필 인덱스 걷기 실패: %s", exc)
        stats["backfill_collect"] = {"failed": str(exc)}
    stats["backfill_details"] = fill_details(
        dart_provider,
        limit=config.KR_SCORING_BACKFILL_DETAIL_CORPS_PER_RUN,
        oldest_first=True,
    )
    stats["backfill_score"] = backfill_score(fsc_provider, today=today)
    board = build_board(today=today)
    stats["board_cards"] = board["count"]
    return stats


def get_board() -> dict:
    """저장된 보드만 읽는다. 요청 경로에서 DART도 FSC도 호출하지 않는다."""
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("score board not built yet")
    return cached
