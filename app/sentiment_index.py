"""Mulmit Market Sentiment Gauge (experimental).

A second self-computed composite, built the same way as the Liquidity & Stress
Index (:mod:`app.stress_index`) but pointed at market risk appetite rather
than funding conditions. It exists because the inputs that make such a gauge
possible only became publishable in August 2026: the Office of Financial
Research's volatility and credit stress categories (a U.S. federal work), and
the stored daily closes of the Hyperliquid HIP-3 synthetic perpetuals.

**It is not CNN's Fear & Greed Index and is deliberately not named like one.**
That index uses put/call ratios, market breadth and 52-week highs/lows, none
of which this project may display, and it scores an equity index and the VIX
where this gauge scores a synthetic perpetual and realized/OFR volatility.
The values are not comparable and the bands are described as risk-off /
risk-on rather than fear / greed.

Method, in full:

1. Every input is a daily series that Mulmit already publishes or derives by
   arithmetic from published values: three from the HIP-3 closes (momentum
   against a moving average, realized volatility, equity-versus-gold relative
   return) and two from the OFR FSI (volatility and credit categories).
2. Each input is scored as the percentile rank of its value within its own
   trailing history (:data:`LOOKBACK_YEARS` for OFR; everything available for
   the perpetual-derived series, which are young). An input needs at least
   :data:`MIN_HISTORY_POINTS` points before it is eligible.
3. Scores are oriented so that **higher always means more risk appetite**:
   rising momentum and equity-over-gold read high; rising volatility and
   credit stress read low.
4. Inputs are equally weighted. Nothing here justifies a fitted weight.
5. Missing or ineligible inputs are dropped, never imputed; the response says
   which ones contributed, and the gauge is withheld below
   :data:`MIN_COMPONENTS`.
6. The composite is rescaled to 0-100 and the same arithmetic is repeated for
   each of the last :data:`HISTORY_DAYS` days to give a history, using each
   input's latest value on or before that day (never later than
   :data:`STALE_DAYS` old).

Nothing here is a forecast, and the gauge has not been validated against
subsequent returns. It summarises where current prices and stress sit
relative to their own recent history, which is all a percentile composite can
claim. Request handlers read stored data only; nothing here calls a provider.
"""

from __future__ import annotations

import datetime as dt
import math
from bisect import bisect_left
from dataclasses import dataclass
from typing import Any

from . import data_rights, hip3_history, store
from .market_assets import REALIZED_VOL_WINDOW, realized_volatility_series

INDEX_KEY = "market_sentiment"
INDEX_VERSION = "0.1-experimental"
LOOKBACK_YEARS = 5
MIN_COMPONENTS = 3
MIN_HISTORY_POINTS = 60
HISTORY_DAYS = 180
STALE_DAYS = 7
MOMENTUM_WINDOW = 50
RELATIVE_RETURN_WINDOW = 20
EQUITY_SYMBOL = "xyz:SP500"
SAFE_HAVEN_SYMBOL = "xyz:GOLD"
MAX_PUBLIC_OBSERVATIONS = 1500


@dataclass(frozen=True)
class Component:
    key: str
    label_ko: str
    label_en: str
    # True when a *high* value of the input means risk-off (scores inverted).
    inverted: bool
    source_kind: str  # "hip3_derived" | "macro_series"
    series_key: str | None
    unit: str
    rationale_ko: str
    rationale_en: str
    derivation_ko: str
    derivation_en: str


