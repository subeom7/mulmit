from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app import config, store
from app.providers.base import DataUnavailable, RateLimited


@pytest.fixture
def db(tmp_path, monkeypatch):
    """테스트마다 빈 SQLite. 네트워크는 전혀 쓰지 않는다.

    권리 게이트는 전부 배포 기본값(닫힘)으로 둔다. 값을 실제로 서빙하는
    테스트는 아래 opt-in fixture 중 하나를 명시적으로 요청해야 한다.
    """
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "FRED_ENABLED", False)
    monkeypatch.setattr(config, "FRED_API_KEY", "")
    monkeypatch.setattr(config, "LEGACY_PRICE_DATA_ENABLED", False)
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", False)
    store.reset(f"sqlite:///{tmp_path / 'test.db'}")
    store.init_db()
    yield store
    store.reset()


@pytest.fixture
def legacy_price_data(db, monkeypatch):
    """Opt in only tests that intentionally exercise the quarantined Yahoo-era lane."""
    monkeypatch.setattr(config, "LEGACY_PRICE_DATA_ENABLED", True)


@pytest.fixture
def fred_serving(db, monkeypatch):
    """Open the FRED lane for tests that assert on assembled macro payloads.

    Public deployments keep this closed; these tests describe the shape a
    licensed or approved lane produces, not what mulmit.com serves today.
    """
    monkeypatch.setattr(config, "FRED_ENABLED", True)


@pytest.fixture
def hip3_public_display(monkeypatch):
    """Opt in tests that assert on served Hyperliquid HIP-3 payloads."""
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", True)


def make_close(n=400, start="2020-01-01", seed=0, drift=0.0004, vol=0.02):
    """재현 가능한 합성 종가."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start, periods=n)
    steps = rng.normal(drift, vol, n)
    return pd.Series(
        100.0 * np.exp(np.cumsum(steps)),
        index=pd.DatetimeIndex(index.date, name="Date"),
        dtype="float64",
    )


class FakeProvider:
    """호출 횟수를 세는 공급자. 원하는 실패를 주입할 수 있다."""

    name = "fake"

    def __init__(self, close=None, info=None, fail=None):
        self.close = close if close is not None else make_close()
        self.info = info if info is not None else {"longName": "테스트 종목", "currency": "USD"}
        self.fail = fail
        self.price_calls: list[tuple[str, dt.date | None]] = []
        self.info_calls: list[str] = []
        self.rate_calls = 0

    def fetch_prices(self, ticker, start=None):
        self.price_calls.append((ticker, start))
        if isinstance(self.fail, Exception):
            raise self.fail
        if start is not None:
            tail = self.close[self.close.index > pd.Timestamp(start)]
            if tail.empty:
                raise DataUnavailable(f"'{ticker}' 새 데이터 없음")
            return tail
        return self.close

    def fetch_info(self, ticker):
        self.info_calls.append(ticker)
        return dict(self.info)

    def fetch_risk_free_rate(self):
        self.rate_calls += 1
        if isinstance(self.fail, RateLimited):
            raise self.fail
        return 0.0425
