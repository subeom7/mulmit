"""Regime read for one market — how hot the conditions are, and which way the trend leans.

This is a *description of market conditions*, not a trade signal: every input is
shown with its raw value and its contribution, and the payload says plainly that
it is not advice.  Two numbers come out of it:

``heat``       0–100, how crowded and stretched the market looks right now —
               funding pressure, realized volatility versus its own year,
               position inside the recent range, and upside momentum extremes.
``direction``  −100…+100, which way the trend leans — moving-average structure
               and where RSI sits relative to 50.

Both are computed from data the crypto section already relays: Hyperliquid daily
candles (the same ``candleSnapshot`` the chart and the history lane use) and the
market context the coin cards already show.  Nothing is fetched from anywhere
new, and no component is a black box.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from typing import Any

SIGNAL_INTERVAL = "1d"
SIGNAL_LOOKBACK_DAYS = 400
MIN_CANDLES = 60
RANGE_WINDOW = 90
TREND_FAST = 20
TREND_SLOW = 50
RSI_PERIOD = 14
VOL_FAST_DAYS = 7
VOL_SLOW_DAYS = 30
TRADING_DAYS = 365

# Heat weights — they sum to 1.0 and are published in the payload.
WEIGHTS = {"funding": 0.30, "volatility": 0.25, "range": 0.25, "momentum": 0.20}
# Funding heat anchors, in annualised percent, matching the card badges
# (docs: |APR| ≥ 15 elevated, ≥ 30 high).
FUNDING_ANCHORS = ((0.0, 0.0), (15.0, 50.0), (30.0, 80.0), (60.0, 100.0))

HEAT_BANDS = (
    (25.0, "cool", {"ko": "냉각", "en": "cool"}),
    (45.0, "steady", {"ko": "안정", "en": "steady"}),
    (65.0, "warm", {"ko": "보통", "en": "warm"}),
    (80.0, "elevated", {"ko": "과열 주의", "en": "elevated"}),
    (101.0, "overheated", {"ko": "과열", "en": "overheated"}),
)
DIRECTION_BANDS = (
    (-25.0, "down", {"ko": "하락 우위", "en": "downward"}),
    (25.0, "flat", {"ko": "방향성 뚜렷하지 않음", "en": "no clear trend"}),
    (101.0, "up", {"ko": "상승 우위", "en": "upward"}),
)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def sma(values: list[float], window: int) -> float | None:
    if len(values) < window or window <= 0:
        return None
    return sum(values[-window:]) / window


def rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    """Wilder's RSI on closes; ``None`` until there are enough moves to smooth."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = sum(d for d in deltas[:period] if d > 0) / period
    losses = sum(-d for d in deltas[:period] if d < 0) / period
    for delta in deltas[period:]:
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        gains = (gains * (period - 1) + gain) / period
        losses = (losses * (period - 1) + loss) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def log_returns(closes: list[float]) -> list[float]:
    out: list[float] = []
    for previous, current in zip(closes, closes[1:], strict=False):
        if previous > 0 and current > 0:
            out.append(math.log(current / previous))
    return out


def realized_vol(closes: list[float], window: int) -> float | None:
    """Annualised standard deviation of daily log returns, in percent."""
    returns = log_returns(closes[-(window + 1):])
    if len(returns) < max(3, window // 2):
        return None
    return statistics.pstdev(returns) * math.sqrt(TRADING_DAYS) * 100.0


def rolling_vol_series(closes: list[float], window: int) -> list[float]:
    out: list[float] = []
    for end in range(window + 1, len(closes) + 1):
        value = realized_vol(closes[:end], window)
        if value is not None:
            out.append(value)
    return out


def percentile_rank(series: list[float], value: float | None) -> float | None:
    if value is None or not series:
        return None
    below = sum(1 for item in series if item <= value)
    return below / len(series) * 100.0


def _interpolate(anchors: tuple[tuple[float, float], ...], value: float) -> float:
    """Piecewise-linear map so the published anchors are exactly the band edges."""
    if value <= anchors[0][0]:
        return anchors[0][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:], strict=False):
        if value <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (value - x0) * (y1 - y0) / span
    return anchors[-1][1]


def _band(bands: tuple[tuple[float, str, dict[str, str]], ...], score: float) -> tuple[str, dict[str, str]]:
    for threshold, key, label in bands:
        if score < threshold:
            return key, label
    return bands[-1][1], bands[-1][2]


def _component(cid: str, label_ko: str, label_en: str, value: Any, score: float | None, note_ko: str, note_en: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": cid,
        "label": {"ko": label_ko, "en": label_en},
        "value": value,
        "heat_score": None if score is None else round(score, 1),
        "weight": WEIGHTS.get(cid),
        "note": {"ko": note_ko, "en": note_en},
        "detail": detail or {},
    }


