"""CAPM 회귀 + 업/다운사이드 분해.

기존 capm.py의 계산 로직을 그대로 옮기되, print 대신 dict를 반환하도록
바꾸고 결정계수/유의성/캡처비율을 추가했다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from .. import config


def _regress(y: pd.Series, x: pd.Series) -> dict:
    """y = alpha + beta * x 단순회귀."""
    if len(y) < 3:
        return {"beta": None, "alpha": None, "r_squared": None, "p_value": None}
    model = sm.OLS(y.to_numpy(), sm.add_constant(x.to_numpy())).fit()
    return {
        "beta": float(model.params[1]),
        "alpha": float(model.params[0]),  # 일간 알파
        "alpha_annual": float(model.params[0] * config.TRADING_DAYS),
        "r_squared": float(model.rsquared),
        "p_value": float(model.pvalues[1]),  # 베타가 0이라는 귀무가설
    }


def _dimson_beta(returns: pd.DataFrame) -> tuple[float, float] | None:
    """지연보정(Dimson) 베타 = 당일 계수 + 전일 계수. (베타, R²) 반환.

    거래시간이 어긋나는 시장에서는 당일 회귀가 베타를 크게 과소평가한다.
    한국장은 미국장보다 먼저 닫히므로 삼성전자의 t일 수익률에는 S&P500의
    t-1일 뉴스가 반영된다(실제로 당일 회귀로는 베타가 0.2까지 떨어진다).
    시장 수익률의 전일 항을 넣고 계수를 더하면 이 시차를 회수할 수 있다.
    """
    frame = pd.DataFrame(
        {
            "stock": returns["stock"],
            "m0": returns["market"],
            "m1": returns["market"].shift(1),
        }
    ).dropna()
    if len(frame) < 30:
        return None
    model = sm.OLS(frame["stock"].to_numpy(), sm.add_constant(frame[["m0", "m1"]].to_numpy())).fit()
    return float(model.params[1] + model.params[2]), float(model.rsquared)


def _side_metrics(returns: pd.DataFrame, stock_col: str, market_col: str, up: bool) -> dict:
    """시장 상승일/하락일만 떼어낸 지표."""
    mask = returns[market_col] > 0 if up else returns[market_col] < 0
    subset = returns[mask]
    if len(subset) < 3:
        return {"beta": None, "alpha": None, "win_rate": None, "avg_return": None,
                "capture": None, "r_squared": None, "p_value": None, "days": int(len(subset))}

    stock = subset[stock_col]
    market = subset[market_col]
    result = _regress(stock, market)
    market_mean = float(market.mean())

    return {
        **result,
        "days": int(len(subset)),
        # 시장이 오른(내린) 날 이 종목도 오른 비율
        "win_rate": float((stock > 0).mean()),
        "avg_return": float(stock.mean()),
        # 캡처비율: 시장이 1% 오를 때 이 종목은 평균 몇 % 올랐나
        "capture": float(stock.mean() / market_mean) if market_mean != 0 else None,
    }


def analyze(
    close: pd.Series,
    market_close: pd.Series,
    risk_free_rate: float,
    expected_market_return: float = config.EXPECTED_MARKET_RETURN,
    beta_from_provider: float | None = None,
) -> dict:
    """CAPM 지표 일체.

    close와 market_close는 같은 분석 구간으로 잘라서 넘길 것.
    거래일이 다른 시장(예: 한국 종목 vs S&P500)이면 교집합 날짜만 쓴다.
    """
    returns = pd.DataFrame(
        {"stock": close.pct_change(), "market": market_close.pct_change()}
    ).dropna()

    if len(returns) < 30:
        return {
            "available": False,
            "reason": f"시장 지수와 겹치는 거래일이 {len(returns)}일뿐입니다.",
        }

    overall = _regress(returns["stock"], returns["market"])
    beta = overall["beta"]
    dimson = _dimson_beta(returns)
    beta_lag_adjusted = dimson[0] if dimson else None

    # 두 베타가 크게 갈리면 거래시간 어긋남(해외 종목)으로 보고 보정치를 쓴다
    beta_effective, beta_basis = beta, "same_day"
    r_squared_effective = overall["r_squared"]
    if (
        beta is not None
        and beta_lag_adjusted is not None
        and abs(beta_lag_adjusted - beta) > 0.25 * max(abs(beta), 0.1)
    ):
        beta_effective, beta_basis = beta_lag_adjusted, "lag_adjusted"
        r_squared_effective = dimson[1]  # 실제로 쓴 회귀의 설명력을 보여야 한다

    # 상승장/하락장 분해는 당일 회귀 위에 서 있다. 그 회귀가 시차 때문에
    # 무너졌거나 설명력이 거의 없으면(R² < 5%) 분해 결과도 해석하면 안 된다.
    side_reliable = beta_basis == "same_day" and (overall["r_squared"] or 0) >= 0.05

    # CAPM 기대수익률: Rf + β(Rm - Rf)
    expected_return = (
        risk_free_rate + beta_effective * (expected_market_return - risk_free_rate)
        if beta_effective is not None
        else None
    )

    annual_vol = float(returns["stock"].std(ddof=1) * np.sqrt(config.TRADING_DAYS))
    # 사전적(ex-ante) 샤프: 실현 수익률이 아니라 CAPM 기대수익률 기준.
    # 실현 기준 샤프는 basic.analyze가 따로 낸다.
    ex_ante_sharpe = (
        float((expected_return - risk_free_rate) / annual_vol)
        if expected_return is not None and annual_vol > 0
        else None
    )

    upside = _side_metrics(returns, "stock", "market", up=True)
    downside = _side_metrics(returns, "stock", "market", up=False)

    return {
        "available": True,
        "risk_free_rate": risk_free_rate,
        "expected_market_return": expected_market_return,
        "beta": beta,
        "beta_lag_adjusted": beta_lag_adjusted,
        "beta_effective": beta_effective,
        "beta_basis": beta_basis,  # 기대수익률 계산에 실제로 쓴 베타
        "beta_from_provider": beta_from_provider,
        "alpha_daily": overall["alpha"],
        "alpha_annual": overall["alpha_annual"],
        "r_squared": overall["r_squared"],
        "r_squared_effective": r_squared_effective,
        "beta_p_value": overall["p_value"],
        "expected_return": expected_return,
        "ex_ante_sharpe": ex_ante_sharpe,
        "upside": upside,
        "downside": downside,
        "side_analysis_reliable": side_reliable,
        "sample_days": int(len(returns)),
        "period": {
            "start": returns.index[0].strftime("%Y-%m-%d"),
            "end": returns.index[-1].strftime("%Y-%m-%d"),
        },
    }
