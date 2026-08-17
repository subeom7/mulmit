"""Korean per-stock lookup and risk statistics on the FSC open-data lane.

This is the Korean half of the analytics the legacy Yahoo lane used to power.
The maths did not go anywhere when that lane was quarantined — the data did.
The FSC dataset supplies what the maths needs for any listed Korean issue
(five years of official closes, 이용허락범위 "제한 없음", ``DS-2026-006``
grants derived metrics), so drawdowns and volatility come back here first.
The US half stays down until a licensed price provider exists.

Two deliberate deviations from the macro lanes:

* **On-demand fetch.** The ingest loop runs hourly; a stock someone just
  searched for cannot wait that long. A cache miss fetches synchronously under
  a process-wide lock — one fetch at a time, two or three requests per stock,
  written straight to the store so every later request is a database read.
  Failures are memoised briefly so a bad code cannot hammer the API.
* **Name search never leaves the process.** The whole exchange is one daily
  snapshot (~3k rows) kept in ``kr_listings``; keystrokes query that table.

Everything served here passes the same rights gate as the macro cards:
FSC lane enabled + row rights approved, or a structured 503.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time
from typing import Any

from . import config, data_rights, store
from .providers.base import DataError, DataUnavailable, RateLimited
from .providers.fsc import (
    FSC_ATTRIBUTION,
    FSC_PROVIDER_ID,
    FSC_PUBLISHER,
    FSC_PUBLISHER_URL,
    FSC_STOCK_DATASET_URL,
    FSC_TERMS_URL,
    KR_STOCK_KEY_PREFIX,
    FscProvider,
    stock_series_spec,
)

log = logging.getLogger(__name__)

# Yearly windows the return table reports, oldest last so the UI reads naturally.
RETURN_WINDOWS = (("1m", 30), ("3m", 91), ("6m", 182), ("1y", 366), ("3y", 366 * 3), ("5y", 366 * 5))
TRADING_DAYS_PER_YEAR = 252
MAX_CHART_POINTS = 1300  # five years of daily closes, undecimated

_fetch_lock = threading.Lock()
_recent_failures: dict[str, float] = {}
FAILURE_MEMO_SECONDS = 60.0


class KrStockDisabled(RuntimeError):
    """The FSC lane is off, so nothing here may be served."""


class KrStockUnknown(RuntimeError):
    """The code matches no listed issue and no stored series."""


def _require_lane() -> None:
    if not data_rights.series_values_servable(FSC_PROVIDER_ID, data_rights.SERVABLE_ROW_RIGHTS):
        raise KrStockDisabled


def _provider() -> FscProvider:
    return FscProvider(
        config.FSC_API_KEY,
        timeout=config.FSC_TIMEOUT,
        retries=config.FSC_RETRIES,
        request_interval=config.FSC_REQUEST_INTERVAL,
    )


def _fetch_series(code: str, name: str) -> int:
    """Fetch and store five years of closes for one code. Returns row count."""
    spec = stock_series_spec(code, name)
    provider = _provider()
    # Three weeks past the window so the 5-year return has a base to stand on;
    # otherwise the window and the fetch end on the same day and the longest
    # return reads null on exactly the history meant to support it.
    start = dt.date.today() - dt.timedelta(days=config.FSC_HISTORY_DAYS + 21)
    metadata, observations = provider.fetch_series(spec, start=start)
    return store.save_economic_series(
        spec.series_key,
        provider_id=FSC_PROVIDER_ID,
        provider_series_id=spec.provider_series_id,
        metadata_fields=metadata,
        observations=observations,
        publisher=FSC_PUBLISHER,
        publisher_url=FSC_PUBLISHER_URL,
        series_url=spec.series_url,
        rights_status="approved",
        rights_evidence=FSC_TERMS_URL,
    )


def ensure_listings() -> dict[str, Any]:
    """Make sure the search roster exists, fetching it once if it never has.

    The scheduled batch refreshes it daily; this only covers the very first
    boot so search is not dead for up to an hour.
    """
    _require_lane()
    meta = store.kr_listings_meta()
    if meta["count"]:
        return meta
    if not config.FSC_API_KEY:
        raise KrStockDisabled
    with _fetch_lock:
        meta = store.kr_listings_meta()
        if meta["count"]:
            return meta
        bas_dt, rows = _provider().fetch_day_snapshot()
        store.save_kr_listings(rows, bas_dt)
        log.info("국내 종목 로스터 최초 수집: %s일자 %d종목", bas_dt, len(rows))
        return store.kr_listings_meta()


def search(query: str, limit: int = 10) -> dict[str, Any]:
    _require_lane()
    meta = ensure_listings()
    results = [
        {
            "code": row["srtn_cd"],
            "name": row["itms_nm"],
            "market": row["mrkt_ctg"],
            "close": row["clpr"],
            "change_percent": row["flt_rt"],
            "market_cap": row["mrkt_tot_amt"],
        }
        for row in store.search_kr_listings(query, limit)
    ]
    return {
        "query": query,
        "as_of": meta["bas_dt"],
        "results": results,
        "source": _source_block(),
    }


def _source_block() -> dict[str, Any]:
    return {
        "provider": FSC_PROVIDER_ID,
        "provider_name": FSC_PUBLISHER,
        "publisher": FSC_PUBLISHER,
        "publisher_url": FSC_PUBLISHER_URL,
        "url": FSC_STOCK_DATASET_URL,
        "notice": FSC_ATTRIBUTION,
        "basis_ko": "장 마감 기준값이며 실시간 시세가 아닙니다. 기준일 다음 영업일 13시 이후 공개됩니다.",
        "basis_en": "End-of-day values, not live quotes; published after 13:00 KST the next business day.",
    }


def _stats(observations: list[tuple[dt.date, float]]) -> dict[str, Any]:
    """Everything the analysis card shows, derived from closes alone.

    No estimation and no gap-filling: every number here is arithmetic on the
    official closes, and windows that reach past the available history are
    reported as null rather than computed on a shorter window in disguise.
    """
    dates = [d for d, _ in observations]
    closes = [v for _, v in observations]
    latest_date, latest = dates[-1], closes[-1]
    previous = closes[-2] if len(closes) > 1 else None

    def value_on_or_before(target: dt.date) -> float | None:
        # Walk back to the last trading day at or before the target date.
        for i in range(len(dates) - 1, -1, -1):
            if dates[i] <= target:
                return closes[i]
        return None

    first_date = dates[0]
    returns: dict[str, float | None] = {}
    for label, days in RETURN_WINDOWS:
        target = latest_date - dt.timedelta(days=days)
        if target < first_date:
            returns[label] = None  # 이력이 창보다 짧으면 계산하지 않는다
            continue
        base = value_on_or_before(target)
        returns[label] = round((latest / base - 1) * 100, 2) if base else None

    # Running-peak drawdown series; its minimum is the MDD.
    peak = closes[0]
    peak_date = dates[0]
    drawdowns: list[float] = []
    mdd = 0.0
    mdd_trough: dt.date | None = None
    mdd_peak: dt.date | None = None
    for date, close in observations:
        if close > peak:
            peak, peak_date = close, date
        dd = (close / peak - 1) * 100
        drawdowns.append(round(dd, 2))
        if dd < mdd:
            mdd, mdd_trough, mdd_peak = dd, date, peak_date

    year_ago = latest_date - dt.timedelta(days=366)
    window_52w = [c for d, c in observations if d >= year_ago]
    # Annualised volatility from one year of daily log returns.
    vol = None
    if len(window_52w) > 30:
        logs = [
            math.log(window_52w[i] / window_52w[i - 1])
            for i in range(1, len(window_52w))
            if window_52w[i - 1] > 0
        ]
        if len(logs) > 1:
            mean = sum(logs) / len(logs)
            variance = sum((x - mean) ** 2 for x in logs) / (len(logs) - 1)
            vol = round(math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100, 1)

    return {
        "latest": {"date": latest_date.isoformat(), "value": latest},
        "change": {
            "value": round(latest - previous, 4) if previous is not None else None,
            "percent": round((latest / previous - 1) * 100, 2) if previous else None,
        },
        "returns": returns,
        "high_52w": max(window_52w) if window_52w else None,
        "low_52w": min(window_52w) if window_52w else None,
        "drawdown_current": drawdowns[-1] if drawdowns else None,
        "mdd": {
            "value": round(mdd, 2),
            "peak_date": mdd_peak.isoformat() if mdd_peak else None,
            "trough_date": mdd_trough.isoformat() if mdd_trough else None,
        },
        "volatility_1y": vol,
        "observation_start": first_date.isoformat(),
        "observations": [
            {"date": d.isoformat(), "close": c, "drawdown": dd}
            for (d, c), dd in zip(observations[-MAX_CHART_POINTS:], drawdowns[-MAX_CHART_POINTS:], strict=True)
        ],
    }


# --- 코스피 지수군 ------------------------------------------------------------
#
# The curated family, with names exactly as the dataset publishes them.
# Ordering here is display ordering. Every row of the table comes from the
# daily snapshot — no per-index history is collected for this section.
KR_INDEX_CLASS = "KOSPI시리즈"
KR_INDEX_HEADLINE: tuple[str, ...] = (
    "코스피",
    "코스피 200",
    "코스피 100",
    "코스피 50",
    "코스피 대형주",
    "코스피 중형주",
    "코스피 소형주",
    "코스피 200 중소형주",
    "코스피 200 초대형제외 지수",
    "코스피200제외 코스피지수",
)
KR_INDEX_SECTORS: tuple[str, ...] = (
    "코스피 200 커뮤니케이션서비스",
    "코스피 200 건설",
    "코스피 200 중공업",
    "코스피 200 철강/소재",
    "코스피 200 에너지/화학",
    "코스피 200 정보기술",
    "코스피 200 금융",
    "코스피 200 생활소비재",
    "코스피 200 경기소비재",
    "코스피 200 산업재",
    "코스피 200 헬스케어",
)


class KrIndexUnavailable(RuntimeError):
    """No index snapshot has been collected yet."""


def _ensure_index_snapshot() -> dict[str, Any]:
    meta = store.kr_index_snapshot_meta()
    if meta["count"]:
        return meta
    if not config.FSC_API_KEY:
        raise KrIndexUnavailable
    with _fetch_lock:
        meta = store.kr_index_snapshot_meta()
        if meta["count"]:
            return meta
        bas_dt, rows = _provider().fetch_index_day_snapshot()
        store.save_kr_index_snapshot(rows, bas_dt)
        log.info("국내 지수 스냅샷 최초 수집: %s일자 %d지수", bas_dt, len(rows))
        return store.kr_index_snapshot_meta()


def _index_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": row["idx_nm"],
        "close": row.get("clpr"),
        "change": row.get("vs"),
        "change_percent": row.get("flt_rt"),
        "ytd_percent": row.get("ls_yr_flt_rt"),
        "high_52w": row.get("yr_hgst"),
        "high_52w_date": row.get("yr_hgst_dt"),
        "low_52w": row.get("yr_lwst"),
        "low_52w_date": row.get("yr_lwst_dt"),
        "volume": row.get("trqu"),
        "value": row.get("tr_prc"),
        "market_cap": row.get("lstg_mrkt_tot_amt"),
    }


def index_family() -> dict[str, Any]:
    """The KOSPI index family table, straight from the daily snapshot."""
    _require_lane()
    meta = _ensure_index_snapshot()
    wanted = list(KR_INDEX_HEADLINE) + list(KR_INDEX_SECTORS)
    # 분류 고정이 필수다: "IT 서비스"처럼 KOSPI와 KOSDAQ 시리즈에 같은 이름으로
    # 존재하는 지수가 있어, 이름만 보면 다른 시장의 지수를 집을 수 있다.
    by_name = {
        row["idx_nm"]: row
        for row in store.load_kr_index_snapshot(wanted, idx_csf=KR_INDEX_CLASS)
    }

    def rows_for(names: tuple[str, ...]) -> list[dict[str, Any]]:
        return [_index_row(by_name[name]) for name in names if name in by_name]

    return {
        "as_of": meta["bas_dt"],
        "groups": [
            {
                "id": "headline",
                "label": {"ko": "대표 지수", "en": "Headline indices"},
                "rows": rows_for(KR_INDEX_HEADLINE),
            },
            {
                "id": "kospi200-sectors",
                "label": {"ko": "코스피 200 섹터", "en": "KOSPI 200 sectors"},
                "rows": rows_for(KR_INDEX_SECTORS),
            },
        ],
        "source": _source_block(),
    }


def get_analysis(code: str) -> dict[str, Any]:
    """DB-first analysis for one code; a cache miss fetches synchronously."""
    _require_lane()
    code = code.strip().upper()
    series_key = f"{KR_STOCK_KEY_PREFIX}{code}"
    listing = store.get_kr_listing(code)

    record = store.get_economic_series(series_key)
    fresh = (
        record is not None
        and record.get("status") == "ok"
        and (record.get("fetched_at") or 0) > time.time() - config.FSC_MAX_AGE
    )

    if not fresh:
        failed_at = _recent_failures.get(code, 0.0)
        can_retry = time.time() - failed_at > FAILURE_MEMO_SECONDS
        if config.FSC_API_KEY and can_retry:
            with _fetch_lock:
                record = store.get_economic_series(series_key)
                fresh = (
                    record is not None
                    and record.get("status") == "ok"
                    and (record.get("fetched_at") or 0) > time.time() - config.FSC_MAX_AGE
                )
                if not fresh:
                    try:
                        _fetch_series(code, (listing or {}).get("itms_nm", ""))
                        record = store.get_economic_series(series_key)
                        _recent_failures.pop(code, None)
                    except (DataUnavailable, RateLimited, DataError, ValueError) as exc:
                        _recent_failures[code] = time.time()
                        log.warning("국내 종목 즉시조회 실패 %s: %s", code, exc)

    if record is None or not record.get("observation_count"):
        raise KrStockUnknown(code)

    observations = store.load_economic_observations(series_key)
    if len(observations) < 2:
        raise KrStockUnknown(code)

    payload = _stats(list(observations))
    payload.update({
        "code": code,
        "name": (listing or {}).get("itms_nm") or record.get("title") or code,
        "market": (listing or {}).get("mrkt_ctg"),
        "market_cap": (listing or {}).get("mrkt_tot_amt"),
        "currency": "KRW",
        "source": _source_block(),
        "freshness": {
            "status": "ok" if record.get("status") == "ok" else "stale",
            "fetched_at": record.get("fetched_at"),
        },
        "disclaimer_ko": "정보 제공 목적이며 투자 자문이 아닙니다. 과거 수익률과 낙폭은 미래를 보장하지 않습니다.",
        "disclaimer_en": "For information only, not investment advice. Past returns and drawdowns do not guarantee the future.",
    })
    return payload
