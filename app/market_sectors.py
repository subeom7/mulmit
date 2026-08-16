"""S&P 500 섹터 히트맵용 Select Sector SPDR ETF 스냅샷.

요청 경로에서는 공급자를 절대 호출하지 않는다. ingest가 미리 저장한 일봉만
읽고, 11개 섹터 ETF의 1일/1주/1개월/1년 수익률을 한 번에 계산한다.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from . import config, store

PERIODS = ("1d", "1w", "1m", "1y")

_SECTOR_NAMES = {
    "XLB": ("Materials", "소재"),
    "XLC": ("Communication Services", "커뮤니케이션 서비스"),
    "XLE": ("Energy", "에너지"),
    "XLF": ("Financials", "금융"),
    "XLI": ("Industrials", "산업재"),
    "XLK": ("Information Technology", "정보기술"),
    "XLP": ("Consumer Staples", "필수소비재"),
    "XLRE": ("Real Estate", "부동산"),
    "XLU": ("Utilities", "유틸리티"),
    "XLV": ("Health Care", "헬스케어"),
    "XLY": ("Consumer Discretionary", "경기소비재"),
}

_OFFSETS = {
    "1w": pd.DateOffset(weeks=1),
    "1m": pd.DateOffset(months=1),
    "1y": pd.DateOffset(years=1),
}


def _prepare_close(close: pd.Series | None) -> pd.Series | None:
    """저장 데이터의 불변식을 방어적으로 다시 확인한다."""
    if close is None or len(close) < 2:
        return None

    cleaned = pd.Series(close, copy=True).dropna()
    index = pd.DatetimeIndex(pd.to_datetime(cleaned.index))
    if index.tz is not None:
        index = index.tz_localize(None)
    cleaned.index = index.normalize()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")].sort_index()
    cleaned = cleaned[cleaned > 0].astype("float64")
    return cleaned if len(cleaned) >= 2 else None


def _at_or_before(close: pd.Series, cutoff: pd.Timestamp) -> tuple[float, pd.Timestamp] | None:
    """cutoff 이하의 가장 가까운 거래일 종가."""
    position = int(close.index.searchsorted(cutoff, side="right")) - 1
    if position < 0:
        return None
    return float(close.iloc[position]), close.index[position]


def calculate_period_returns(close: pd.Series, as_of: pd.Timestamp) -> dict:
    """하나의 공통 기준일에 맞춘 네 기간 수익률과 실제 기준 종가일."""
    prepared = _prepare_close(close)
    as_of = pd.Timestamp(as_of).normalize()
    empty = {period: None for period in PERIODS}
    if prepared is None or as_of not in prepared.index:
        return {"returns": empty, "baseline_dates": dict(empty)}

    through_as_of = prepared[prepared.index <= as_of]
    current = float(through_as_of.loc[as_of])
    returns: dict[str, float | None] = dict(empty)
    baseline_dates: dict[str, str | None] = dict(empty)

    previous = through_as_of[through_as_of.index < as_of]
    if not previous.empty:
        returns["1d"] = current / float(previous.iloc[-1]) - 1.0
        baseline_dates["1d"] = previous.index[-1].strftime("%Y-%m-%d")

    for period, offset in _OFFSETS.items():
        baseline = _at_or_before(through_as_of, as_of - offset)
        if baseline is None:
            continue
        price, date = baseline
        returns[period] = current / price - 1.0
        baseline_dates[period] = date.strftime("%Y-%m-%d")

    return {"returns": returns, "baseline_dates": baseline_dates}


def calculate_sector_snapshot(
    closes: Mapping[str, pd.Series | None], *, provider: str | None = None
) -> dict:
    """저장된 ETF 시리즈들로 API에 바로 내보낼 스냅샷을 만든다."""
    prepared = {
        ticker: _prepare_close(closes.get(ticker))
        for ticker in config.SECTOR_ETF_TICKERS
    }
    last_dates = [series.index[-1] for series in prepared.values() if series is not None]
    as_of = max(last_dates) if last_dates else None

    sectors = []
    for ticker in config.SECTOR_ETF_TICKERS:
        name_en, name_ko = _SECTOR_NAMES[ticker]
        close = prepared[ticker]
        last_date = close.index[-1] if close is not None else None

        if close is None:
            status = "missing"
            calculation = {
                "returns": {period: None for period in PERIODS},
                "baseline_dates": {period: None for period in PERIODS},
            }
        elif last_date < as_of:
            status = "stale"
            calculation = {
                "returns": {period: None for period in PERIODS},
                "baseline_dates": {period: None for period in PERIODS},
            }
        else:
            status = "ok"
            calculation = calculate_period_returns(close, as_of)

        sectors.append(
            {
                "ticker": ticker,
                "sector_en": name_en,
                "sector_ko": name_ko,
                "status": status,
                "last_date": last_date.strftime("%Y-%m-%d") if last_date is not None else None,
                **calculation,
            }
        )

    total = len(config.SECTOR_ETF_TICKERS)
    fresh = sum(sector["status"] == "ok" for sector in sectors)
    stale = sum(sector["status"] == "stale" for sector in sectors)
    missing = sum(sector["status"] == "missing" for sector in sectors)
    period_coverage = {
        period: {
            "available": sum(sector["returns"][period] is not None for sector in sectors),
            "total": total,
        }
        for period in PERIODS
    }
    for coverage in period_coverage.values():
        coverage["ratio"] = round(coverage["available"] / total, 4)

    return {
        "market": "S&P 500",
        "representation": "Select Sector SPDR ETF proxy",
        "as_of": as_of.strftime("%Y-%m-%d") if as_of is not None else None,
        "periods": list(PERIODS),
        "sectors": sectors,
        "coverage": {
            "total": total,
            "fresh": fresh,
            "stale": stale,
            "missing": missing,
            "ratio": round(fresh / total, 4),
            "by_period": period_coverage,
        },
        "source": {
            "price_provider": provider or config.PROVIDER,
            "read_path": "persisted_store_only",
            "instruments": "11 Select Sector SPDR ETFs",
            "tickers": list(config.SECTOR_ETF_TICKERS),
        },
        "basis": {
            "frequency": "daily",
            "price": "adjusted_close",
            "return_type": "dividend_and_split_adjusted_proxy",
            "return_unit": "decimal",
            "common_as_of": True,
            "as_of_policy": "latest stored close across sector ETFs",
            "definitions": {
                "1d": "previous available session close",
                "1w": "last close on or before as_of minus 1 calendar week",
                "1m": "last close on or before as_of minus 1 calendar month",
                "1y": "last close on or before as_of minus 1 calendar year",
            },
        },
    }


def build_sector_snapshot() -> dict:
    """영속 저장소만 읽는 요청 경로 진입점."""
    closes = {ticker: store.load_close(ticker) for ticker in config.SECTOR_ETF_TICKERS}
    return calculate_sector_snapshot(closes)
