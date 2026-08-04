"""티커 간 상관계수.

기존 correlation.py를 다중 티커로 확장했다. 가격이 아니라 **일간 수익률**로
계산한다. 가격 자체의 상관계수는 둘 다 우상향하기만 해도 0.9가 넘어서
분산투자 판단에 쓸 수 없다.

주의: 거래시간이 다른 시장끼리는 값이 왜곡된다. 한국장은 미국장보다 먼저
닫히므로 같은 날짜의 두 수익률이 사실은 서로 다른 뉴스를 반영한다(실제로
AAPL vs 삼성전자가 음수로 나온다). capm.py의 지연보정 베타와 같은 문제이며,
여기에는 아직 보정이 들어가 있지 않다. 같은 시장 안에서만 신뢰할 것.
"""

from __future__ import annotations

import pandas as pd

from .. import data

# 기간별 달력일수. 저장소에는 전체 이력이 한 벌만 있고 여기서 잘라 쓴다.
_PERIOD_DAYS = {
    "1mo": 30, "3mo": 91, "6mo": 182, "1y": 365,
    "2y": 730, "5y": 1826, "10y": 3652, "max": None,
}


def _window(close: pd.Series, period: str) -> pd.Series:
    days = _PERIOD_DAYS.get(period)
    if days is None:
        return close
    return close[close.index >= close.index[-1] - pd.Timedelta(days=days)]


def correlation_matrix(tickers: list[str], period: str = "1y") -> dict:
    tickers = [t.strip().upper() for t in tickers if t.strip()]
    unique = list(dict.fromkeys(tickers))
    if len(unique) < 2:
        raise ValueError("티커를 2개 이상 입력하세요.")
    if period not in _PERIOD_DAYS:
        raise ValueError(f"지원하지 않는 기간입니다: {period}")

    frame = pd.DataFrame(
        {t: _window(data.get_close(t), period) for t in unique}
    ).dropna()
    if len(frame) < 30:
        raise ValueError(f"공통 거래일이 {len(frame)}일뿐이라 상관계수를 낼 수 없습니다.")

    corr = frame.pct_change().dropna().corr()
    return {
        "tickers": unique,
        "period": period,
        "trading_days": int(len(frame) - 1),
        "start": frame.index[0].strftime("%Y-%m-%d"),
        "end": frame.index[-1].strftime("%Y-%m-%d"),
        "matrix": {
            row: {col: float(corr.loc[row, col]) for col in unique} for row in unique
        },
    }
