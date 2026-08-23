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


# --- 새로 추가된 마켓 backfill ------------------------------------------------


def test_a_newly_listed_symbol_is_backfilled_without_waiting_for_the_cycle(history_lane, monkeypatch):
    """자산 목록에 마켓을 더한 날 그 카드의 추이선이 6시간 비어 있으면 안 된다.

    블롭이 아직 신선하면 refresh()는 통째로 건너뛴다. 그런데 새 심볼은 시리즈가
    아예 없어서, 다음 전체 주기까지 화면이 비어 있었다(실측: xyz:SKHX). 신선한
    블롭이어도 **없는 심볼만** 따로 채운다.
    """
    monkeypatch.setattr(hip3_history, "_backfill_attempts", {})
    monkeypatch.setattr(hip3_history, "_symbols", lambda: ["OLD", "NEW"])

    asked: list[str] = []

    class _Client:
        def fetch_candles(self, symbol, *, interval, start, end):
            asked.append(symbol)
            return {
                "fetched_at": "2026-08-23T00:00:00Z",
                "as_of": "2026-08-23",
                "candles": [{"t": 1787000000000, "c": "10.0"}, {"t": 1787086400000, "c": "11.0"}],
            }

    # 첫 패스: 둘 다 없으므로 둘 다 받는다.
    hip3_history.refresh(provider=_Client())
    assert set(asked) == {"OLD", "NEW"}

    # 블롭이 신선한 상태에서 심볼이 하나 더 늘면 그것만 받는다.
    asked.clear()
    monkeypatch.setattr(hip3_history, "_symbols", lambda: ["OLD", "NEW", "LATER"])
    hip3_history.refresh(provider=_Client())
    assert asked == ["LATER"], "새 심볼만 채워야 하는데 전체를 다시 받았다"

    # 이미 있는 것뿐이면 아무것도 부르지 않는다.
    asked.clear()
    outcome = hip3_history.refresh(provider=_Client())
    assert asked == [] and outcome["skipped"] == "fresh"


def test_a_failing_new_symbol_does_not_hammer_the_upstream(history_lane, monkeypatch):
    """계속 실패하는 심볼이 매 틱마다 상류를 두드리면 안 된다.

    한 번 시도했으면 같은 주기가 지나기 전에는 다시 시도하지 않는다.
    """
    monkeypatch.setattr(hip3_history, "_backfill_attempts", {})
    monkeypatch.setattr(hip3_history, "_symbols", lambda: ["GOOD", "BROKEN"])

    calls: list[str] = []

    class _Client:
        def fetch_candles(self, symbol, *, interval, start, end):
            calls.append(symbol)
            if symbol == "BROKEN":
                raise RuntimeError("상장 폐지")
            return {
                "fetched_at": "2026-08-23T00:00:00Z",
                "as_of": "2026-08-23",
                "candles": [{"t": 1787000000000, "c": "10.0"}, {"t": 1787086400000, "c": "11.0"}],
            }

    hip3_history.refresh(provider=_Client())
    assert "BROKEN" in calls
    calls.clear()

    # 바로 다음 틱에서는 다시 부르지 않는다.
    for _ in range(3):
        hip3_history.refresh(provider=_Client())
    assert calls == [], "실패한 심볼을 매 틱마다 다시 불렀다"
