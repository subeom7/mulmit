"""데이터 공급자 인터페이스.

yfinance는 야후의 비공개 API를 긁는 것이라 공개 서비스로 재배포하는 건
야후 ToS 위반이고, 클라우드 IP는 차단도 잦다. 언젠가 유료 API(EODHD,
Twelve Data 등)로 갈아탈 걸 전제로 공급자를 갈아끼울 수 있게 분리했다.

새 공급자는 이 세 메서드만 구현하면 되고, 나머지 코드는 손대지 않는다.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol, runtime_checkable

import pandas as pd


class DataError(Exception):
    """데이터 계층 공통 예외."""


class DataUnavailable(DataError):
    """티커가 없거나 데이터가 부족할 때 (재시도해도 소용없음)."""


class RateLimited(DataError):
    """공급자가 요청을 제한했을 때 (잠시 후 재시도하면 됨)."""


@runtime_checkable
class PriceProvider(Protocol):
    """가격·메타데이터 공급자."""

    name: str

    def fetch_prices(self, ticker: str, start: dt.date | None = None) -> pd.Series:
        """조정 종가 시리즈.

        인덱스는 **tz 없는 날짜**(pd.DatetimeIndex, 시분초 없음)여야 한다.
        거래소 타임존이 붙어 있으면 서로 다른 시장의 티커를 조인할 때
        같은 날짜가 어긋난다.

        start를 주면 그 날짜 이후만 받아온다(증분 갱신용). 공급자가 증분을
        지원하지 않으면 전체를 받아서 잘라 내도 되지만, 그만큼 느려진다.

        데이터가 없으면 DataUnavailable, 제한이 걸리면 RateLimited.
        """

    def fetch_info(self, ticker: str) -> dict:
        """회사명·통화·섹터·PER 등. 실패해도 서비스는 굴러가야 하므로
        예외 대신 빈 dict를 돌려주는 쪽을 권장한다."""

    def fetch_risk_free_rate(self) -> float:
        """무위험 수익률(연, 소수). 실패하면 DataUnavailable."""


def normalize_close(raw: pd.Series, ticker: str) -> pd.Series:
    """공급자가 준 시리즈를 저장 가능한 형태로 정리.

    공급자마다 인덱스 타입과 결측 처리가 제각각이라 여기서 한 번 통일한다.
    0 이하 값은 수익률 계산에서 그대로 터지므로 제거한다.
    """
    if raw is None or len(raw) == 0:
        raise DataUnavailable(f"'{ticker}' 가격 데이터를 찾을 수 없습니다.")

    close = pd.Series(raw).dropna()
    close.index = pd.DatetimeIndex(pd.to_datetime(close.index).date, name="Date")
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close = close[close > 0].astype("float64")

    if len(close) < 2:
        raise DataUnavailable(f"'{ticker}' 유효한 가격 데이터가 부족합니다.")
    return close
