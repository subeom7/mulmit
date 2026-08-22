"""Study series for the coin chart — computed here, not in the browser.

The coin page already reports an RSI in its regime panel, and two numbers
wearing the same name must come from the same definition. So the chart's
studies are computed next to that one and travel with the candles: Wilder's
RSI (the same one `crypto_signal` reads), simple moving averages, Bollinger
bands on the population standard deviation, and MACD from exponential
averages seeded on a simple one.

Every series is exactly as long as the candle array, holding ``None`` where
its window has not filled yet, so the front end can index straight into it
without tracking offsets.

A study is a restatement of the candles we already publish — no new upstream
data and no new right. Which is also why the definitions ship with them: a
moving average is only meaningful if you know its window, and the window here
is the chart's interval, not a day.
"""

from __future__ import annotations

import math
from typing import Any

Number = float | None

MA_FAST = 20
MA_SLOW = 50
BOLLINGER_WINDOW = 20
BOLLINGER_MULTIPLE = 2.0
RSI_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# Enough resolution to redraw a price exactly at any scale BTC or a sub-cent
# coin reaches, without shipping float noise for every point.
SIGNIFICANT_DIGITS = 8


def _round(value: float | None, digits: int = SIGNIFICANT_DIGITS) -> Number:
    if value is None or not math.isfinite(value):
        return None
    if value == 0:
        return 0.0
    return round(value, -int(math.floor(math.log10(abs(value)))) + (digits - 1))


def sma_series(values: list[float], window: int) -> list[Number]:
    """Simple moving average, ``None`` until the window fills."""
    if window <= 0:
        return [None] * len(values)
    out: list[Number] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        out.append(_round(total / window) if index >= window - 1 else None)
    return out


def bollinger(
    values: list[float], window: int = BOLLINGER_WINDOW, multiple: float = BOLLINGER_MULTIPLE
) -> dict[str, list[Number]]:
    """Middle band plus/minus `multiple` population standard deviations."""
    middle = sma_series(values, window)
    upper: list[Number] = []
    lower: list[Number] = []
    for index, centre in enumerate(middle):
        if centre is None:
            upper.append(None)
            lower.append(None)
            continue
        window_values = values[index - window + 1 : index + 1]
        mean = sum(window_values) / window
        variance = sum((value - mean) ** 2 for value in window_values) / window
        spread = multiple * math.sqrt(variance)
        upper.append(_round(mean + spread))
        lower.append(_round(mean - spread))
    return {"middle": middle, "upper": upper, "lower": lower}


def ema_series(values: list[float], span: int) -> list[Number]:
    """Exponential moving average seeded with the simple average of the first span."""
    if span <= 0 or len(values) < span:
        return [None] * len(values)
    out: list[Number] = [None] * (span - 1)
    average = sum(values[:span]) / span
    out.append(_round(average))
    weight = 2.0 / (span + 1)
    for value in values[span:]:
        average = value * weight + average * (1 - weight)
        out.append(_round(average))
    return out


def rsi_series(closes: list[float], period: int = RSI_PERIOD) -> list[Number]:
    """Wilder's RSI at every point — the scalar in `crypto_signal.rsi` is this series' last value."""
    if len(closes) < period + 1:
        return [None] * len(closes)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = sum(delta for delta in deltas[:period] if delta > 0) / period
    losses = sum(-delta for delta in deltas[:period] if delta < 0) / period

    def level(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - (100.0 / (1.0 + gain / loss))

    # closes[period] is the first point with a full window behind it.
    out: list[Number] = [None] * period + [_round(level(gains, losses), 4)]
    for delta in deltas[period:]:
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        gains = (gains * (period - 1) + gain) / period
        losses = (losses * (period - 1) + loss) / period
        out.append(_round(level(gains, losses), 4))
    return out


def macd(
    closes: list[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> dict[str, list[Number]]:
    """MACD line, its signal average, and the histogram between them."""
    fast_line = ema_series(closes, fast)
    slow_line = ema_series(closes, slow)
    line: list[Number] = [
        _round(quick - slow_value) if quick is not None and slow_value is not None else None
        for quick, slow_value in zip(fast_line, slow_line, strict=True)
    ]
    # The signal average starts where the MACD line does, then is padded back
    # out to full length so every series shares one index.
    started = [value for value in line if value is not None]
    offset = len(line) - len(started)
    signal_line: list[Number] = [None] * offset + ema_series(started, signal)
    histogram: list[Number] = [
        _round(value - average) if value is not None and average is not None else None
        for value, average in zip(line, signal_line, strict=True)
    ]
    return {"macd": line, "signal": signal_line, "histogram": histogram}


def build(candles: list[dict[str, Any]], *, interval: str | None = None) -> dict[str, Any] | None:
    """Every study for one candle array, with the definitions that produced it."""
    closes = [row["c"] for row in candles if isinstance(row.get("c"), (int, float))]
    if len(closes) != len(candles) or not closes:
        return None
    bands = bollinger(closes)
    convergence = macd(closes)
    unit = f"{interval} 봉" if interval else "봉"
    return {
        "ma": {
            "fast": {"period": MA_FAST, "values": sma_series(closes, MA_FAST)},
            "slow": {"period": MA_SLOW, "values": sma_series(closes, MA_SLOW)},
        },
        "bollinger": {"period": BOLLINGER_WINDOW, "multiple": BOLLINGER_MULTIPLE, **bands},
        "rsi": {"period": RSI_PERIOD, "values": rsi_series(closes)},
        "macd": {"fast": MACD_FAST, "slow": MACD_SLOW, "signal": MACD_SIGNAL, **convergence},
        "basis_ko": (
            f"모두 이 차트의 종가에서 계산합니다. 이동평균 {MA_FAST}·{MA_SLOW}{unit}, "
            f"볼린저 {BOLLINGER_WINDOW}{unit}±{BOLLINGER_MULTIPLE:g}σ(모집단 표준편차), "
            f"RSI는 와일더 방식 {RSI_PERIOD}{unit}, MACD는 {MACD_FAST}·{MACD_SLOW}·{MACD_SIGNAL} 지수이동평균입니다. "
            "기간은 날짜가 아니라 봉 수이므로 간격을 바꾸면 값도 바뀝니다."
        ),
        "basis_en": (
            f"All computed from this chart's closes: SMA {MA_FAST}/{MA_SLOW}, "
            f"Bollinger {BOLLINGER_WINDOW}±{BOLLINGER_MULTIPLE:g}σ (population), "
            f"Wilder RSI {RSI_PERIOD}, MACD {MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}. "
            "Periods count bars, not days, so changing the interval changes the values."
        ),
    }
