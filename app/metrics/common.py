"""여러 지표 모듈이 공유하는 유틸."""

from __future__ import annotations

import pandas as pd

from .. import config


def periods_per_year(close: pd.Series) -> int:
    """연율화 계수를 데이터에서 추론한다.

    주식은 연 252거래일이지만 암호화폐는 365일 내내 거래된다. 전부 252로
    연율화하면 크립토의 변동성과 수익률이 √(252/365)만큼 과소 계산되고,
    "1년 예측"도 실제로는 8개월이 된다.

    관측 밀도가 연 300일을 넘으면 24/7 자산으로 본다. 실제 값(예: 364.2)을
    그대로 쓰지 않는 건 상장폐지 구간이나 데이터 공백 때문에 값이 흔들리기
    때문이다.
    """
    years = (close.index[-1] - close.index[0]).days / 365.25
    if years <= 0.5:
        return config.TRADING_DAYS
    return 365 if len(close) / years > 300 else config.TRADING_DAYS