COMPONENTS: tuple[Component, ...] = (
    Component(
        key="sp500_momentum",
        label_ko="S&P 500 퍼프 모멘텀",
        label_en="S&P 500 perp momentum",
        inverted=False,
        source_kind="hip3_derived",
        series_key=None,
        unit="% vs 50d MA",
        rationale_ko="가격이 이동평균 위에 있을수록 위험선호가 강한 것으로 읽는다.",
        rationale_en="Price above its moving average reads as stronger risk appetite.",
        derivation_ko=f"xyz:SP500 일봉 종가 ÷ {MOMENTUM_WINDOW}일 단순이동평균 − 1 (%)",
        derivation_en=f"xyz:SP500 daily close ÷ {MOMENTUM_WINDOW}-day simple moving average − 1 (%)",
    ),
    Component(
        key="sp500_realized_vol",
        label_ko="S&P 500 퍼프 실현 변동성 (20일)",
        label_en="S&P 500 perp realized volatility (20d)",
        inverted=True,
        source_kind="hip3_derived",
        series_key=None,
        unit="% annualized",
        rationale_ko="실현 변동성이 높을수록 위험회피 국면으로 읽는다. VIX(내재변동성)가 아니다.",
        rationale_en="Higher realized volatility reads as risk-off. Not the VIX (implied volatility).",
        derivation_ko=f"xyz:SP500 일봉 종가 {REALIZED_VOL_WINDOW}개의 로그수익률 표본표준편차 × √252",
        derivation_en=f"Sample stdev of log returns over {REALIZED_VOL_WINDOW} xyz:SP500 daily closes × √252",
    ),
    Component(
        key="equity_vs_gold",
        label_ko="주식 대 금 상대수익 (20일)",
        label_en="Equity vs gold relative return (20d)",
        inverted=False,
        source_kind="hip3_derived",
        series_key=None,
        unit="%p",
        rationale_ko="주식이 금을 앞설수록 안전자산 수요가 약한 것으로 읽는다.",
        rationale_en="Equities outrunning gold reads as weaker safe-haven demand.",
        derivation_ko=f"xyz:SP500 {RELATIVE_RETURN_WINDOW}일 수익률 − xyz:GOLD {RELATIVE_RETURN_WINDOW}일 수익률 (%p)",
        derivation_en=f"xyz:SP500 {RELATIVE_RETURN_WINDOW}-day return − xyz:GOLD {RELATIVE_RETURN_WINDOW}-day return (pp)",
    ),
    Component(
        key="ofr_fsi_volatility",
        label_ko="변동성 스트레스 (OFR)",
        label_en="Volatility stress (OFR)",
        inverted=True,
        source_kind="macro_series",
        series_key="ofr_fsi_volatility",
        unit="index",
        rationale_ko="OFR 변동성 범주가 높을수록 위험회피로 읽는다.",
        rationale_en="A higher OFR volatility category reads as risk-off.",
        derivation_ko="OFR 금융스트레스지수 변동성 범주 (미 재무부 OFR 공표값 그대로)",
        derivation_en="OFR Financial Stress Index volatility category, as published",
    ),
    Component(
        key="ofr_fsi_credit",
        label_ko="신용 스트레스 (OFR)",
        label_en="Credit stress (OFR)",
        inverted=True,
        source_kind="macro_series",
        series_key="ofr_fsi_credit",
        unit="index",
        rationale_ko="OFR 신용 범주가 높을수록 위험회피로 읽는다.",
        rationale_en="A higher OFR credit category reads as risk-off.",
        derivation_ko="OFR 금융스트레스지수 신용 범주 (미 재무부 OFR 공표값 그대로)",
        derivation_en="OFR Financial Stress Index credit category, as published",
    ),
)

BANDS = (
    (20.0, "위험회피 강함", "Strong risk-off"),
    (40.0, "위험회피", "Risk-off"),
    (60.0, "중립", "Neutral"),
    (80.0, "위험선호", "Risk-on"),
    (100.1, "위험선호 강함", "Strong risk-on"),
)


class SentimentIndexUnavailable(RuntimeError):
    def __init__(self, available: int, required: int = MIN_COMPONENTS) -> None:
        super().__init__(f"{available} of {required} required components available")
        self.available = available
        self.required = required


Series = list[tuple[dt.date, float]]


def _percentile_rank(history: list[float], value: float) -> float:
    """Share of the history at or below ``value``, as 0-100 (50 when empty)."""
    if not history:
        return 50.0
    at_or_below = sum(1 for item in history if item <= value)
    return at_or_below / len(history) * 100.0


def _band(score: float) -> tuple[str, str]:
    for ceiling, ko, en in BANDS:
        if score < ceiling:
            return ko, en
    return BANDS[-1][1], BANDS[-1][2]


# -- inputs -----------------------------------------------------------------

def _closes(blob: dict[str, Any] | None, symbol: str) -> Series:
    rows, _ = hip3_history.observations_for(blob, symbol, days=None, limit=0)
    closes: Series = []
    for row in rows:
        try:
            date = dt.date.fromisoformat(str(row.get("date")))
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            closes.append((date, value))
    return closes


