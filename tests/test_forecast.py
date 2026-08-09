"""미래 MDD 시뮬레이션 검증.

난수를 쓰는 코드라 "정답"을 못 박기 어렵다. 대신 반드시 성립해야 하는
성질(단조성, 재현성, 경계조건)과 손으로 검산 가능한 부분을 검증한다.
"""

import numpy as np
import pandas as pd
import pytest

from app.metrics import forecast
from app.metrics.common import periods_per_year


def trading_index(n, start="2015-01-01"):
    """미국장과 비슷한 밀도(연 252일)의 거래일 인덱스.

    pd.bdate_range는 공휴일이 없어서 연 261일이 나온다. 그대로 쓰면 연율화
    계수(252)와 어긋나 CAGR 검증이 3% 틀어진다. 29일마다 하루씩 빼서
    261 x 28/29 = 252일에 맞춘다.
    """
    raw = pd.bdate_range(start, periods=int(n * 29 / 28) + 30)
    return raw[np.arange(len(raw)) % 29 != 0][:n]


def geometric_series(n=1500, mu=0.0003, sigma=0.015, seed=7):
    """로그정규 랜덤워크. 실제 주가와 비슷한 성질을 갖는다."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(mu, sigma, n)
    return pd.Series(100 * np.exp(np.cumsum(steps)), index=trading_index(n))


# --- 경로 통계 --------------------------------------------------------------

def test_path_stats_matches_manual_calculation():
    # 1.0 -> 1.1 -> 0.88 : 고점 1.1 대비 저점 0.88이므로 MDD -20%, 최종 -12%
    path = np.array([[np.log(1.1), np.log(0.88 / 1.1)]])
    mdd, terminal = forecast._path_stats(path)

    assert mdd[0] == pytest.approx(-0.2)
    assert terminal[0] == pytest.approx(-0.12)


def test_path_stats_counts_start_as_a_peak():
    """첫날부터 하락하는 경로에서 시작점을 고점으로 안 치면 낙폭을 놓친다."""
    path = np.array([[np.log(0.9), 0.0]])
    mdd, _ = forecast._path_stats(path)
    assert mdd[0] == pytest.approx(-0.1)


def test_flat_path_has_zero_drawdown():
    mdd, terminal = forecast._path_stats(np.zeros((3, 50)))
    assert mdd == pytest.approx(0.0)
    assert terminal == pytest.approx(0.0)


def test_mdd_is_never_positive():
    result = forecast.forecast_mdd(geometric_series(), n_sims=500)
    for method in result["methods"].values():
        assert method["percentiles"]["p50"] <= 0
        assert method["percentiles"]["p95"] <= method["percentiles"]["p50"]


# --- 분포의 성질 ------------------------------------------------------------

def test_longer_horizon_means_deeper_drawdown():
    close = geometric_series()
    depths = [
        forecast.forecast_mdd(close, horizon_months=m, n_sims=2000)["headline"]["median_mdd"]
        for m in (3, 12, 36)
    ]
    assert depths[0] > depths[1] > depths[2]  # 음수라 부등호 방향이 뒤집힌다


def test_higher_volatility_means_deeper_drawdown():
    calm = forecast.forecast_mdd(geometric_series(sigma=0.008), n_sims=2000)
    wild = forecast.forecast_mdd(geometric_series(sigma=0.030), n_sims=2000)
    assert wild["headline"]["median_mdd"] < calm["headline"]["median_mdd"]


def test_higher_drift_means_shallower_drawdown():
    close = geometric_series()
    zero = forecast.forecast_mdd(close, drift_mode="zero", n_sims=3000)
    rich = forecast.forecast_mdd(close, drift_mode="custom", custom_annual_drift=0.30, n_sims=3000)
    assert rich["headline"]["median_mdd"] > zero["headline"]["median_mdd"]


def test_exceedance_probabilities_are_monotonic():
    result = forecast.forecast_mdd(geometric_series(), n_sims=2000)
    levels = result["methods"]["block_bootstrap"]["exceedance"]
    values = [levels[k] for k in sorted(levels)]
    # 더 깊은 낙폭일수록 확률이 낮아야 한다
    assert all(a >= b for a, b in zip(values, values[1:], strict=False))
    assert all(0.0 <= v <= 1.0 for v in values)


def test_seed_makes_results_reproducible():
    close = geometric_series()
    first = forecast.forecast_mdd(close, n_sims=500, seed=42)
    second = forecast.forecast_mdd(close, n_sims=500, seed=42)
    third = forecast.forecast_mdd(close, n_sims=500, seed=43)

    assert first["headline"] == second["headline"]
    assert first["headline"] != third["headline"]


def test_three_methods_broadly_agree_on_lognormal_data():
    """부트스트랩/t분포/실증 분포가 크게 어긋나면 어느 하나가 틀린 것이다."""
    result = forecast.forecast_mdd(geometric_series(n=2500), n_sims=5000)
    medians = [m["percentiles"]["p50"] for m in result["methods"].values()]

    assert len(medians) == 3
    assert max(medians) - min(medians) < 0.06  # 6%p 이내


# --- 드리프트 가정 ----------------------------------------------------------

def test_historical_drift_reproduces_actual_cagr():
    close = geometric_series()
    result = forecast.forecast_mdd(close, n_sims=200, drift_mode="historical")

    years = (close.index[-1] - close.index[0]).days / 365.25
    actual_cagr = (close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1
    assert result["assumptions"]["annual_drift"] == pytest.approx(actual_cagr, rel=0.02)


def test_zero_drift_mode():
    result = forecast.forecast_mdd(geometric_series(), n_sims=200, drift_mode="zero")
    assert result["assumptions"]["annual_drift"] == pytest.approx(0.0)
    assert result["assumptions"]["drift_mode"] == "zero"


def test_capm_drift_falls_back_when_unavailable():
    result = forecast.forecast_mdd(
        geometric_series(), n_sims=200, drift_mode="capm", capm_expected_return=None
    )
    assert result["assumptions"]["drift_mode"] == "historical"


# --- 경계조건 ---------------------------------------------------------------

def test_short_history_is_rejected():
    result = forecast.forecast_mdd(geometric_series(n=40), n_sims=200)
    assert result["available"] is False
    assert "60" in result["reason"]


def test_short_history_produces_warning():
    result = forecast.forecast_mdd(geometric_series(n=300), n_sims=200)
    assert result["available"] is True
    assert result["warnings"]


def test_block_size_shrinks_for_small_samples():
    result = forecast.forecast_mdd(geometric_series(n=80), n_sims=200, block_size=20)
    # 표본의 1/5을 넘는 블록은 같은 구간만 반복 추출하게 된다
    assert result["methods"]["block_bootstrap"]["block_size"] <= 16


def test_histogram_probabilities_sum_to_about_one():
    result = forecast.forecast_mdd(geometric_series(), n_sims=2000)
    histogram = result["methods"]["block_bootstrap"]["histogram"]

    assert len(histogram["bin_edges"]) == len(histogram["probs"]) + 1
    assert sum(histogram["probs"]) == pytest.approx(1.0, abs=0.02)
    assert all(edge <= 0 for edge in histogram["bin_edges"])


# --- 연율화 계수 ------------------------------------------------------------

def test_periods_per_year_detects_stock_vs_crypto():
    stock = pd.Series(1.0, index=trading_index(1500))
    crypto = pd.Series(1.0, index=pd.date_range("2015-01-01", periods=1500, freq="D"))

    assert periods_per_year(stock) == 252
    assert periods_per_year(crypto) == 365


def test_horizon_scales_with_asset_calendar():
    """크립토의 '1년'은 252일이 아니라 365일이어야 한다."""
    values = geometric_series(n=1500)
    crypto = pd.Series(
        values.to_numpy(), index=pd.date_range("2015-01-01", periods=1500, freq="D")
    )

    assert forecast.forecast_mdd(values, n_sims=200)["horizon_days"] == 252
    assert forecast.forecast_mdd(crypto, n_sims=200)["horizon_days"] == 365
