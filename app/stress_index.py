"""Mulmit Liquidity & Stress Index.

A composite built only from series Mulmit is licensed to publish, with the
method written down here rather than described loosely on a card.

**It is not a fear-and-greed index and is deliberately not named like one.**
CNN's index is built mostly from equity-market internals — implied volatility,
put/call ratios, junk-bond demand, price momentum and breadth — and every one
of those inputs is behind a licence this project does not hold. A composite of
what is available measures something real but different: how tight funding and
liquidity conditions are, and what the curve and the labour market say about
the cycle. Naming it for the thing it actually measures is the point.

Method, in full:

1. Each input is scored against its own history over :data:`LOOKBACK_YEARS`
   using a percentile rank, so a series is compared with itself rather than
   with an arbitrary fixed range. Percentiles need no assumption of normality,
   which matters because several of these series are strongly skewed.
2. A score is oriented so that **higher always means more stress**. An inverted
   curve, a wide SOFR-IORB spread and rising unemployment all read high.
3. Inputs are equally weighted. Nothing here justifies a fitted weight, and an
   unfitted equal weight is honest about that.
4. Missing inputs are dropped, not imputed. The response reports which ones
   contributed, and the index is withheld entirely below
   :data:`MIN_COMPONENTS`.
5. The composite is rescaled to 0-100 where 100 is maximum stress.

Nothing here is a forecast, and the index has not been validated against
subsequent returns. It summarises current conditions relative to their own
recent history, which is all a percentile composite can claim.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from . import data_rights, store

INDEX_KEY = "liquidity_stress"
INDEX_VERSION = "1.0"
LOOKBACK_YEARS = 5
# A composite of one or two things is a chart of one or two things wearing a
# costume. Below this it is withheld.
MIN_COMPONENTS = 3
MAX_PUBLIC_OBSERVATIONS = 1500


@dataclass(frozen=True)
class Component:
    """One input and the direction that counts as stress."""

    series_key: str
    label_ko: str
    label_en: str
    # True when a *low* value of the series means high stress.
    inverted: bool
    rationale_ko: str
    rationale_en: str


COMPONENTS: tuple[Component, ...] = (
    Component(
        series_key="yield_curve",
        label_ko="장단기 금리차",
        label_en="10Y-2Y curve",
        inverted=True,
        rationale_ko="곡선이 평탄하거나 역전될수록 경기 위험이 크게 반영된 것으로 본다.",
        rationale_en="A flatter or inverted curve reads as more cycle risk being priced.",
    ),
    Component(
        series_key="reverse_repo",
        label_ko="역레포 잔액",
        label_en="Overnight reverse repo",
        inverted=True,
        rationale_ko="잔액이 줄어들수록 시장으로 되돌릴 유동성 완충이 얇아진다.",
        rationale_en="A smaller balance leaves a thinner cushion of liquidity to return to markets.",
    ),
    Component(
        series_key="reserve_balances",
        label_ko="지급준비금",
        label_en="Reserve balances",
        inverted=True,
        rationale_ko="준비금이 낮을수록 은행 시스템의 결제 여력이 빠듯하다.",
        rationale_en="Lower reserves mean tighter settlement capacity in the banking system.",
    ),
    Component(
        series_key="treasury_general_account",
        label_ko="재무부 TGA",
        label_en="Treasury General Account",
        inverted=False,
        rationale_ko="TGA가 커질수록 그만큼의 현금이 시중에서 정부 계정으로 빠져 있다.",
        rationale_en="A larger balance is that much cash held out of the market in a government account.",
    ),
    Component(
        series_key="unemployment",
        label_ko="실업률",
        label_en="Unemployment rate",
        inverted=False,
        rationale_ko="실업률이 높을수록 경기 스트레스가 크다.",
        rationale_en="A higher rate is more cyclical stress.",
    ),
    Component(
        series_key="fx_usdkrw",
        label_ko="원·달러",
        label_en="USD/KRW",
        inverted=False,
        rationale_ko="원화가 약할수록 달러 조달 여건이 빡빡하다는 신호로 읽는다.",
        rationale_en="A weaker won reads as tighter dollar funding conditions.",
    ),
)

# Bands are descriptions of where the composite sits, not advice.
BANDS = (
    (20.0, "매우 완화", "Very loose"),
    (40.0, "완화", "Loose"),
    (60.0, "중립", "Neutral"),
    (80.0, "긴축", "Tight"),
    (100.1, "매우 긴축", "Very tight"),
)


class StressIndexUnavailable(RuntimeError):
    """Raised when too few licensed inputs are available to compose an index."""

    def __init__(self, available: int, required: int = MIN_COMPONENTS) -> None:
        super().__init__(f"{available} of {required} required components available")
        self.available = available
        self.required = required


def _percentile_rank(history: list[float], value: float) -> float:
    """Share of the history at or below ``value``, as 0-100.

    A rank rather than a z-score because several inputs are strongly skewed —
    reverse repo spent years near a ceiling and then drained to nearly zero —
    and a rank makes no assumption about the shape of the distribution.
    """
    if not history:
        return 50.0
    at_or_below = sum(1 for item in history if item <= value)
    return at_or_below / len(history) * 100.0


def _band(score: float) -> tuple[str, str]:
    for ceiling, ko, en in BANDS:
        if score < ceiling:
            return ko, en
    return BANDS[-1][1], BANDS[-1][2]


def _load(component: Component, start: dt.date) -> list[tuple[dt.date, float]]:
    record = store.get_economic_series(component.series_key)
    if record is None:
        return []
    # The composite may only use inputs this deployment is allowed to publish.
    if not data_rights.series_values_servable(
        str(record.get("provider_id") or ""), str(record.get("rights_status") or "")
    ):
        return []
    return store.load_economic_observations(component.series_key, start=start)


def build_stress_index(as_of: dt.date | None = None) -> dict[str, Any]:
    """Compose the index from whichever licensed inputs are present."""
    as_of = as_of or dt.date.today()
    start = as_of - dt.timedelta(days=366 * LOOKBACK_YEARS)

    used: list[dict[str, Any]] = []
    skipped: list[str] = []
    for component in COMPONENTS:
        observations = _load(component, start)
        if len(observations) < 2:
            skipped.append(component.series_key)
            continue
        history = [value for _, value in observations]
        latest_date, latest_value = observations[-1]
        rank = _percentile_rank(history, latest_value)
        # Orient every score so that higher always means more stress.
        score = 100.0 - rank if component.inverted else rank
        used.append({
            "series_key": component.series_key,
            "label": {"ko": component.label_ko, "en": component.label_en},
            "value": latest_value,
            "as_of": latest_date.isoformat(),
            "percentile": round(rank, 1),
            "score": round(score, 1),
            "inverted": component.inverted,
            "observations": len(observations),
            "rationale": {"ko": component.rationale_ko, "en": component.rationale_en},
        })

    if len(used) < MIN_COMPONENTS:
        raise StressIndexUnavailable(len(used))

    score = round(sum(item["score"] for item in used) / len(used), 1)
    band_ko, band_en = _band(score)
    return {
        "key": INDEX_KEY,
        "version": INDEX_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "label": {
            "ko": "Mulmit 유동성·스트레스 지수",
            "en": "Mulmit Liquidity & Stress Index",
        },
        "score": score,
        "scale": {"min": 0, "max": 100, "meaning_ko": "100에 가까울수록 긴축", "meaning_en": "Higher is tighter"},
        "band": {"ko": band_ko, "en": band_en},
        "as_of": max(item["as_of"] for item in used),
        "components": used,
        "missing": skipped,
        "method": {
            "lookback_years": LOOKBACK_YEARS,
            "scoring": "percentile rank of the latest value within its own history",
            "weighting": "equal",
            "missing_data": "dropped, never imputed",
            "minimum_components": MIN_COMPONENTS,
            "summary_ko": (
                f"각 입력을 최근 {LOOKBACK_YEARS}년 자기 이력 안에서 백분위로 점수화하고, "
                "스트레스가 큰 쪽이 높아지도록 방향을 맞춘 뒤 동일 가중으로 평균합니다. "
                "결측 입력은 채우지 않고 제외합니다."
            ),
            "summary_en": (
                f"Each input is scored as a percentile within its own {LOOKBACK_YEARS}-year "
                "history, oriented so higher means more stress, then equally weighted. "
                "Missing inputs are dropped rather than imputed."
            ),
        },
        "disclaimer": {
            "ko": (
                "Mulmit이 직접 산출하는 자체 지수입니다. CNN Fear & Greed를 비롯한 다른 "
                "심리 지수와 입력도 산식도 다르며 값을 비교할 수 없습니다. 변동성·옵션·"
                "신용 스프레드는 표시 권리가 없어 입력에 포함되지 않습니다. 예측이 아니며 "
                "투자 판단의 근거로 삼기에 충분하지 않습니다."
            ),
            "en": (
                "A Mulmit-computed index. Its inputs and formula differ from other sentiment "
                "gauges including CNN's Fear & Greed, and the values are not comparable. "
                "Volatility, options and credit-spread inputs are absent because Mulmit has no "
                "right to display them. It is not a forecast and is not sufficient grounds for "
                "an investment decision."
            ),
        },
    }