def _momentum(closes: Series, window: int = MOMENTUM_WINDOW) -> Series:
    out: Series = []
    total = 0.0
    for index, (date, value) in enumerate(closes):
        total += value
        if index >= window:
            total -= closes[index - window][1]
        if index >= window - 1:
            average = total / window
            out.append((date, (value / average - 1.0) * 100.0))
    return out


def _relative_return(equity: Series, haven: Series, window: int = RELATIVE_RETURN_WINDOW) -> Series:
    """Equity minus safe-haven trailing return, on dates both series share."""
    haven_by_date = dict(haven)
    shared = [(date, value, haven_by_date[date]) for date, value in equity if date in haven_by_date]
    out: Series = []
    for index in range(window, len(shared)):
        date, eq_now, hv_now = shared[index]
        _, eq_then, hv_then = shared[index - window]
        out.append((date, (eq_now / eq_then - hv_now / hv_then) * 100.0))
    return out


def _realized_vol(closes: Series) -> Series:
    rows = [{"date": date.isoformat(), "value": value} for date, value in closes]
    return [
        (dt.date.fromisoformat(item["date"]), float(item["value"]))
        for item in realized_volatility_series(rows)
    ]


def _macro_series(series_key: str, start: dt.date) -> Series:
    record = store.get_economic_series(series_key)
    if record is None:
        return []
    if not data_rights.series_values_servable(
        str(record.get("provider_id") or ""), str(record.get("rights_status") or "")
    ):
        return []
    return [(date, float(value)) for date, value in store.load_economic_observations(series_key, start=start)]


def _load_inputs(as_of: dt.date) -> dict[str, Series]:
    start = as_of - dt.timedelta(days=366 * LOOKBACK_YEARS)
    blob = hip3_history.load()
    equity = _closes(blob, EQUITY_SYMBOL)
    haven = _closes(blob, SAFE_HAVEN_SYMBOL)
    return {
        "sp500_momentum": _momentum(equity),
        "sp500_realized_vol": _realized_vol(equity),
        "equity_vs_gold": _relative_return(equity, haven),
        "ofr_fsi_volatility": _macro_series("ofr_fsi_volatility", start),
        "ofr_fsi_credit": _macro_series("ofr_fsi_credit", start),
    }


# -- scoring ----------------------------------------------------------------

def _score_at(series: Series, day: dt.date, lookback_days: int, inverted: bool) -> tuple[float, float, float, dt.date] | None:
    """(value, percentile, score, value_date) for the latest value on/before ``day``.

    The window is the series' own history ending at that value, bounded by
    ``lookback_days``; a value older than STALE_DAYS is treated as missing.
    """
    if not series:
        return None
    dates = [date for date, _ in series]
    position = bisect_left(dates, day + dt.timedelta(days=1)) - 1
    if position < 0:
        return None
    value_date, value = series[position]
    if (day - value_date).days > STALE_DAYS:
        return None
    window_start = value_date - dt.timedelta(days=lookback_days)
    history = [item for date, item in series[: position + 1] if date >= window_start]
    if len(history) < MIN_HISTORY_POINTS:
        return None
    rank = _percentile_rank(history, value)
    score = 100.0 - rank if inverted else rank
    return value, rank, score, value_date


