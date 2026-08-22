"""Hyperliquid-wide market board — movers, OI/volume leaders, funding extremes, totals.

Built from the same ``metaAndAssetCtxs`` snapshot the coin cards use (one call,
shared provider cache), under the same HIP-3 display gate and the same posture:
perpetual references on Hyperliquid's own venue, not spot quotes.  Nothing new
is fetched; the board is sorting and summing of values already relayed.

Thin markets are excluded from the movers and funding-extremes lists by a
stated notional-volume floor so a $30k market cannot top the "gainers" table
on one print; leaders by OI and volume are unfiltered by construction.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Protocol

from .crypto_market import (
    _DEFAULT_PROVIDER,
    _RIGHTS,
    FUNDING_INTERVAL_HOURS,
    annualize_funding,
    funding_side,
)
from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import API_URL, HYPERLIQUID_INFO_DOCS, MAIN_DEX, REQUEST_TYPE

BOARD_LIMIT = 8
# Movers and funding extremes only consider markets with at least this much
# 24h notional; stated in the payload so the filter is visible, not hidden.
MIN_VOLUME_USD = 1_000_000.0


class DexProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _row(market: dict[str, Any]) -> dict[str, Any] | None:
    metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
    if metadata.get("isDelisted") is True:
        return None
    context = market.get("context") if isinstance(market.get("context"), dict) else {}
    symbol = str(market.get("symbol") or "").strip()
    mark = _number(context.get("markPx")) or _number(context.get("oraclePx"))
    if not symbol or mark is None or mark <= 0:
        return None
    previous = _number(context.get("prevDayPx"))
    change = (mark - previous) / previous * 100.0 if previous else None
    volume = _number(context.get("dayNtlVlm"))
    oi_units = _number(context.get("openInterest"))
    funding = _number(context.get("funding"))
    apr = annualize_funding(funding, FUNDING_INTERVAL_HOURS)
    return {
        "symbol": symbol,
        "price": mark,
        "change_24h_percent": round(change, 4) if change is not None else None,
        "volume_24h_usd": volume,
        "open_interest_usd": round(oi_units * mark, 2) if oi_units is not None else None,
        "funding_hourly_rate": funding,
        "funding_apr_percent": round(apr, 3) if apr is not None else None,
        "funding_side": funding_side(funding),
        "source_url": f"https://app.hyperliquid.xyz/trade/{symbol}",
    }


def _top(rows: list[dict[str, Any]], key: str, *, limit: int, reverse: bool, min_volume: float | None) -> list[dict[str, Any]]:
    eligible = [
        row for row in rows
        if row.get(key) is not None and (min_volume is None or (row.get("volume_24h_usd") or 0) >= min_volume)
    ]
    eligible.sort(key=lambda row: row[key], reverse=reverse)
    return eligible[:limit]


_METHOD = {
    "ko": (
        "Hyperliquid 자체 DEX 전체 무기한선물 한 스냅샷의 정렬·합계입니다. 24h = markPx 대 prevDayPx, OI(USD) = openInterest × 가격, "
        "펀딩 APR = 시간당 펀딩 × 24 × 365. 24h 상위·하위와 펀딩 극단값은 24h 거래대금 기준 이상 시장만 대상(표시), OI·거래대금 상위는 전체."
    ),
    "en": (
        "Sorting and sums over one snapshot of every perpetual on Hyperliquid's own DEX. 24h = markPx vs prevDayPx, OI (USD) = "
        "openInterest × price, funding APR = hourly funding × 24 × 365. Movers and funding extremes consider markets above the "
        "stated 24h-volume floor; OI and volume leaders are unfiltered."
    ),
}

_DISCLAIMER = {
    "ko": (
        "Hyperliquid 무기한선물 참고값이며 현물 가격·투자 권유가 아닙니다. 얇은 시장의 수치는 한 번의 체결로도 크게 움직일 수 있습니다."
    ),
    "en": (
        "Hyperliquid perpetual references, not spot prices or recommendations. Thin markets can move on a single print."
    ),
}


def _provider_block(snapshot: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    snapshot = snapshot or {}
    return {
        "id": "hyperliquid",
        "name": "Hyperliquid",
        "url": HYPERLIQUID_INFO_DOCS,
        "api_url": API_URL,
        "request_type": REQUEST_TYPE,
        "dex": MAIN_DEX,
        "cached": bool(snapshot.get("cached")),
        "stale": bool(snapshot.get("stale")),
        "age_seconds": _number(snapshot.get("age_seconds")),
        "as_of": snapshot.get("as_of") or snapshot.get("fetched_at"),
        "error": error if error is not None else snapshot.get("error"),
    }


def build_crypto_board(provider: DexProvider | None = None, *, limit: int = BOARD_LIMIT) -> dict[str, Any]:
    client = provider or _DEFAULT_PROVIDER
    try:
        snapshot = client.fetch_dex(MAIN_DEX)
    except RateLimited:
        return _empty("rate_limited")
    except DataUnavailable:
        return _empty("unavailable")

    rows = [row for row in (_row(m) for m in snapshot.get("markets") or [] if isinstance(m, dict)) if row]
    total_oi = sum(row["open_interest_usd"] for row in rows if row["open_interest_usd"] is not None)
    total_volume = sum(row["volume_24h_usd"] for row in rows if row["volume_24h_usd"] is not None)
    return {
        "generated_at": _iso_utc(),
        "as_of": snapshot.get("as_of") or snapshot.get("fetched_at"),
        "provider": _provider_block(snapshot, None),
        "totals": {
            "markets": len(rows),
            "open_interest_usd": round(total_oi, 2),
            "volume_24h_usd": round(total_volume, 2),
            "basis": "sum over all listed Hyperliquid perpetuals in this snapshot",
        },
        "filters": {"limit": limit, "min_volume_usd_for_movers_and_funding": MIN_VOLUME_USD},
        "movers": {
            "gainers": _top(rows, "change_24h_percent", limit=limit, reverse=True, min_volume=MIN_VOLUME_USD),
            "losers": _top(rows, "change_24h_percent", limit=limit, reverse=False, min_volume=MIN_VOLUME_USD),
        },
        "leaders": {
            "open_interest": _top(rows, "open_interest_usd", limit=limit, reverse=True, min_volume=None),
            "volume": _top(rows, "volume_24h_usd", limit=limit, reverse=True, min_volume=None),
        },
        "funding": {
            "highest": _top(rows, "funding_apr_percent", limit=limit, reverse=True, min_volume=MIN_VOLUME_USD),
            "lowest": _top(rows, "funding_apr_percent", limit=limit, reverse=False, min_volume=MIN_VOLUME_USD),
        },
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
        "rights": _RIGHTS,
    }


def _empty(error: str) -> dict[str, Any]:
    return {
        "generated_at": _iso_utc(),
        "as_of": None,
        "provider": _provider_block(None, error),
        "totals": {"markets": 0, "open_interest_usd": None, "volume_24h_usd": None},
        "filters": {"limit": BOARD_LIMIT, "min_volume_usd_for_movers_and_funding": MIN_VOLUME_USD},
        "movers": {"gainers": [], "losers": []},
        "leaders": {"open_interest": [], "volume": []},
        "funding": {"highest": [], "lowest": []},
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
        "rights": _RIGHTS,
    }
