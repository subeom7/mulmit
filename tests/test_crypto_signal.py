"""Regime signal — indicator maths, heat/direction composition, and the states that refuse to score."""

from __future__ import annotations

import datetime as dt
import math

import pytest

from app import crypto_signal as cs


def _series(closes: list[float], *, spread: float = 0.01) -> list[dict[str, float]]:
    """Daily rows shaped like app.crypto_coin.parse_candles output."""
    rows = []
    for index, close in enumerate(closes):
        rows.append({
            "t": 1_780_000_000_000 + index * 86_400_000,
            "o": close, "c": close,
            "h": close * (1 + spread), "l": close * (1 - spread), "v": 100.0,
        })
    return rows


def _card(apr: float | None) -> dict:
    return {"funding": {"apr_percent": apr}}


def test_rsi_sma_and_realized_vol_match_hand_computed_values():
    assert cs.sma([1, 2, 3, 4, 5], 3) == 4.0
    assert cs.sma([1, 2], 3) is None
    assert cs.rsi([100 + i for i in range(30)]) == 100.0          # only gains
    assert cs.rsi([130 - i for i in range(30)]) == 0.0            # only losses
    assert cs.rsi([100.0] * 30) == 50.0                           # no moves at all
    assert cs.rsi([1, 2, 3]) is None                              # not enough history
    # A constant 1% daily step has zero dispersion, so realized vol is 0.
    assert cs.realized_vol([100 * 1.01**i for i in range(40)], 30) == pytest.approx(0.0, abs=1e-9)
    # Alternating ±1% moves: population stdev of the log returns, annualised.
    alternating = [100.0]
    for index in range(40):
        alternating.append(alternating[-1] * (1.01 if index % 2 == 0 else 1 / 1.01))
    expected = math.log(1.01) * math.sqrt(cs.TRADING_DAYS) * 100.0
    assert cs.realized_vol(alternating, 30) == pytest.approx(expected, rel=1e-6)
    assert cs.percentile_rank([1, 2, 3, 4], 3) == 75.0
    assert cs.percentile_rank([], 3) is None and cs.percentile_rank([1], None) is None


def test_funding_anchors_and_bands_are_exactly_as_published():
    assert [cs._interpolate(cs.FUNDING_ANCHORS, apr) for apr in (0, 15, 30, 60, 500)] == [0.0, 50.0, 80.0, 100.0, 100.0]
    assert cs._interpolate(cs.FUNDING_ANCHORS, 7.5) == 25.0
    assert [cs._band(cs.HEAT_BANDS, v)[0] for v in (0, 24.9, 25, 64.9, 79.9, 80, 100)] == [
        "cool", "cool", "steady", "warm", "elevated", "overheated", "overheated"]
    assert [cs._band(cs.DIRECTION_BANDS, v)[0] for v in (-100, -25.1, -25, 0, 24.9, 25)] == [
        "down", "down", "flat", "flat", "flat", "up"]  # half-open bands, as for heat
    assert sum(cs.WEIGHTS.values()) == pytest.approx(1.0)


def test_calm_uptrend_reads_as_moderate_heat_with_an_upward_trend():
    signal = cs.build_signal(_series([100 * 1.002**i for i in range(200)]), _card(2.0), as_of="2026-08-22T00:00:00Z")
    assert signal["status"] == "ok" and signal["candles_used"] == 200
    assert signal["direction"]["band"] == "up" and signal["direction"]["score"] > 50
    assert signal["direction"]["detail"]["price_over_fast"] is True and signal["direction"]["detail"]["fast_over_slow"] is True
    by_id = {c["id"]: c for c in signal["components"]}
    assert by_id["funding"]["heat_score"] == pytest.approx(cs._interpolate(cs.FUNDING_ANCHORS, 2.0), abs=0.1)
    assert by_id["range"]["heat_score"] > 90.0   # a straight climb sits near the range high (the last wick is above the close)
    assert by_id["momentum"]["heat_score"] == pytest.approx(100.0, abs=0.1)  # RSI pinned at 100
    assert by_id["volatility"]["heat_score"] is not None
    assert signal["heat"]["score"] == pytest.approx(
        sum(by_id[k]["heat_score"] * cs.WEIGHTS[k] for k in cs.WEIGHTS), abs=0.15)
    assert "과열도" in signal["reading"]["ko"] and signal["reading"]["ko"].startswith(signal["direction"]["label"]["ko"])
    assert "매수·매도 신호나 투자 자문이 아닙니다" in signal["disclaimer"]["ko"]


