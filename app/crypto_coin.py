"""Per-coin detail — one Hyperliquid market's context plus its candle history.

Same venue, same gate, same posture as the rest of the crypto section
(docs/DATA_SOURCE_REGISTER.md §3.1, ``DS-2026-001``): Hyperliquid's own
perpetual listings, relayed by the server, labelled as perpetual references
rather than spot quotes.  The market context reuses the coin-card builder the
overview already serves, so a coin's numbers cannot disagree between the tape
and its detail page.  Candles come from the same ``candleSnapshot`` endpoint
the daily-history lane uses, one bounded window per interval, cached in the
request path so a page view does not mean a fresh upstream call.

No third-party chart or price feed is embedded: the page draws these candles
itself, which keeps the displayed venue honest (Hyperliquid perpetuals) and
keeps the page free of a third-party iframe.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any, Protocol

from . import crypto_indicators, crypto_signal
from .crypto_market import (
    _DEFAULT_PROVIDER,
    _RIGHTS,
    COIN_SPECS,
    CoinSpec,
    _coin_card,
)
from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import API_URL, HYPERLIQUID_INFO_DOCS, MAIN_DEX


class CoinProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...

    def fetch_predicted_fundings(self) -> dict[str, Any]: ...

    def fetch_candles(self, symbol: str, *, interval: str, start: dt.datetime, end: dt.datetime) -> dict[str, Any]: ...


# Interval → (window length, how long a served payload may be cached).  The
# windows are chosen so every interval returns a few hundred candles: enough to
# read a trend, small enough to send.
INTERVALS: dict[str, dict[str, Any]] = {
    "15m": {"window": dt.timedelta(days=2), "cache_seconds": 30, "label": {"ko": "15분", "en": "15m"}},
    "1h": {"window": dt.timedelta(days=14), "cache_seconds": 60, "label": {"ko": "1시간", "en": "1h"}},
    "4h": {"window": dt.timedelta(days=60), "cache_seconds": 120, "label": {"ko": "4시간", "en": "4h"}},
    "1d": {"window": dt.timedelta(days=365), "cache_seconds": 300, "label": {"ko": "1일", "en": "1d"}},
}
DEFAULT_INTERVAL = "1h"
MAX_CANDLES = 800


class CoinNotFound(Exception):
    """The symbol is not a live market on Hyperliquid's own venue."""

    def __init__(self, symbol: str) -> None:
        super().__init__(symbol)
        self.symbol = symbol


class CoinUnavailable(Exception):
    """The venue itself could not be reached; ``reason`` is rate_limited or unavailable."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _iso_utc(moment: dt.datetime | None = None) -> str:
    return (moment or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _millis_iso(value: Any) -> str | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    return dt.datetime.fromtimestamp(millis / 1000, dt.UTC).isoformat().replace("+00:00", "Z")


def coin_spec(symbol: str) -> CoinSpec:
    """Curated coins keep their Korean name; every other listing shows its symbol."""
    for spec in COIN_SPECS:
        if spec.symbol.casefold() == symbol.casefold():
            return spec
    return CoinSpec(symbol, symbol, symbol)


def curated_symbols() -> list[str]:
    return [spec.symbol for spec in COIN_SPECS]


def resolve_symbol(requested: str, snapshot: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Match case-insensitively but return the venue's own casing (``kPEPE``)."""
    wanted = (requested or "").strip().casefold()
    if not wanted:
        raise CoinNotFound(requested)
    for market in snapshot.get("markets") or []:
        if not isinstance(market, dict):
            continue
        symbol = market.get("symbol")
        if not isinstance(symbol, str) or symbol.strip().casefold() != wanted:
            continue
        metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
        if metadata.get("isDelisted") is True:
            raise CoinNotFound(requested)
        return symbol.strip(), market
    raise CoinNotFound(requested)


def resolve_page_symbol(requested: str, *, provider: CoinProvider | None = None) -> str:
    """Page-route resolution: the venue decides, but a curated coin still renders during an outage."""
    client = provider or _DEFAULT_PROVIDER
    try:
        snapshot = client.fetch_dex(MAIN_DEX)
    except (RateLimited, DataUnavailable) as exc:
        for spec in COIN_SPECS:
            if spec.symbol.casefold() == (requested or "").strip().casefold():
                return spec.symbol
        raise CoinUnavailable("unavailable") from exc
    resolved, _market = resolve_symbol(requested, snapshot)
    return resolved


