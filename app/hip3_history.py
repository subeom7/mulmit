"""Stored daily closes for the Hyperliquid HIP-3 asset cards.

The live card endpoint (``app/market_assets.py``) deliberately makes one
snapshot request and asks for no candles, so it stays cheap.  History comes
from this batch lane instead: one ``candleSnapshot`` (1d) per asset per
refresh, kept as a single report blob and read back by the request path.

It sits behind its own gate (``HIP3_HISTORY_ENABLED``) in addition to the
display gate, because keeping a year of another venue's closes is a bigger
footprint than relaying one mark.  A deployment opts in explicitly and records
why in ``docs/DATA_SOURCE_REGISTER.md`` (DS-2026-001, revised 2026-08-21).
An explicit refusal from the listing party closes both gates at once.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time
from collections.abc import Callable
from typing import Any

from . import config, data_rights, store
from .providers.base import RateLimited
from .providers.hyperliquid import HyperliquidProvider

log = logging.getLogger(__name__)

CACHE_KEY = "hip3_history_daily_v1"
INTERVAL = "1d"
# A stored blob keeps serving for up to a week if the lane stalls; the refresh
# cadence itself is config.HIP3_HISTORY_MAX_AGE.
SERVE_TTL_SECONDS = 60 * 60 * 24 * 7
# Process-local read cache so each card request does not re-inflate the blob.
LOAD_CACHE_SECONDS = 60.0
REQUEST_GAP_SECONDS = 0.25

STATUS_WITHHELD = "withheld_pending_rights"
STATUS_COLLECTING = "collecting"
STATUS_STORED = "stored_daily_candles"

BASIS = {
    "ko": (
        "Hyperliquid candleSnapshot 일봉 종가(UTC 일 기준). 마지막 봉은 진행 중인 날이라 "
        "마감 전 값입니다. 합성 무기한선물 가격이며 현물·공식 지수 종가가 아닙니다."
    ),
    "en": (
        "Hyperliquid candleSnapshot daily closes (UTC days); the last bar is the running "
        "day. Synthetic-perpetual prices, not spot or official index closes."
    ),
}

_cache_lock = threading.Lock()
_cache: tuple[float, dict[str, Any] | None] | None = None


def enabled() -> bool:
    """History is served only while both the display gate and the history gate are open."""
    return data_rights.hip3_history_enabled()


def clear_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


# 신규 심볼 backfill 시도 시각(모노토닉 아님 — 프로세스 재시작 시 한 번 더
# 시도해도 무해하다). 블롭에 적지 않는 이유는 refresh() 주석에 있다.
_backfill_attempts: dict[str, float] = {}


def _needs_backfill(symbol: str, stored: dict[str, Any]) -> bool:
    """저장된 시리즈가 없고, 같은 주기 안에 이미 시도하지도 않았는가."""
    series = stored.get("series")
    if isinstance(series, dict) and symbol in series:
        return False
    attempted = _backfill_attempts.get(symbol)
    return attempted is None or (time.time() - attempted) >= config.HIP3_HISTORY_MAX_AGE


def _symbols() -> list[str]:
    # Imported here: market_assets imports this module for the request path.
    from .crypto_market import history_symbols
    from .market_assets import ASSETS

    symbols = [spec.provider_symbol for spec in ASSETS if spec.provider_symbol]
    # The crypto section adds Hyperliquid's own coins while it is switched on;
    # the same blob serves their realized volatility and the BTC correlations.
    for symbol in history_symbols():
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _candle_rows(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Daily closes keyed by the candle's UTC open date, sorted, later bars winning."""
    by_date: dict[str, float] = {}
    for candle in candles:
        if not isinstance(candle, dict):
            continue
        try:
            opened = int(candle["t"])
            close = float(candle["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(close):
            continue
        date = dt.datetime.fromtimestamp(opened / 1000, tz=dt.UTC).date().isoformat()
        by_date[date] = close
    return [{"date": date, "value": by_date[date]} for date in sorted(by_date)]


def refresh(
    *,
    force: bool = False,
    provider: Any | None = None,
    now: dt.datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch one daily candle window per asset and store them as a single blob.

    Per-symbol failures keep that symbol's previous rows; a rate limit stops the
    pass and leaves the rest for the next tick.  Nothing is written when no
    symbol succeeded, so a bad pass never blanks a good blob.
    """
    if not enabled():
        return {"skipped": "disabled", "attempted": 0, "updated": 0, "failed": 0}
    stored = store.load_report(CACHE_KEY, SERVE_TTL_SECONDS) or {}
    fresh = not force and store.load_report(CACHE_KEY, config.HIP3_HISTORY_MAX_AGE) is not None
    targets = _symbols()
    if fresh:
        # 블롭은 아직 신선해도, 목록에 **새로 들어온** 마켓은 시리즈가 아예 없다.
        # 그때까지 그 카드의 추이선은 비어 있는데, 전체 주기(6시간)를 기다릴
        # 이유가 없다 — 없는 것만 따로 채운다(실측: xyz:SKHX를 자산에 추가한
        # 날 하이닉스 추이선이 몇 시간 비었다).
        #
        # 계속 실패하는 심볼이 매 틱마다 상류를 두드리지 않도록, 시도한 시각을
        # 기억해 두고 같은 주기 안에서는 다시 시도하지 않는다. 이 기억은
        # 프로세스 메모리에만 둔다 — 블롭에 적으면 실패만 한 패스가 저장을
        # 일으켜 "성공한 심볼이 없으면 아무것도 쓰지 않는다"는 규칙이 깨진다.
        targets = [symbol for symbol in targets if _needs_backfill(symbol, stored)]
        if not targets:
            return {"skipped": "fresh", "attempted": 0, "updated": 0, "failed": 0}
        log.info("HIP-3 이력 신규 심볼 backfill: %s", ", ".join(targets))

    client = provider or HyperliquidProvider(
        timeout=config.HIP3_HISTORY_TIMEOUT,
        retries=1,
        max_request_seconds=config.HIP3_HISTORY_TIMEOUT * 2,
    )
    moment = now or dt.datetime.now(dt.UTC)
    start = moment - dt.timedelta(days=config.HIP3_HISTORY_DAYS)
    series: dict[str, Any] = (
        dict(stored["series"]) if isinstance(stored.get("series"), dict) else {}
    )
    result = {"attempted": 0, "updated": 0, "failed": 0, "rate_limited": 0, "observations": 0}

    symbols = targets
    for index, symbol in enumerate(symbols):
        _backfill_attempts[symbol] = time.time()
        result["attempted"] += 1
        try:
            snapshot = client.fetch_candles(symbol, interval=INTERVAL, start=start, end=moment)
        except RateLimited:
            result["rate_limited"] += 1
            log.warning("HIP-3 이력 요청 제한 — 남은 심볼은 다음 주기에 재시도")
            break
        except Exception as exc:  # noqa: BLE001 - 한 심볼 실패가 나머지를 막지 않는다
            result["failed"] += 1
            log.warning("HIP-3 이력 수집 실패 %s: %s", symbol, exc)
            continue
        rows = _candle_rows(snapshot.get("candles") or [])
        if not rows:
            result["failed"] += 1
            log.warning("HIP-3 이력 비어 있음 %s", symbol)
            continue
        series[symbol] = {
            "fetched_at": snapshot.get("fetched_at"),
            "as_of": snapshot.get("as_of"),
            "interval": INTERVAL,
            "observations": rows,
        }
        result["updated"] += 1
        result["observations"] += len(rows)
        if index < len(symbols) - 1 and REQUEST_GAP_SECONDS > 0:
            sleep(REQUEST_GAP_SECONDS)

    if result["updated"]:
        store.save_report(
            CACHE_KEY,
            {
                "generated_at": moment.isoformat().replace("+00:00", "Z"),
                "interval": INTERVAL,
                "window_days": config.HIP3_HISTORY_DAYS,
                "basis": BASIS,
                "series": series,
            },
        )
        clear_cache()
        log.info(
            "HIP-3 이력 갱신 %d/%d 심볼 (%d행)",
            result["updated"], result["attempted"], result["observations"],
        )
    return result


def load() -> dict[str, Any] | None:
    """Stored history for the request path; ``None`` while either gate is closed."""
    global _cache
    if not enabled():
        return None
    now = time.monotonic()
    with _cache_lock:
        if _cache is not None and _cache[0] > now:
            return _cache[1]
    blob = store.load_report(CACHE_KEY, SERVE_TTL_SECONDS)
    with _cache_lock:
        _cache = (now + LOAD_CACHE_SECONDS, blob)
    return blob


def observations_for(
    blob: dict[str, Any] | None,
    symbol: str,
    *,
    days: int | None,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """Rows for one symbol within ``days`` of today (UTC), plus how many were stored."""
    if not blob or not isinstance(blob.get("series"), dict):
        return [], 0
    entry = blob["series"].get(symbol)
    rows = entry.get("observations") if isinstance(entry, dict) else None
    if not isinstance(rows, list) or not rows:
        return [], 0
    available = len(rows)
    if days is not None:
        cutoff = (dt.datetime.now(dt.UTC).date() - dt.timedelta(days=days)).isoformat()
        rows = [row for row in rows if str(row.get("date", "")) >= cutoff]
    if limit and len(rows) > limit:
        rows = rows[-limit:]
    return rows, available


def series_as_of(blob: dict[str, Any] | None, symbol: str) -> str | None:
    if not blob or not isinstance(blob.get("series"), dict):
        return None
    entry = blob["series"].get(symbol)
    return entry.get("as_of") if isinstance(entry, dict) else None
