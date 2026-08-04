"""데이터 공급자 레지스트리.

유료 API로 갈아탈 때 여기에 한 줄 추가하고 PROVIDER 환경변수만 바꾸면 된다.
"""

from __future__ import annotations

from functools import cache

from .. import config
from .base import (
    DataError,
    DataUnavailable,
    PriceProvider,
    RateLimited,
    normalize_close,
)

__all__ = [
    "DataError",
    "DataUnavailable",
    "PriceProvider",
    "RateLimited",
    "get_provider",
    "normalize_close",
]


@cache
def get_provider(name: str | None = None) -> PriceProvider:
    name = (name or config.PROVIDER).strip().lower()
    if name == "yahoo":
        from .yahoo import YahooProvider

        return YahooProvider()
    raise ValueError(f"알 수 없는 데이터 공급자입니다: {name}")
