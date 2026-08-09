"""기본 수익률/위험 지표."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .common import periods_per_year

# (라벨, 달력일수) — 상장 이력이 부족하면 해당 항목은 None
_PERIODS = (
    ("1m", 30),
    ("3m", 91),
    ("6m", 182),
    ("1y", 365),
    ("3y", 1095),
    ("5y", 1826),
    ("10y", 3652),
)


def _return_since(close: pd.Series, days: int) -> float | None:
    cutoff = close.index[-1] - pd.Timedelta(days=days)
    if close.index[0] > cutoff:
        return None
    window = close[close.index >= cutoff]
    if len(window) < 2:
        return None
    return float(window.iloc[-1] / window.iloc[0] - 1.0)


def _cagr(close: pd.Series) -> float:
    years = (close.index[-1] - close.index[0]).days / 365.25
    if years <= 0:
        return float("nan")
    return float((close.iloc[-1] / close.iloc[0]) ** (1.0 / years) - 1.0)


def analyze(
    close: pd.Series, risk_free_rate: float, full_close: pd.Series | None = None
) -> dict:
    """가격 시리즈 하나로 계산할 수 있는 것들.

    샤프/소르티노는 CAPM 기대수익률이 아니라 **실현 수익률(CAGR)** 기준이다.

    close에는 분석 구간(기본 최근 10년)을, full_close에는 전체 상장 이력을
    넘긴다. 위험 지표는 CAPM/시뮬레이션과 같은 구간에서 뽑아야 대시보드에
    변동성 숫자가 두 개 뜨는 일이 없고, 기간별 수익률 표만 전체 이력을 쓴다.
    """
    full_close = close if full_close is None else full_close
    ppy = periods_per_year(close)  # 주식 252 / 크립토 365
    returns = close.pct_change().dropna()
    daily_vol = float(returns.std(ddof=1))
    annual_vol = daily_vol * np.sqrt(ppy)
    cagr = _cagr(close)

    # 하방편차: 손실 구간의 변동성만 (소르티노 분모)
    downside = np.minimum(returns.to_numpy(dtype="float64"), 0.0)
    downside_dev = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(ppy))

    sharpe = float((cagr - risk_free_rate) / annual_vol) if annual_vol > 0 else None
    sortino = float((cagr - risk_free_rate) / downside_dev) if downside_dev > 0 else None

    ytd_start = pd.Timestamp(year=full_close.index[-1].year, month=1, day=1)
    ytd_window = full_close[full_close.index >= ytd_start]
    ytd = float(ytd_window.iloc[-1] / ytd_window.iloc[0] - 1.0) if len(ytd_window) >= 2 else None

    # 최근 30거래일 변동성 — 전체 평균 대비 지금이 조용한지 시끄러운지
    recent_vol = (
        float(returns.iloc[-30:].std(ddof=1) * np.sqrt(ppy)) if len(returns) >= 30 else None
    )

    return {
        "last_price": float(close.iloc[-1]),
        "last_date": close.index[-1].strftime("%Y-%m-%d"),
        "change_1d": float(returns.iloc[-1]) if len(returns) else None,
        # 위험 지표가 어느 구간 기준인지 UI에서 밝혀야 오해가 없다
        "window": {
            "start": close.index[0].strftime("%Y-%m-%d"),
            "end": close.index[-1].strftime("%Y-%m-%d"),
            "years": round((close.index[-1] - close.index[0]).days / 365.25, 1),
            "periods_per_year": ppy,
        },
        "cagr": cagr,
        "annual_volatility": annual_vol,
        "recent_volatility_30d": recent_vol,
        "downside_deviation": downside_dev,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "skew": float(returns.skew()),
        "kurtosis": float(returns.kurtosis()),  # 초과첨도(정규분포=0)
        "best_day": float(returns.max()),
        "worst_day": float(returns.min()),
        "positive_day_ratio": float((returns > 0).mean()),
        # 기간별 수익률만 전체 상장 이력 기준
        "returns": {
            "ytd": ytd,
            **{label: _return_since(full_close, days) for label, days in _PERIODS},
            "max": float(full_close.iloc[-1] / full_close.iloc[0] - 1.0),
        },
    }
