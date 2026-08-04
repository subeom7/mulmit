"""yfinance 공급자.

야후는 데이터센터 IP에 특히 인색하다(AWS 대역은 더 그렇다). 여기서는
일시적 스파이크만 백오프로 흡수하고, 근본 대응은 store.py의 영속 저장과
ingest.py의 배치 수집이 맡는다. 요청 경로에서 이 모듈을 부르는 일은
새 티커를 처음 조회할 때뿐이어야 한다.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import pandas as pd
import yfinance as yf

from .. import config
from .base import DataUnavailable, RateLimited, normalize_close

log = logging.getLogger(__name__)

T = TypeVar("T")

try:  # yfinance 버전에 따라 없을 수 있다
    from yfinance.exceptions import YFRateLimitError
except ImportError:  # pragma: no cover
    class YFRateLimitError(Exception):  # type: ignore[no-redef]
        pass

_INFO_FIELDS = (
    "longName", "shortName", "currency", "exchange", "quoteType",
    "sector", "industry", "marketCap", "beta", "forwardPE",
    "trailingPE", "dividendYield",
)


def _is_rate_limit(exc: BaseException) -> bool:
    if isinstance(exc, (YFRateLimitError, RateLimited)):
        return True
    text = str(exc).lower()
    return "too many requests" in text or "rate limit" in text or "429" in text


def _with_retry(fn: Callable[[], T], attempts: int = 3) -> T:
    """레이트리밋에만 지수 백오프로 재시도.

    요청 경로에서 불릴 수 있으므로 최대 대기를 3초로 묶었다.
    """
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if not _is_rate_limit(exc):
                raise
            if attempt == attempts - 1:
                raise RateLimited(
                    "야후 파이낸스가 요청을 제한하고 있습니다. 잠시 후 다시 시도해 주세요."
                ) from exc
            time.sleep(1.0 * (2 ** attempt))
    raise AssertionError("unreachable")


class YahooProvider:
    name = "yahoo"

    def fetch_prices(self, ticker: str, start: dt.date | None = None) -> pd.Series:
        def load() -> pd.DataFrame:
            handle = yf.Ticker(ticker)
            if start is None:
                return handle.history(period="max", auto_adjust=True)
            # 하루 겹쳐서 받는다. 경계일이 빠지는 것보다 중복이 낫고,
            # 중복은 store 쪽 upsert가 흡수한다.
            return handle.history(
                start=start - dt.timedelta(days=1), auto_adjust=True
            )

        frame = _with_retry(load)
        if frame is None or frame.empty:
            raise DataUnavailable(f"'{ticker}' 가격 데이터를 찾을 수 없습니다.")
        return normalize_close(frame["Close"], ticker)

    def fetch_info(self, ticker: str) -> dict:
        """`.info`는 느리고 자주 실패한다. 실패해도 서비스는 굴러가야 한다."""
        out: dict[str, Any] = {}
        try:
            info = yf.Ticker(ticker).info or {}
            for key in _INFO_FIELDS:
                value = info.get(key)
                if value is not None:
                    out[key] = value
        except Exception:
            log.warning("info 조회 실패: %s", ticker, exc_info=True)
        return out

    def fetch_risk_free_rate(self) -> float:
        hist = _with_retry(
            lambda: yf.Ticker(config.RISKFREE_TICKER).history(period="5d")
        )
        if hist is None or hist.empty:
            raise DataUnavailable("무위험 수익률 조회 실패")
        close = hist["Close"].dropna()
        if close.empty:
            raise DataUnavailable("무위험 수익률 조회 실패")
        return float(close.iloc[-1]) / 100.0