def build_sentiment_index(as_of: dt.date | None = None) -> dict[str, Any]:
    """Compose the gauge from whichever publishable inputs are present."""
    as_of = as_of or dt.date.today()
    inputs = _load_inputs(as_of)
    lookback_days = 366 * LOOKBACK_YEARS

    used: list[dict[str, Any]] = []
    skipped: list[str] = []
    for component in COMPONENTS:
        series = inputs.get(component.key) or []
        scored = _score_at(series, as_of, lookback_days, component.inverted)
        if scored is None:
            skipped.append(component.key)
            continue
        value, rank, score, value_date = scored
        used.append({
            "key": component.key,
            "label": {"ko": component.label_ko, "en": component.label_en},
            "value": round(value, 4),
            "unit": component.unit,
            "as_of": value_date.isoformat(),
            "percentile": round(rank, 1),
            "score": round(score, 1),
            "inverted": component.inverted,
            "observations": len(series),
            "source_kind": component.source_kind,
            "rationale": {"ko": component.rationale_ko, "en": component.rationale_en},
            "derivation": {"ko": component.derivation_ko, "en": component.derivation_en},
        })

    if len(used) < MIN_COMPONENTS:
        raise SentimentIndexUnavailable(len(used))

    score = round(sum(item["score"] for item in used) / len(used), 1)
    band_ko, band_en = _band(score)

    # History: the same arithmetic for each recent day, so the gauge has a
    # chart rather than a number. Days with too few eligible inputs are left
    # out instead of being filled.
    history: list[dict[str, Any]] = []
    first_day = as_of - dt.timedelta(days=HISTORY_DAYS - 1)
    for offset in range(HISTORY_DAYS):
        day = first_day + dt.timedelta(days=offset)
        scores = []
        for component in COMPONENTS:
            scored = _score_at(inputs.get(component.key) or [], day, lookback_days, component.inverted)
            if scored is not None:
                scores.append(scored[2])
        if len(scores) >= MIN_COMPONENTS:
            history.append({
                "date": day.isoformat(),
                "value": round(sum(scores) / len(scores), 1),
                "components": len(scores),
            })
    history = history[-MAX_PUBLIC_OBSERVATIONS:]

    return {
        "key": INDEX_KEY,
        "version": INDEX_VERSION,
        "experimental": True,
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "label": {
            "ko": "Mulmit 시장 심리 게이지 (실험)",
            "en": "Mulmit Market Sentiment Gauge (experimental)",
        },
        "score": score,
        "scale": {
            "min": 0, "max": 100,
            "meaning_ko": "100에 가까울수록 위험선호, 0에 가까울수록 위험회피",
            "meaning_en": "Higher is more risk-on, lower is more risk-off",
        },
        "band": {"ko": band_ko, "en": band_en},
        "as_of": max(item["as_of"] for item in used),
        "components": used,
        "missing": skipped,
        "observations": history,
        "observation_count": {"returned": len(history), "limit": MAX_PUBLIC_OBSERVATIONS},
        "method": {
            "lookback_years": LOOKBACK_YEARS,
            "min_history_points": MIN_HISTORY_POINTS,
            "scoring": "percentile rank of the latest value within its own trailing history",
            "orientation": "higher always means more risk appetite",
            "weighting": "equal",
            "missing_data": "dropped, never imputed",
            "minimum_components": MIN_COMPONENTS,
            "history_days": HISTORY_DAYS,
            "summary_ko": (
                "각 입력을 자기 이력 안의 백분위로 점수화하고(OFR 범주는 최근 "
                f"{LOOKBACK_YEARS}년, 퍼프 파생 입력은 가용 이력 전체·최소 {MIN_HISTORY_POINTS}점), "
                "위험선호가 클수록 높아지도록 방향을 맞춘 뒤 동일 가중으로 평균합니다. "
                "결측·이력 부족 입력은 채우지 않고 제외하며, 같은 계산을 최근 "
                f"{HISTORY_DAYS}일에 반복해 이력을 만듭니다."
            ),
            "summary_en": (
                "Each input is scored as a percentile within its own trailing history "
                f"({LOOKBACK_YEARS} years for the OFR categories; all available history, at least "
                f"{MIN_HISTORY_POINTS} points, for the perpetual-derived inputs), oriented so higher "
                "means more risk appetite, then equally weighted. Missing or short inputs are dropped "
                f"rather than imputed, and the same arithmetic over the last {HISTORY_DAYS} days gives "
                "the history."
            ),
        },
        "disclaimer": {
            "ko": (
                "Mulmit이 직접 산출하는 실험적 지수입니다. CNN Fear & Greed를 비롯한 다른 심리 "
                "지수와 입력도 산식도 다르며 값을 비교할 수 없습니다 — 풋/콜 비율·시장 폭·52주 "
                "신고가 같은 입력은 표시 권리가 없어 포함되지 않고, 주가 입력은 현물지수가 아니라 "
                "Hyperliquid HIP-3 합성 무기한선물입니다. 예측이 아니며 투자 판단의 근거로 삼기에 "
                "충분하지 않습니다."
            ),
            "en": (
                "An experimental Mulmit-computed gauge. Its inputs and formula differ from other "
                "sentiment indexes including CNN's Fear & Greed and the values are not comparable — "
                "put/call ratios, breadth and 52-week highs are absent because Mulmit has no right to "
                "display them, and the equity input is a Hyperliquid HIP-3 synthetic perpetual, not a "
                "spot index. It is not a forecast and is not sufficient grounds for an investment "
                "decision."
            ),
        },
    }
