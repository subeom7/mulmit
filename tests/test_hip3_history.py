from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app import config, hip3_history
from app.providers.base import DataUnavailable, RateLimited


def _candle(day: dt.date, close: str, symbol: str = "xyz:SP500") -> dict[str, Any]:
    opened = int(dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC).timestamp() * 1000)
    return {
        "t": opened,
        "T": opened + 86_400_000 - 1,
        "s": symbol,
        "i": "1d",
        "o": close,
        "c": close,
        "h": close,
        "l": close,
        "v": "1",
        "n": 1,
    }


class CandleProvider:
    """Offline stand-in: a symbol maps to candles, an exception, or nothing."""

    def __init__(self, series: dict[str, list[dict[str, Any]] | Exception]) -> None:
        self.series = series
        self.calls: list[tuple[str, str]] = []

    def fetch_candles(self, symbol: str, *, interval: str, start: dt.datetime, end: dt.datetime):
        self.calls.append((symbol, interval))
        value = self.series.get(symbol)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise DataUnavailable(f"no candles for {symbol}")
        return {
            "symbol": symbol,
            "interval": interval,
            "fetched_at": "2026-08-21T12:00:00Z",
            "as_of": "2026-08-21T23:59:59Z",
            "candles": value,
            "request": {},
        }


@pytest.fixture
def history_lane(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "HIP3_HISTORY_ENABLED", True)
    hip3_history.clear_cache()
    yield
    hip3_history.clear_cache()


def test_refresh_is_skipped_and_nothing_served_while_history_gate_closed(
    db, hip3_public_display, monkeypatch
):
    monkeypatch.setattr(config, "HIP3_HISTORY_ENABLED", False)
    provider = CandleProvider({"xyz:SP500": [_candle(dt.date(2026, 8, 20), "7600")]})
    assert hip3_history.refresh(force=True, provider=provider)["skipped"] == "disabled"
    assert provider.calls == []
    assert hip3_history.load() is None


def test_refresh_stores_sorted_deduped_daily_closes(history_lane):
    day = dt.date(2026, 8, 19)
    provider = CandleProvider(
        {
            "xyz:SP500": [
                _candle(day + dt.timedelta(days=1), "7700"),
                _candle(day, "7600"),
                _candle(day, "7650"),  # later bar for the same day wins
                {"t": "garbage", "c": "1"},  # malformed rows are skipped, not invented
            ]
        }
    )
    result = hip3_history.refresh(force=True, provider=provider, sleep=lambda _s: None)

    symbols = hip3_history._symbols()
    assert result["attempted"] == len(symbols)
    assert result["updated"] == 1
    assert result["failed"] == len(symbols) - 1
    assert result["observations"] == 2
    assert [symbol for symbol, interval in provider.calls] == symbols
    assert {interval for _symbol, interval in provider.calls} == {"1d"}

    blob = hip3_history.load()
    assert blob["interval"] == "1d"
    assert blob["basis"] == hip3_history.BASIS
    rows = blob["series"]["xyz:SP500"]["observations"]
    assert rows == [
        {"date": "2026-08-19", "value": 7650.0},
        {"date": "2026-08-20", "value": 7700.0},
    ]
    assert hip3_history.observations_for(blob, "xyz:SP500", days=366, limit=1500) == (rows, 2)
    assert hip3_history.observations_for(blob, "xyz:SP500", days=366, limit=1) == ([rows[-1]], 2)
    assert hip3_history.observations_for(blob, "xyz:GOLD", days=366, limit=1500) == ([], 0)
    assert hip3_history.series_as_of(blob, "xyz:SP500") == "2026-08-21T23:59:59Z"


def test_refresh_respects_max_age_unless_forced(history_lane):
    provider = CandleProvider({"xyz:SP500": [_candle(dt.date(2026, 8, 20), "7600")]})
    assert hip3_history.refresh(provider=provider, sleep=lambda _s: None)["updated"] == 1
    calls = len(provider.calls)
    assert hip3_history.refresh(provider=provider, sleep=lambda _s: None)["skipped"] == "fresh"
    assert len(provider.calls) == calls


def test_rate_limit_stops_the_pass_but_keeps_previous_rows(history_lane):
    day = dt.date(2026, 8, 20)
    first = CandleProvider(
        {
            "xyz:SP500": [_candle(day, "7600")],
            "xyz:XYZ100": [_candle(day, "29000", "xyz:XYZ100")],
        }
    )
    hip3_history.refresh(force=True, provider=first, sleep=lambda _s: None)

    second = CandleProvider(
        {
            "xyz:SP500": [_candle(day + dt.timedelta(days=1), "7700")],
            "xyz:XYZ100": RateLimited("slow down"),
        }
    )
    result = hip3_history.refresh(force=True, provider=second, sleep=lambda _s: None)
    assert result["rate_limited"] == 1
    assert result["updated"] == 1

    blob = hip3_history.load()
    assert blob["series"]["xyz:SP500"]["observations"][-1]["value"] == 7700.0
    # Not refreshed this pass, so the earlier rows stay instead of vanishing.
    assert blob["series"]["xyz:XYZ100"]["observations"][-1]["value"] == 29000.0


def test_nothing_is_written_when_every_symbol_fails(history_lane):
    provider = CandleProvider({})
    result = hip3_history.refresh(force=True, provider=provider, sleep=lambda _s: None)
    assert result["updated"] == 0
    assert hip3_history.load() is None


def test_load_closes_with_the_display_gate(history_lane, monkeypatch):
    provider = CandleProvider({"xyz:SP500": [_candle(dt.date(2026, 8, 20), "7600")]})
    hip3_history.refresh(force=True, provider=provider, sleep=lambda _s: None)
    assert hip3_history.load() is not None
    hip3_history.clear_cache()
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", False)
    assert hip3_history.enabled() is False
    assert hip3_history.load() is None