def parse_candles(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        opened, closed = item.get("t"), item.get("T")
        o, h, low, c = (_number(item.get(k)) for k in ("o", "h", "l", "c"))
        if None in (o, h, low, c):
            continue
        try:
            opened_ms = int(opened)
        except (TypeError, ValueError):
            continue
        rows.append({
            "t": opened_ms,
            "close_ms": int(closed) if str(closed).lstrip("-").isdigit() else None,
            "o": o, "h": h, "l": low, "c": c,
            "v": _number(item.get("v")),
            "trades": item.get("n") if isinstance(item.get("n"), int) else None,
        })
    rows.sort(key=lambda row: row["t"])
    return rows[-MAX_CANDLES:]


def _window_stats(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if not candles:
        return {"candles": 0, "open": None, "close": None, "high": None, "low": None,
                "change_percent": None, "high_at": None, "low_at": None, "volume": None}
    first, last = candles[0], candles[-1]
    high_row = max(candles, key=lambda row: row["h"])
    low_row = min(candles, key=lambda row: row["l"])
    change = ((last["c"] / first["o"] - 1.0) * 100.0) if first["o"] else None
    volume = sum(row["v"] for row in candles if row["v"] is not None)
    return {
        "candles": len(candles),
        "open": first["o"],
        "close": last["c"],
        "high": high_row["h"],
        "low": low_row["l"],
        "change_percent": round(change, 4) if change is not None else None,
        "high_at": _millis_iso(high_row["t"]),
        "low_at": _millis_iso(low_row["t"]),
        "volume_base": round(volume, 4) if volume else None,
        "from": _millis_iso(first["t"]),
        "to": _millis_iso(last.get("close_ms") or last["t"]),
    }


_METHOD = {
    "ko": (
        "가격·캔들은 Hyperliquid 자체 DEX의 무기한선물 마크가격이며 현물 거래소 호가가 아닙니다. 24시간 변화는 markPx 대 prevDayPx, "
        "펀딩 APR은 시간당 펀딩 × 24 × 365, OI(USD)는 openInterest × 현재가입니다. 구간 통계(고가·저가·변동)는 선택한 인터벌 캔들의 "
        "첫 시가와 마지막 종가 기준입니다."
    ),
    "en": (
        "Prices and candles are Hyperliquid perpetual marks on its own DEX, not spot-exchange quotes. The 24h change is markPx versus "
        "prevDayPx, funding APR is hourly funding × 24 × 365, and OI (USD) is openInterest × current price. Window statistics use the "
        "first open and last close of the selected interval's candles."
    ),
}

_DISCLAIMER = {
    "ko": (
        "Hyperliquid 무기한선물 참고값이며 현물 가격·원화 시세·투자 권유가 아닙니다. 유동성이 낮은 시장은 한 번의 체결로도 크게 움직입니다."
    ),
    "en": (
        "Hyperliquid perpetual references — not spot prices, not KRW quotes, not a recommendation. Thin markets can move on a single print."
    ),
}


def interval_options() -> list[dict[str, Any]]:
    return [
        {"id": key, "label": spec["label"], "window_days": round(spec["window"].total_seconds() / 86400, 2)}
        for key, spec in INTERVALS.items()
    ]


def build_crypto_coin(
    symbol: str,
    *,
    interval: str = DEFAULT_INTERVAL,
    include_candles: bool = True,
    provider: CoinProvider | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """One market's live context (same builder as the tape cards) plus its candle window."""
    if interval not in INTERVALS:
        raise ValueError(f"unsupported interval: {interval}")
    client = provider or _DEFAULT_PROVIDER
    try:
        snapshot = client.fetch_dex(MAIN_DEX)
    except RateLimited as exc:
        raise CoinUnavailable("rate_limited") from exc
    except DataUnavailable as exc:
        raise CoinUnavailable("unavailable") from exc

    resolved, market = resolve_symbol(symbol, snapshot)
    spec = coin_spec(resolved)
    try:
        predicted = client.fetch_predicted_fundings()
    except (RateLimited, DataUnavailable):
        predicted = None  # an enrichment; its outage costs only that column
    card = _coin_card(spec, market, snapshot, predicted)
    if card is None:
        raise CoinNotFound(symbol)

    moment = now or dt.datetime.now(dt.UTC)
    window = INTERVALS[interval]["window"]
    candles: list[dict[str, Any]] = []
    candle_error: str | None = None
    candle_as_of: str | None = None
    # The page polls the live numbers every few seconds but re-reads candles rarely;
    # ``include_candles=false`` keeps those refreshes small and skips the upstream call.
    if include_candles:
        try:
            snapshot_candles = client.fetch_candles(resolved, interval=interval, start=moment - window, end=moment)
            candles = parse_candles(snapshot_candles.get("candles"))
            candle_as_of = snapshot_candles.get("as_of") or snapshot_candles.get("fetched_at")
        except RateLimited:
            candle_error = "rate_limited"
        except DataUnavailable:
            candle_error = "unavailable"

    # The regime read always uses daily candles, so it does not change when the
    # viewer switches the chart interval. The 1d chart window already covers it.
    signal_candles, signal_as_of, signal_error = candles, candle_as_of, candle_error
    if interval != crypto_signal.SIGNAL_INTERVAL or not signal_candles:
        signal_candles, signal_as_of, signal_error = [], None, None
        try:
            start, end = crypto_signal.signal_window(moment)
            daily = client.fetch_candles(resolved, interval=crypto_signal.SIGNAL_INTERVAL, start=start, end=end)
            signal_candles = parse_candles(daily.get("candles"))
            signal_as_of = daily.get("as_of") or daily.get("fetched_at")
        except RateLimited:
            signal_error = "rate_limited"
        except DataUnavailable:
            signal_error = "unavailable"
    from . import crypto_kimchi, crypto_regime  # local imports: both read this module's parser

    signal = (
        crypto_signal.build_signal(signal_candles, card, as_of=signal_as_of)
        if signal_candles
        else {"status": "unavailable", "reason": signal_error or "no daily candles",
              "methodology": crypto_signal._METHOD, "disclaimer": crypto_signal._DISCLAIMER}
    )

    if signal.get("status") == "ok":
        signal["history"] = crypto_regime.history_for(resolved, now=moment)

    # Korean quote and premium, for the coins Upbit lists in KRW. The lane has its own
    # gate and its own rights posture; when it is closed the block is simply absent.
    try:
        krw = crypto_kimchi.build_for_coin(resolved)
    except Exception:  # noqa: BLE001 - the KRW block is an enrichment, never the reason a page fails
        krw = None

    return {
        "generated_at": _iso_utc(),
        "symbol": resolved,
        "label": {"ko": spec.label_ko, "en": spec.label_en},
        "curated": any(s.symbol == resolved for s in COIN_SPECS),
        "market": card,
        "chart": {
            "interval": interval,
            "intervals": interval_options(),
            "window_days": round(window.total_seconds() / 86400, 2),
            "as_of": candle_as_of,
            "error": candle_error,
            "omitted": not include_candles,
            "candles": candles,
            "indicators": crypto_indicators.build(candles, interval=interval) if candles else None,
            "stats": _window_stats(candles),
            "basis": "Hyperliquid candleSnapshot for this market; open/high/low/close and base-unit volume as published",
        },
        "signal": signal,
        "krw": krw,
        "links": {
            "venue": f"https://app.hyperliquid.xyz/trade/{resolved}",
            "board": "/crypto#crypto-board",
            "section": "/crypto",
        },
        "source": {
            "provider": "hyperliquid",
            "provider_name": "Hyperliquid",
            "publisher": "Hyperliquid",
            "venue": MAIN_DEX,
            "api_url": API_URL,
            "documentation_url": HYPERLIQUID_INFO_DOCS,
            "read_path": "request_path_cache",
        },
        "rights": _RIGHTS,
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
    }
