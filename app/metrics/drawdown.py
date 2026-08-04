"""낙폭(drawdown) 분석.

MDD 하나만 보면 "언제, 얼마나 오래" 정보가 사라진다. -50%를 3개월 만에
회복한 종목과 7년 걸린 종목은 완전히 다른 자산이므로, 개별 낙폭 구간의
하락기간/회복기간까지 같이 낸다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import config


def drawdown_series(close: pd.Series) -> pd.Series:
    """언더워터 곡선. 전고점 대비 하락률(0 이하)."""
    return close / close.cummax() - 1.0


def max_drawdown(close: pd.Series) -> float:
    """MDD. 데이터가 없으면 0.0."""
    if len(close) < 2:
        return 0.0
    return float(drawdown_series(close).min())


def _days(a: pd.Timestamp, b: pd.Timestamp) -> int:
    return int((b - a).days)


def drawdown_episodes(close: pd.Series, top: int = 5) -> list[dict]:
    """개별 낙폭 구간을 깊은 순으로 반환.

    한 구간 = 전고점을 깬 날부터 그 고점을 회복한 날까지. 마지막 구간은
    아직 회복 중일 수 있고, 그 경우 recovered=False에 recovery_date=None.
    """
    if len(close) < 2:
        return []

    prices = close.to_numpy(dtype="float64")
    dates = close.index
    running_max = np.maximum.accumulate(prices)
    dd = prices / running_max - 1.0
    underwater = dd < 0

    episodes: list[dict] = []
    n = len(prices)
    i = 0
    while i < n:
        if not underwater[i]:
            i += 1
            continue

        start = i  # 전고점을 깬 첫날
        end = i
        while end < n and underwater[end]:
            end += 1
        # end == 회복한 날의 인덱스 (아직 회복 못 했으면 n)

        peak_idx = start - 1  # dd[0]은 항상 0이므로 start >= 1이 보장된다
        trough_idx = start + int(np.argmin(dd[start:end]))
        recovered = end < n
        recovery_date = dates[end] if recovered else None

        episodes.append(
            {
                "depth": float(dd[trough_idx]),
                "peak_date": dates[peak_idx].strftime("%Y-%m-%d"),
                "peak_price": float(prices[peak_idx]),
                "trough_date": dates[trough_idx].strftime("%Y-%m-%d"),
                "trough_price": float(prices[trough_idx]),
                "recovery_date": recovery_date.strftime("%Y-%m-%d") if recovered else None,
                "recovered": recovered,
                # 하락에 걸린 일수 / 저점에서 전고점 회복까지 걸린 일수(달력 기준)
                "decline_days": _days(dates[peak_idx], dates[trough_idx]),
                "recovery_days": _days(dates[trough_idx], recovery_date) if recovered else None,
                "total_days": _days(dates[peak_idx], recovery_date if recovered else dates[-1]),
            }
        )
        i = end

    episodes.sort(key=lambda e: e["depth"])
    return episodes[:top]


def ulcer_index(close: pd.Series) -> float:
    """언더워터 곡선의 RMS.

    MDD는 최악의 한 순간만 보지만 얼스터 지수는 '얼마나 깊게, 얼마나 오래'
    물려 있었는지를 함께 반영한다. 값이 작을수록 편안한 자산.
    """
    if len(close) < 2:
        return 0.0
    dd = drawdown_series(close)
    return float(np.sqrt(np.mean(np.square(dd.to_numpy(dtype="float64")))))


def _window_mdd(close: pd.Series, years: float) -> float | None:
    """최근 N년 구간의 MDD. 데이터가 부족하면 None."""
    if len(close) < 2:
        return None
    cutoff = close.index[-1] - pd.Timedelta(days=int(round(years * 365.25)))
    if close.index[0] > cutoff:
        return None  # 상장 이력이 짧아 해당 구간을 못 채움
    window = close[close.index >= cutoff]
    if len(window) < 2:
        return None
    return max_drawdown(window)


def analyze(close: pd.Series, top_episodes: int = 5) -> dict:
    """낙폭 지표 전체."""
    dd = drawdown_series(close)
    current = float(dd.iloc[-1])
    mdd = float(dd.min())
    trough_pos = int(dd.to_numpy().argmin())

    # 현재 물려 있다면 언제부터인지
    underwater_since = None
    if current < 0:
        # 마지막으로 전고점에 있었던 날 = 현재 낙폭 구간의 시작
        at_peak = np.flatnonzero(dd.to_numpy() >= 0)
        if len(at_peak):
            underwater_since = dd.index[at_peak[-1]].strftime("%Y-%m-%d")

    underwater_days = int((dd < 0).sum())

    # 연율화 수익률 대비 MDD = 칼마 비율
    years = max((close.index[-1] - close.index[0]).days / 365.25, 1e-9)
    cagr = float((close.iloc[-1] / close.iloc[0]) ** (1 / years) - 1) if years > 0 else float("nan")
    calmar = float(cagr / abs(mdd)) if mdd < 0 else None

    return {
        "max_drawdown": mdd,
        "max_drawdown_date": dd.index[trough_pos].strftime("%Y-%m-%d"),
        "current_drawdown": current,
        "underwater_since": underwater_since,
        "days_underwater_ratio": underwater_days / len(dd),
        "ulcer_index": ulcer_index(close),
        "calmar_ratio": calmar,
        "by_window": {
            "1y": _window_mdd(close, 1),
            "3y": _window_mdd(close, 3),
            "5y": _window_mdd(close, 5),
            "10y": _window_mdd(close, 10),
            "max": mdd,
        },
        "episodes": drawdown_episodes(close, top=top_episodes),
        "period": {
            "start": close.index[0].strftime("%Y-%m-%d"),
            "end": close.index[-1].strftime("%Y-%m-%d"),
            "trading_days": int(len(close)),
            "years": round(years, 2),
        },
    }


def rolling_window_mdd(close: pd.Series, horizon: int = config.TRADING_DAYS) -> np.ndarray:
    """과거 모든 N거래일 구간의 MDD 분포(실증 기준선).

    구간이 겹치므로 표본이 독립은 아니다. 시뮬레이션 결과가 현실과 크게
    어긋나지 않는지 대조하는 용도로만 쓴다.
    """
    prices = close.to_numpy(dtype="float64")
    if len(prices) < horizon + 1:
        return np.empty(0)
    windows = np.lib.stride_tricks.sliding_window_view(prices, horizon)
    running_max = np.maximum.accumulate(windows, axis=1)
    return (windows / running_max - 1.0).min(axis=1)
