"""낙폭 계산 검증. 손으로 답을 알 수 있는 시리즈만 쓴다(네트워크 불필요)."""

import numpy as np
import pandas as pd
import pytest

from app.metrics import drawdown


def series(values, start="2020-01-01"):
    return pd.Series(
        np.asarray(values, dtype="float64"),
        index=pd.bdate_range(start, periods=len(values)),
    )


def test_max_drawdown_basic():
    # 100 -> 110 -> 88 -> 99 -> 121, 전고점 110 대비 88이므로 -20%
    assert drawdown.max_drawdown(series([100, 110, 88, 99, 121])) == pytest.approx(-0.2)


def test_monotonic_rise_has_no_drawdown():
    assert drawdown.max_drawdown(series([1, 2, 3, 4, 5])) == pytest.approx(0.0)


def test_drawdown_series_is_never_positive():
    dd = drawdown.drawdown_series(series([100, 90, 120, 60, 130]))
    assert (dd <= 1e-12).all()
    assert dd.iloc[0] == pytest.approx(0.0)  # 첫날은 항상 전고점


def test_episode_detection_with_recovery():
    close = series([100, 110, 88, 99, 121])
    (episode,) = drawdown.drawdown_episodes(close)

    assert episode["depth"] == pytest.approx(-0.2)
    assert episode["peak_price"] == pytest.approx(110)
    assert episode["trough_price"] == pytest.approx(88)
    assert episode["recovered"] is True
    # 고점(idx1) -> 저점(idx2) -> 회복(idx4). 영업일 인덱스라 달력일과 다르다
    assert episode["peak_date"] == close.index[1].strftime("%Y-%m-%d")
    assert episode["trough_date"] == close.index[2].strftime("%Y-%m-%d")
    assert episode["recovery_date"] == close.index[4].strftime("%Y-%m-%d")


def test_unrecovered_episode_is_marked():
    (episode,) = drawdown.drawdown_episodes(series([100, 120, 60]))

    assert episode["depth"] == pytest.approx(-0.5)
    assert episode["recovered"] is False
    assert episode["recovery_date"] is None
    assert episode["recovery_days"] is None


def test_episodes_sorted_by_depth_and_limited():
    # -10%, -50%, -25% 세 구간
    close = series([100, 90, 100, 50, 100, 75, 100])
    episodes = drawdown.drawdown_episodes(close, top=2)

    assert len(episodes) == 2
    assert [round(e["depth"], 2) for e in episodes] == [-0.5, -0.25]


def test_ulcer_index_is_rms_of_underwater_curve():
    # dd = [0, 0, -0.2, -0.1, 0] -> sqrt(mean([0,0,0.04,0.01,0])) = 0.1
    assert drawdown.ulcer_index(series([100, 110, 88, 99, 121])) == pytest.approx(0.1)


def test_analyze_reports_current_drawdown_and_windows():
    close = series([100, 200, 100], start="2024-01-01")
    result = drawdown.analyze(close)

    assert result["max_drawdown"] == pytest.approx(-0.5)
    assert result["current_drawdown"] == pytest.approx(-0.5)
    assert result["underwater_since"] == close.index[1].strftime("%Y-%m-%d")
    # 상장 이력이 짧으면 장기 구간은 계산하지 않는다
    assert result["by_window"]["10y"] is None
    assert result["by_window"]["max"] == pytest.approx(-0.5)


def test_rolling_window_mdd_matches_manual_calculation():
    close = series([100, 110, 88, 99, 121])
    mdds = drawdown.rolling_window_mdd(close, horizon=3)

    # 창 3개: [100,110,88] -> -20%, [110,88,99] -> -20%, [88,99,121] -> 0%
    assert len(mdds) == 3
    assert mdds == pytest.approx([-0.2, -0.2, 0.0])


def test_rolling_window_returns_empty_when_history_too_short():
    assert len(drawdown.rolling_window_mdd(series([1, 2, 3]), horizon=10)) == 0