def test_crowded_longs_and_a_stretched_range_push_heat_into_the_top_band():
    hot = cs.build_signal(_series([100 * 1.004**i for i in range(200)]), _card(90.0))
    assert hot["heat"]["band"] == "overheated" and hot["heat"]["score"] >= 80
    assert "펀딩 압력" in hot["reading"]["ko"]
    # Same prices, but funding is flat: the same market reads cooler.
    calm = cs.build_signal(_series([100 * 1.004**i for i in range(200)]), _card(0.0))
    assert calm["heat"]["score"] < hot["heat"]["score"]


def test_downtrend_reads_down_and_crowded_shorts_still_count_as_heat():
    closes = [200 * 0.995**i for i in range(200)]
    signal = cs.build_signal(_series(closes), _card(-40.0))
    assert signal["direction"]["band"] == "down" and signal["direction"]["score"] < -50
    by_id = {c["id"]: c for c in signal["components"]}
    assert by_id["range"]["heat_score"] < 5.0      # pinned near the range low (the last wick is below the close)
    assert by_id["momentum"]["heat_score"] == 0.0                           # RSI below 50 adds no heat
    assert by_id["funding"]["heat_score"] == pytest.approx(cs._interpolate(cs.FUNDING_ANCHORS, 40.0), abs=0.1)
    assert "숏 쏠림" in by_id["funding"]["note"]["ko"]
    assert by_id["range"]["detail"]["drawdown_from_high_percent"] < 0


def test_missing_funding_reweights_instead_of_scoring_zero():
    closes = [100 + math.sin(i / 6) * 3 for i in range(200)]
    with_funding = cs.build_signal(_series(closes), _card(0.0))
    without = cs.build_signal(_series(closes), _card(None))
    by_id = {c["id"]: c for c in without["components"]}
    assert by_id["funding"]["heat_score"] is None and by_id["funding"]["value"] is None
    others = {k: v for k, v in cs.WEIGHTS.items() if k != "funding"}
    expected = sum({c["id"]: c["heat_score"] for c in without["components"]}[k] * w for k, w in others.items()) / sum(others.values())
    assert without["heat"]["score"] == pytest.approx(expected, abs=0.15)
    assert without["heat"]["score"] >= with_funding["heat"]["score"]  # a zero-funding market is not "half hot"


def test_short_histories_and_missing_market_are_refused_rather_than_guessed():
    thin = cs.build_signal(_series([100.0 + i for i in range(cs.MIN_CANDLES - 1)]), _card(5.0))
    assert thin["status"] == "insufficient_data" and str(cs.MIN_CANDLES) in thin["reason"]
    assert "disclaimer" in thin and "methodology" in thin
    assert cs.build_signal([], _card(5.0))["status"] == "insufficient_data"
    ok = cs.build_signal(_series([100.0 + i for i in range(cs.MIN_CANDLES)]), None)
    assert ok["status"] == "ok"
    assert {c["id"]: c for c in ok["components"]}["funding"]["heat_score"] is None


def test_signal_window_covers_the_documented_lookback():
    now = dt.datetime(2026, 8, 22, tzinfo=dt.UTC)
    start, end = cs.signal_window(now)
    assert end == now and (end - start).days == cs.SIGNAL_LOOKBACK_DAYS
