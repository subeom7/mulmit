"""S&P 500 섹터 ETF 히트맵 스냅샷."""

from __future__ import annotations

import pandas as pd
import pytest

from app import config, providers
from app.main import app
from app.market_sectors import (
    PERIODS,
    build_sector_snapshot,
    calculate_period_returns,
    calculate_sector_snapshot,
)


def _close(points: list[tuple[str, float]]) -> pd.Series:
    return pd.Series(
        [value for _, value in points],
        index=pd.DatetimeIndex([date for date, _ in points], name="Date"),
        dtype="float64",
    )


def test_calendar_cutoffs_use_closest_close_at_or_before_cutoff():
    close = _close(
        [
            ("2023-06-30", 50.0),  # 1y cutoff인 2023-07-01(토) 직전
            ("2023-07-03", 60.0),
            ("2024-05-31", 80.0),  # 1m cutoff인 2024-06-01(토) 직전
            ("2024-06-03", 85.0),
            ("2024-06-21", 90.0),  # 1w cutoff 2024-06-24 이전의 최근 종가
            ("2024-06-28", 100.0),
            ("2024-07-01", 110.0),
        ]
    )

    snapshot = calculate_period_returns(close, pd.Timestamp("2024-07-01"))

    assert snapshot["baseline_dates"] == {
        "1d": "2024-06-28",
        "1w": "2024-06-21",
        "1m": "2024-05-31",
        "1y": "2023-06-30",
    }
    assert snapshot["returns"]["1d"] == pytest.approx(110.0 / 100.0 - 1.0)
    assert snapshot["returns"]["1w"] == pytest.approx(110.0 / 90.0 - 1.0)
    assert snapshot["returns"]["1m"] == pytest.approx(110.0 / 80.0 - 1.0)
    assert snapshot["returns"]["1y"] == pytest.approx(110.0 / 50.0 - 1.0)


def test_month_and_year_offsets_keep_calendar_semantics():
    close = _close(
        [
            ("2023-02-28", 50.0),
            ("2024-01-29", 80.0),
            ("2024-02-28", 90.0),
            ("2024-02-29", 100.0),
        ]
    )

    snapshot = calculate_period_returns(close, pd.Timestamp("2024-02-29"))

    assert snapshot["baseline_dates"]["1m"] == "2024-01-29"
    assert snapshot["baseline_dates"]["1y"] == "2023-02-28"


def test_snapshot_uses_one_as_of_and_reports_missing_and_stale_coverage():
    fresh = _close(
        [
            ("2023-01-03", 80.0),
            ("2024-01-02", 100.0),
            ("2024-01-03", 110.0),
        ]
    )
    stale = fresh.iloc[:-1]
    closes = {
        "XLB": fresh,
        "XLC": fresh * 2.0,
        "XLE": stale,
    }

    snapshot = calculate_sector_snapshot(closes, provider="fixture")
    sectors = {sector["ticker"]: sector for sector in snapshot["sectors"]}

    assert snapshot["as_of"] == "2024-01-03"
    assert snapshot["periods"] == list(PERIODS)
    assert snapshot["coverage"] == {
        "total": 11,
        "fresh": 2,
        "stale": 1,
        "missing": 8,
        "ratio": pytest.approx(2 / 11, abs=0.0001),
        "by_period": {
            period: {"available": 2, "total": 11, "ratio": pytest.approx(2 / 11, abs=0.0001)}
            for period in PERIODS
        },
    }
    assert sectors["XLB"]["sector_en"] == "Materials"
    assert sectors["XLB"]["sector_ko"] == "소재"
    assert sectors["XLB"]["status"] == "ok"
    assert sectors["XLE"]["status"] == "stale"
    assert sectors["XLE"]["last_date"] == "2024-01-02"
    assert all(value is None for value in sectors["XLE"]["returns"].values())
    assert sectors["XLF"]["status"] == "missing"
    assert snapshot["source"]["price_provider"] == "fixture"
    assert snapshot["source"]["read_path"] == "persisted_store_only"
    assert snapshot["basis"]["return_unit"] == "decimal"
    assert snapshot["basis"]["common_as_of"] is True


def test_request_builder_reads_store_only(monkeypatch):
    close = _close([("2024-01-02", 100.0), ("2024-01-03", 101.0)])
    loaded: list[str] = []

    def load_close(ticker: str):
        loaded.append(ticker)
        return close

    def fail_if_provider_is_called(*_args, **_kwargs):
        raise AssertionError("sector request path must not call a price provider")

    monkeypatch.setattr("app.market_sectors.store.load_close", load_close)
    monkeypatch.setattr(providers, "get_provider", fail_if_provider_is_called)

    snapshot = build_sector_snapshot()

    assert loaded == list(config.SECTOR_ETF_TICKERS)
    assert snapshot["coverage"]["fresh"] == 11
    route = next(route for route in app.routes if route.path == "/api/market/sectors")
    assert route.methods == {"GET"}