_METHOD = {
    "ko": (
        "일봉 종가(Hyperliquid)와 현재 시장 컨텍스트만으로 계산합니다. 과열도 = 펀딩 |APR|(30%) + 30일 실현변동성의 1년 백분위(25%) + "
        f"{RANGE_WINDOW}일 고저 범위 내 위치(25%) + RSI({RSI_PERIOD})의 50 초과분(20%)을 0~100으로 합성한 값입니다. 추세는 "
        f"{TREND_FAST}·{TREND_SLOW}일 이동평균 구조(60%)와 RSI의 50 대비 위치(40%)를 −100~+100으로 합성합니다. 펀딩 환산은 "
        "|APR| 0%→0, 15%→50, 30%→80, 60%→100의 구간 선형이며 15·30%는 카드의 '다소 높음·과열' 배지와 같은 기준입니다."
    ),
    "en": (
        "Computed from Hyperliquid daily closes and the current market context only. Heat = funding |APR| (30%) + the 1-year percentile of "
        f"30-day realized volatility (25%) + position inside the {RANGE_WINDOW}-day range (25%) + how far RSI({RSI_PERIOD}) sits above 50 "
        f"(20%), combined on a 0–100 scale. Direction combines the {TREND_FAST}/{TREND_SLOW}-day moving-average structure (60%) with RSI "
        "relative to 50 (40%) on a −100…+100 scale. Funding maps piecewise-linearly (|APR| 0%→0, 15%→50, 30%→80, 60%→100); the 15% and 30% "
        "anchors are the same bands the cards badge as elevated and high."
    ),
}

_DISCLAIMER = {
    "ko": (
        "과거 가격·펀딩을 요약한 상태 지표이며 매수·매도 신호나 투자 자문이 아닙니다. 과열 구간이라고 해서 가격이 곧 내린다는 뜻이 아니고, "
        "냉각 구간이라고 해서 오른다는 뜻도 아닙니다. 같은 상태에서 시장은 어느 쪽으로든 움직일 수 있습니다."
    ),
    "en": (
        "A summary of past prices and funding — not a buy or sell signal and not investment advice. 'Overheated' does not mean the price is "
        "about to fall, and 'cool' does not mean it is about to rise; markets move either way from any of these states."
    ),
}


def _reading(heat: float, heat_label: dict[str, str], direction: float, direction_label: dict[str, str],
             components: list[dict[str, Any]]) -> dict[str, str]:
    """One sentence that names the two largest heat contributors, so the number is never bare."""
    ranked = sorted(
        (c for c in components if c["heat_score"] is not None and c["weight"]),
        key=lambda c: c["heat_score"] * c["weight"], reverse=True,
    )[:2]
    drivers_ko = ", ".join(f"{c['label']['ko']}({c['note']['ko']})" for c in ranked)
    drivers_en = ", ".join(f"{c['label']['en']} ({c['note']['en']})" for c in ranked)
    return {
        "ko": (
            f"{direction_label['ko']} · 과열도 {heat:.0f}/100 ({heat_label['ko']})"
            + (f" — 온도를 가장 많이 끌어올린 요인은 {drivers_ko}입니다." if drivers_ko else ".")
        ),
        "en": (
            f"{direction_label['en'].capitalize()} · heat {heat:.0f}/100 ({heat_label['en']})"
            + (f" — driven mostly by {drivers_en}." if drivers_en else ".")
        ),
    }


