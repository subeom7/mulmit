"""Chart studies — definitions, alignment with the candle array, and parity with the signal panel."""

from __future__ import annotations

import math

import pytest

from app import crypto_indicators as ind
from app import crypto_signal


def _closes(n: int = 120) -> list[float]:
    # Deterministic and not monotone: a drifting sine keeps every study in range.
    return [100.0 + 10.0 * math.sin(i / 7.0) + i * 0.35 for i in range(n)]


def _candles(closes: list[float]) -> list[dict[str, float]]:
    return [
        {"t": 1_760_000_000_000 + i * 3_600_000, "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": 10.0 + i}
        for i, c in enumerate(closes)
    ]


def test_sma_fills_only_once_its_window_has():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    series = ind.sma_series(values, 3)
    assert series[:2] == [None, None]
    assert series[2:] == [2.0, 3.0, 4.0]
    assert len(series) == len(values)
    assert ind.sma_series(values, 9) == [None] * 5


def test_bollinger_is_the_population_deviation_around_the_average():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]        # mean 5, population σ 2
    bands = ind.bollinger(values, window=8, multiple=2.0)
    assert bands["middle"][-1] == 5.0
    assert bands["upper"][-1] == 9.0 and bands["lower"][-1] == 1.0
    assert bands["upper"][:7] == [None] * 7

    flat = ind.bollinger([3.0] * 5, window=5)
    assert flat["upper"][-1] == flat["lower"][-1] == 3.0     # no spread, no bands apart


def test_ema_seeds_on_the_simple_average_then_weights_the_new_close():
    values = [1.0, 2.0, 3.0, 4.0]
    series = ind.ema_series(values, 3)
    assert series[:2] == [None, None]
    assert series[2] == 2.0                                   # (1+2+3)/3
    assert series[3] == pytest.approx(2.0 + (4.0 - 2.0) * (2 / 4))
    assert ind.ema_series([1.0, 2.0], 5) == [None, None]


def test_rsi_series_last_value_is_the_number_the_signal_panel_reports():
    """One definition, one number: the panel's scalar must be this series' tail."""
    closes = _closes()
    series = ind.rsi_series(closes)
    assert len(series) == len(closes)
    assert series[: ind.RSI_PERIOD] == [None] * ind.RSI_PERIOD
    assert series[ind.RSI_PERIOD] is not None
    assert series[-1] == pytest.approx(crypto_signal.rsi(closes), abs=1e-3)
    assert all(0.0 <= value <= 100.0 for value in series if value is not None)

    # A run of gains pins it at the top rather than dividing by a zero loss.
    assert ind.rsi_series([float(i) for i in range(40)])[-1] == 100.0


def test_macd_series_share_one_index_and_the_histogram_is_their_difference():
    closes = _closes()
    block = ind.macd(closes)
    assert len(block["macd"]) == len(block["signal"]) == len(block["histogram"]) == len(closes)
    # The line starts when the slow average does; the signal average later still.
    assert block["macd"][ind.MACD_SLOW - 2] is None and block["macd"][ind.MACD_SLOW - 1] is not None
    first_signal = next(i for i, value in enumerate(block["signal"]) if value is not None)
    assert first_signal == ind.MACD_SLOW - 1 + ind.MACD_SIGNAL - 1
    for line, average, bar in zip(block["macd"], block["signal"], block["histogram"], strict=True):
        if line is None or average is None:
            assert bar is None
        else:
            assert bar == pytest.approx(line - average, abs=1e-6)


def test_build_returns_every_series_aligned_to_the_candles_with_its_definitions():
    candles = _candles(_closes())
    block = ind.build(candles, interval="4h")
    assert block is not None
    for series in (
        block["ma"]["fast"]["values"], block["ma"]["slow"]["values"],
        block["bollinger"]["upper"], block["bollinger"]["lower"], block["bollinger"]["middle"],
        block["rsi"]["values"], block["macd"]["macd"], block["macd"]["signal"], block["macd"]["histogram"],
    ):
        assert len(series) == len(candles)
    assert block["ma"]["fast"]["period"] == 20 and block["ma"]["slow"]["period"] == 50
    assert "4h 봉" in block["basis_ko"] and "간격을 바꾸면 값도 바뀝니다" in block["basis_ko"]
    assert "Wilder RSI 14" in block["basis_en"]

    assert ind.build([]) is None
    assert ind.build([{"t": 1, "o": 1.0, "h": 1.0, "l": 1.0}]) is None   # no close, no studies


def test_short_history_yields_empty_series_rather_than_an_error():
    block = ind.build(_candles(_closes(5)), interval="1d")
    assert block is not None
    assert block["ma"]["slow"]["values"] == [None] * 5
    assert block["rsi"]["values"] == [None] * 5
    assert block["macd"]["histogram"] == [None] * 5