def build_signal(candles: list[dict[str, Any]], market: dict[str, Any] | None, *, as_of: str | None = None) -> dict[str, Any]:
    """``candles`` are daily rows from :mod:`app.crypto_coin`; ``market`` is the coin card."""
    closes = [row["c"] for row in candles if isinstance(row.get("c"), (int, float))]
    if len(closes) < MIN_CANDLES:
        return {
            "status": "insufficient_data",
            "reason": f"needs at least {MIN_CANDLES} daily candles, has {len(closes)}",
            "as_of": as_of,
            "methodology": _METHOD,
            "disclaimer": _DISCLAIMER,
        }

    last = closes[-1]
    fast, slow = sma(closes, TREND_FAST), sma(closes, TREND_SLOW)
    momentum = rsi(closes)
    vol_fast, vol_slow = realized_vol(closes, VOL_FAST_DAYS), realized_vol(closes, VOL_SLOW_DAYS)
    vol_history = rolling_vol_series(closes, VOL_SLOW_DAYS)
    vol_pct = percentile_rank(vol_history, vol_slow)

    window = candles[-RANGE_WINDOW:]
    high = max(row["h"] for row in window)
    low = min(row["l"] for row in window)
    span = high - low
    range_position = ((last - low) / span * 100.0) if span > 0 else 50.0
    drawdown = ((last / high - 1.0) * 100.0) if high else None

    funding_apr = None
    if isinstance(market, dict):
        funding_apr = (market.get("funding") or {}).get("apr_percent")
    funding_heat = _interpolate(FUNDING_ANCHORS, abs(funding_apr)) if isinstance(funding_apr, (int, float)) else None
    momentum_heat = _clamp((momentum - 50.0) / 30.0 * 100.0) if momentum is not None else None

    components = [
        _component(
            "funding", "펀딩 압력", "funding pressure",
            None if funding_apr is None else round(funding_apr, 2), funding_heat,
            "—" if funding_apr is None else f"APR {funding_apr:+.1f}% · {'롱 쏠림' if funding_apr > 0 else '숏 쏠림' if funding_apr < 0 else '중립'}",
            "—" if funding_apr is None else f"APR {funding_apr:+.1f}%, {'longs pay' if funding_apr > 0 else 'shorts pay' if funding_apr < 0 else 'flat'}",
            {"apr_percent": funding_apr, "anchors": [{"apr": a, "heat": h} for a, h in FUNDING_ANCHORS]},
        ),
        _component(
            "volatility", "변동성", "volatility",
            None if vol_slow is None else round(vol_slow, 1), vol_pct,
            "—" if vol_pct is None else f"30일 {vol_slow:.0f}% · 1년 상위 {100 - vol_pct:.0f}%",
            "—" if vol_pct is None else f"30d {vol_slow:.0f}%, top {100 - vol_pct:.0f}% of the year",
            {"realized_7d_percent": None if vol_fast is None else round(vol_fast, 1),
             "realized_30d_percent": None if vol_slow is None else round(vol_slow, 1),
             "percentile_1y": None if vol_pct is None else round(vol_pct, 1),
             "fast_over_slow": None if not (vol_fast and vol_slow) else round(vol_fast / vol_slow, 3),
             "samples": len(vol_history)},
        ),
        _component(
            "range", "범위 내 위치", "range position",
            round(range_position, 1), _clamp(range_position),
            f"{RANGE_WINDOW}일 범위의 {range_position:.0f}%" + ("" if drawdown is None else f" · 고점 대비 {drawdown:+.1f}%"),
            f"{range_position:.0f}% of the {RANGE_WINDOW}-day range" + ("" if drawdown is None else f", {drawdown:+.1f}% from its high"),
            {"window_days": RANGE_WINDOW, "high": high, "low": low, "drawdown_from_high_percent": None if drawdown is None else round(drawdown, 2)},
        ),
        _component(
            "momentum", "모멘텀", "momentum",
            None if momentum is None else round(momentum, 1), momentum_heat,
            "—" if momentum is None else f"RSI {momentum:.0f}" + (" · 과매수권" if momentum >= 70 else " · 과매도권" if momentum <= 30 else ""),
            "—" if momentum is None else f"RSI {momentum:.0f}" + (" · overbought" if momentum >= 70 else " · oversold" if momentum <= 30 else ""),
            {"period": RSI_PERIOD},
        ),
    ]

    scored = [(c["heat_score"], c["weight"]) for c in components if c["heat_score"] is not None and c["weight"]]
    total_weight = sum(weight for _score, weight in scored)
    heat = sum(score * weight for score, weight in scored) / total_weight if total_weight else 0.0
    heat = round(_clamp(heat), 1)

    trend_score = 0.0
    if fast is not None and slow is not None:
        above_fast, above_slow, fast_above_slow = last > fast, last > slow, fast > slow
        trend_score = (40.0 if above_fast else -40.0) + (30.0 if above_slow else -30.0) + (30.0 if fast_above_slow else -30.0)
    momentum_direction = _clamp((momentum - 50.0) / 25.0 * 100.0, -100.0, 100.0) if momentum is not None else 0.0
    direction = round(max(-100.0, min(100.0, trend_score * 0.6 + momentum_direction * 0.4)), 1)

    heat_key, heat_label = _band(HEAT_BANDS, heat)
    direction_key, direction_label = _band(DIRECTION_BANDS, direction)

    return {
        "status": "ok",
        "as_of": as_of,
        "candles_used": len(closes),
        "heat": {"score": heat, "band": heat_key, "label": heat_label, "weights": WEIGHTS},
        "direction": {
            "score": direction, "band": direction_key, "label": direction_label,
            "detail": {
                "price": last,
                f"sma_{TREND_FAST}": None if fast is None else round(fast, 6),
                f"sma_{TREND_SLOW}": None if slow is None else round(slow, 6),
                "price_over_fast": None if fast is None else last > fast,
                "fast_over_slow": None if (fast is None or slow is None) else fast > slow,
            },
        },
        "components": components,
        "reading": _reading(heat, heat_label, direction, direction_label, components),
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
        "basis": f"Hyperliquid {SIGNAL_INTERVAL} candles (up to {SIGNAL_LOOKBACK_DAYS} days) and the current market context",
    }


def signal_window(now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    return now - dt.timedelta(days=SIGNAL_LOOKBACK_DAYS), now
