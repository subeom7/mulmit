from __future__ import annotations

import io
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import app.weekend_signals as weekend_signals
from app.main import app
from app.providers.base import DataUnavailable
from app.providers.hyperliquid import HyperliquidProvider
from app.weekend_signals import build_weekend_signals


def _context(mark: str, previous: str, volume: str = "2000000") -> dict:
    return {
        "markPx": mark,
        "oraclePx": mark,
        "prevDayPx": previous,
        "funding": "0.00001",
        "openInterest": "123.4",
        "dayNtlVlm": volume,
        "impactPxs": [mark, str(float(mark) * 1.001)],
    }


def _response(markets: list[tuple[str, dict]]) -> list:
    return [
        {"universe": [{"name": symbol, "maxLeverage": 10} for symbol, _ in markets]},
        [context for _, context in markets],
    ]


def _candle(symbol: str, close: str, close_at: datetime) -> dict:
    close_ms = int(close_at.timestamp() * 1000)
    return {
        "T": close_ms,
        "c": close,
        "h": close,
        "i": "5m",
        "l": close,
        "n": 1,
        "o": close,
        "s": symbol,
        "t": close_ms - 299_999,
        "v": "1",
    }


def test_provider_joins_by_universe_and_uses_process_ttl_cache():
    calls: list[dict] = []
    clock_value = [10.0]
    wall = datetime(2026, 8, 15, 1, 2, 3, tzinfo=UTC)

    def transport(payload, timeout):
        calls.append({"payload": payload, "timeout": timeout})
        return _response(
            [
                ("xyz:KR200", _context("101", "100")),
                ("xyz:SKHX", _context("204", "200")),
            ]
        )

    provider = HyperliquidProvider(
        transport=transport,
        timeout=3,
        retries=0,
        ttl=20,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wall,
    )
    first = provider.fetch_dex("xyz")
    clock_value[0] = 25.0
    second = provider.fetch_dex("xyz")

    assert len(calls) == 1
    assert calls[0]["payload"] == {"type": "metaAndAssetCtxs", "dex": "xyz"}
    assert calls[0]["timeout"] <= 3.0
    assert [market["symbol"] for market in first["markets"]] == [
        "xyz:KR200",
        "xyz:SKHX",
    ]
    assert first["markets"][1]["context"]["markPx"] == "204"
    assert first["fetched_at"] == "2026-08-15T01:02:03Z"
    assert first["as_of"] == first["fetched_at"]
    assert first["cached"] is False
    assert first["age_seconds"] == 0.0
    assert second["cached"] is True
    assert second["age_seconds"] == 15.0


def test_provider_retries_429_then_succeeds_with_bounded_delay():
    attempts = 0
    sleeps: list[float] = []

    def transport(_payload, _timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.HTTPError(
                "https://api.hyperliquid.xyz/info",
                429,
                "rate limited",
                {"Retry-After": "99"},
                io.BytesIO(),
            )
        return _response([("mkts:USTECH", _context("202", "200"))])

    provider = HyperliquidProvider(
        transport=transport,
        retries=1,
        max_request_seconds=3,
        sleep=sleeps.append,
    )
    snapshot = provider.fetch_dex("mkts")

    assert attempts == 2
    assert sleeps == [2.0]
    assert snapshot["markets"][0]["symbol"] == "mkts:USTECH"


def test_provider_tolerates_context_array_shorter_than_universe():
    provider = HyperliquidProvider(
        transport=lambda _payload, _timeout: [
            {"universe": [{"name": "xyz:SKHX"}, {"name": "xyz:KR200"}]},
            [_context("101", "100")],
        ],
        retries=0,
    )

    snapshot = provider.fetch_dex("xyz")

    assert len(snapshot["markets"]) == 2
    assert snapshot["markets"][1]["context"] == {}


def test_provider_stale_fallback_preserves_observation_time_and_reports_age():
    clock_value = [10.0]
    should_fail = [False]
    wall = datetime(2026, 8, 15, 2, 0, tzinfo=UTC)

    def transport(_payload, _timeout):
        if should_fail[0]:
            raise urllib.error.URLError("temporary outage")
        return _response([("xyz:KR200", _context("101", "100"))])

    provider = HyperliquidProvider(
        transport=transport,
        retries=0,
        ttl=1,
        stale_ttl=30,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wall,
    )
    original = provider.fetch_dex("xyz")
    clock_value[0] = 12.0
    should_fail[0] = True

    recovered = provider.fetch_dex("xyz")

    assert recovered["cached"] is True
    assert recovered["stale"] is True
    assert recovered["error"] == "DataUnavailable"
    assert recovered["fetched_at"] == original["fetched_at"]
    assert recovered["as_of"] == original["as_of"]
    assert recovered["age_seconds"] == 2.0
    assert recovered["markets"][0]["symbol"] == "xyz:KR200"


def test_provider_failure_cooldown_reuses_stale_without_resetting_its_age():
    calls = 0
    clock_value = [10.0]
    should_fail = [False]

    def transport(_payload, _timeout):
        nonlocal calls
        calls += 1
        if should_fail[0]:
            raise urllib.error.URLError("temporary outage")
        return _response([("xyz:KR200", _context("101", "100"))])

    provider = HyperliquidProvider(
        transport=transport,
        retries=0,
        ttl=5,
        stale_ttl=30,
        clock=lambda: clock_value[0],
    )
    provider.fetch_dex("xyz")
    clock_value[0] = 16.0
    should_fail[0] = True

    first_stale = provider.fetch_dex("xyz")
    clock_value[0] = 18.0
    cooldown_stale = provider.fetch_dex("xyz")

    assert calls == 2
    assert first_stale["stale"] is True
    assert first_stale["age_seconds"] == 6.0
    assert cooldown_stale["stale"] is True
    assert cooldown_stale["error"] == "DataUnavailable"
    assert cooldown_stale["age_seconds"] == 8.0

    provider.clear_cache()
    with pytest.raises(DataUnavailable):
        provider.fetch_dex("xyz")
    assert calls == 3


def test_provider_failure_cooldown_suppresses_repeated_cold_requests():
    calls = 0
    clock_value = [10.0]

    def transport(_payload, _timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.URLError("temporary outage")

    provider = HyperliquidProvider(
        transport=transport,
        retries=0,
        ttl=5,
        clock=lambda: clock_value[0],
    )

    with pytest.raises(DataUnavailable):
        provider.fetch_dex("xyz")
    clock_value[0] = 14.9
    with pytest.raises(DataUnavailable, match="cooling down"):
        provider.fetch_dex("xyz")
    assert calls == 1

    clock_value[0] = 15.1
    with pytest.raises(DataUnavailable):
        provider.fetch_dex("xyz")
    assert calls == 2


def test_provider_cold_cache_single_flight_coalesces_concurrent_requests():
    started = threading.Event()
    release = threading.Event()
    call_count = 0
    count_lock = threading.Lock()

    def transport(_payload, _timeout):
        nonlocal call_count
        with count_lock:
            call_count += 1
        started.set()
        assert release.wait(timeout=2)
        return _response([("xyz:KR200", _context("101", "100"))])

    provider = HyperliquidProvider(transport=transport, retries=0, ttl=20)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(provider.fetch_dex, "xyz") for _ in range(4)]
        assert started.wait(timeout=1)
        release.set()
        results = [future.result(timeout=2) for future in futures]

    assert call_count == 1
    assert sum(not item["cached"] for item in results) == 1
    assert all(item["markets"][0]["symbol"] == "xyz:KR200" for item in results)


def test_session_baseline_uses_last_official_5m_close_before_boundary():
    boundary = datetime(2026, 8, 14, 21, 0, tzinfo=UTC)
    payloads: list[dict] = []

    def transport(payload, _timeout):
        payloads.append(payload)
        return [
            _candle("xyz:XYZ100", "99", boundary - timedelta(minutes=10)),
            _candle("xyz:XYZ100", "100", boundary - timedelta(milliseconds=1)),
        ]

    provider = HyperliquidProvider(transport=transport, retries=0)
    baseline = provider.fetch_session_baseline("xyz:XYZ100", boundary)

    assert baseline is not None
    assert baseline["price"] == 100.0
    assert baseline["boundary_at"] == "2026-08-14T21:00:00Z"
    assert baseline["distance_seconds"] == 0.0
    assert baseline["proximity_quality"] == "high"
    assert payloads[0]["type"] == "candleSnapshot"
    assert payloads[0]["req"]["coin"] == "xyz:XYZ100"
    assert payloads[0]["req"]["interval"] == "5m"
    assert payloads[0]["req"]["endTime"] == int(boundary.timestamp() * 1000) - 1


class FixtureProvider:
    def __init__(
        self,
        by_dex: dict[str, list[tuple[str, dict]]],
        failing: set[str] | None = None,
        baselines: dict[str, float | None] | None = None,
        delisted: set[str] | None = None,
    ):
        self.by_dex = by_dex
        self.failing = failing or set()
        self.baselines = baselines or {}
        self.delisted = delisted or set()
        self.baseline_calls: list[str] = []

    def fetch_dex(self, dex: str) -> dict:
        if dex in self.failing:
            raise DataUnavailable("fixture unavailable")
        markets = [
            {
                "symbol": symbol,
                "dex": dex,
                "metadata": {
                    "name": symbol,
                    **({"isDelisted": True} if symbol in self.delisted else {}),
                },
                "context": ctx,
            }
            for symbol, ctx in self.by_dex.get(dex, [])
        ]
        return {
            "dex": dex,
            "fetched_at": "2026-08-15T03:00:00Z",
            "as_of": "2026-08-15T03:00:00Z",
            "cached": False,
            "stale": False,
            "age_seconds": 0.0,
            "markets": markets,
        }

    def fetch_session_baseline(self, symbol: str, boundary: datetime, *, interval: str):
        self.baseline_calls.append(symbol)
        value = self.baselines.get(symbol, 100.0)
        if value is None:
            return None
        return {
            "price": value,
            "interval": interval,
            "boundary_at": boundary.isoformat().replace("+00:00", "Z"),
            "candle_open_at": (boundary - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "candle_close_at": (boundary - timedelta(milliseconds=1))
            .isoformat()
            .replace("+00:00", "Z"),
            "distance_seconds": 0.0,
            "proximity_quality": "high",
            "fetched_at": "2026-08-15T03:00:00Z",
            "as_of": (boundary - timedelta(milliseconds=1)).isoformat().replace("+00:00", "Z"),
            "cached": False,
            "stale": False,
            "age_seconds": 0.0,
        }


class ParallelDexProvider(FixtureProvider):
    def __init__(self):
        super().__init__(
            {
                "xyz": [("xyz:XYZ100", _context("101", "100"))],
                "mkts": [("mkts:USTECH", _context("101", "100"))],
            }
        )
        self.barrier = threading.Barrier(2)

    def fetch_dex(self, dex: str) -> dict:
        self.barrier.wait(timeout=1)
        return super().fetch_dex(dex)


def test_build_fetches_two_dex_contexts_in_parallel():
    result = build_weekend_signals(
        ParallelDexProvider(), now=datetime(2026, 8, 15, 3, 0, tzinfo=UTC)
    )

    assert result["source"]["errors"] == {}
    # Both DEX contexts are fetched concurrently, but only XYZ100 has the
    # documented internal-session schedule used by the weekend composite.
    assert result["composites"]["nasdaq_weekend"]["available_components"] == 1
    us_tech = next(signal for signal in result["signals"] if signal["symbol"] == "mkts:USTECH")
    assert us_tech["change_24h_percent"] is not None
    assert us_tech["session_change_percent"] is None


@pytest.mark.parametrize(
    ("moment", "korea_active", "market_session"),
    [
        (
            datetime(2026, 8, 14, 19, 59, tzinfo=ZoneInfo("Asia/Seoul")),
            False,
            "external_reference",
        ),
        (
            datetime(2026, 8, 14, 20, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            True,
            "korea_internal_price_discovery",
        ),
        (
            datetime(2026, 8, 17, 7, 59, tzinfo=ZoneInfo("Asia/Seoul")),
            True,
            "korea_internal_price_discovery",
        ),
        (
            datetime(2026, 8, 17, 8, 0, tzinfo=ZoneInfo("Asia/Seoul")),
            False,
            "external_reference",
        ),
    ],
)
def test_korea_internal_session_boundaries(
    moment: datetime,
    korea_active: bool,
    market_session: str,
):
    result = build_weekend_signals(FixtureProvider({"xyz": [], "mkts": []}), now=moment)

    session = result["composites"]["korea_weekend"]["session"]
    assert session["active"] is korea_active
    assert session["timezone"] == "Asia/Seoul"
    assert result["calendar_day_type"] == "weekday"
    assert result["market_session"] == market_session
    if korea_active:
        assert session["local_start"].endswith("20:00:00+09:00")
        assert session["local_end"].endswith("08:00:00+09:00")


@pytest.mark.parametrize(
    ("moment", "active", "window", "calendar_day_type", "market_session"),
    [
        (
            datetime(2026, 8, 14, 16, 59, tzinfo=ZoneInfo("America/New_York")),
            False,
            "external_reference",
            "weekend",
            "korea_internal_price_discovery",
        ),
        (
            datetime(2026, 8, 14, 17, 0, tzinfo=ZoneInfo("America/New_York")),
            True,
            "weekend_internal",
            "weekend",
            "korea_and_nasdaq_internal_price_discovery",
        ),
        (
            datetime(2026, 8, 16, 17, 59, tzinfo=ZoneInfo("America/New_York")),
            True,
            "weekend_internal",
            "weekday",
            "korea_and_nasdaq_internal_price_discovery",
        ),
        (
            datetime(2026, 8, 16, 18, 0, tzinfo=ZoneInfo("America/New_York")),
            False,
            "external_reference",
            "weekday",
            "korea_internal_price_discovery",
        ),
        (
            datetime(2026, 8, 17, 17, 30, tzinfo=ZoneInfo("America/New_York")),
            True,
            "daily_internal_gap",
            "weekday",
            "nasdaq_internal_price_discovery",
        ),
    ],
)
def test_nasdaq_internal_session_boundaries(
    moment: datetime,
    active: bool,
    window: str,
    calendar_day_type: str,
    market_session: str,
):
    result = build_weekend_signals(FixtureProvider({"xyz": [], "mkts": []}), now=moment)

    session = result["composites"]["nasdaq_weekend"]["session"]
    assert session["active"] is active
    assert session["window"] == window
    assert session["timezone"] == "America/New_York"
    assert result["calendar_day_type"] == calendar_day_type
    assert result["market_session"] == market_session


def test_sessions_expose_next_internal_start_when_inactive():
    provider = FixtureProvider({"xyz": [], "mkts": []})
    # Friday 20:18 KST = 07:18 ET: Korea is inside its window, Nasdaq is not yet.
    moment = datetime(2026, 8, 21, 20, 18, tzinfo=ZoneInfo("Asia/Seoul"))
    result = build_weekend_signals(provider, now=moment)
    korea = result["composites"]["korea_weekend"]["session"]
    nasdaq = result["composites"]["nasdaq_weekend"]["session"]
    assert korea["active"] is True
    assert korea["next_start_at"] is None
    assert nasdaq["active"] is False
    assert result["composites"]["nasdaq_weekend"]["status"] == "outside_internal_session"
    assert nasdaq["next_local_start"] == "2026-08-21T17:00:00-04:00"
    assert nasdaq["next_start_at"] == "2026-08-21T21:00:00Z"
    assert nasdaq["next_window"] == "weekend_internal"

    # Monday 08:00 KST: the Korea window just closed; the next one is Friday 20:00 KST.
    monday = datetime(2026, 8, 24, 8, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    korea = build_weekend_signals(provider, now=monday)["composites"]["korea_weekend"]["session"]
    assert korea["active"] is False
    assert korea["next_local_start"] == "2026-08-28T20:00:00+09:00"

    # Sunday 18:00 ET: weekend window closed; next internal window is Monday's daily gap.
    sunday = datetime(2026, 8, 23, 18, 0, tzinfo=ZoneInfo("America/New_York"))
    nasdaq = build_weekend_signals(provider, now=sunday)["composites"]["nasdaq_weekend"]["session"]
    assert nasdaq["active"] is False
    assert nasdaq["next_local_start"] == "2026-08-24T17:00:00-04:00"
    assert nasdaq["next_window"] == "daily_internal_gap"


def test_weekend_contract_separates_rolling_24h_and_session_change():
    provider = FixtureProvider(
        {
            "xyz": [
                ("xyz:KR200", _context("102", "100")),
                ("xyz:SMSN", _context("103", "100")),
                ("xyz:EWY", _context("104", "100", "500000")),
                # Daily-3x KORU remains visible only as a rolling-24h auxiliary.
                ("xyz:KORU", _context("112", "100", "500000")),
                ("xyz:XYZ100", _context("103", "101")),
            ],
            "mkts": [("mkts:USTECH", _context("102", "101"))],
        },
        baselines={"xyz:KR200": 101.0},
    )

    result = build_weekend_signals(provider, now=datetime(2026, 8, 15, 3, 0, tzinfo=UTC))

    assert set(result) == {
        "generated_at",
        "calendar_day_type",
        "market_session",
        "signals",
        "composites",
        "disclaimer",
        "source",
    }
    kr200 = next(signal for signal in result["signals"] if signal["id"] == "kospi_200")
    assert "previous" not in kr200
    assert "change_percent" not in kr200
    assert kr200["previous_24h"] == 100.0
    assert kr200["change_24h_percent"] == pytest.approx(2.0)
    assert kr200["session_baseline"]["price"] == 101.0
    assert kr200["session_change_percent"] == pytest.approx((102 / 101 - 1) * 100)
    assert kr200["funding_hourly_rate"] == 0.00001
    assert kr200["open_interest_base_units"] == 123.4
    assert kr200["units"]["funding_hourly_rate"].startswith("raw decimal")
    assert kr200["fetched_at"] == "2026-08-15T03:00:00Z"
    assert kr200["stale"] is False

    korea = result["composites"]["korea_weekend"]
    assert {item["id"] for item in korea["components"]} == {
        "kospi_200",
        "samsung_electronics",
    }
    assert korea["expected_components"] == 4
    assert "koru_adjustment" not in korea["methodology"]
    assert korea["methodology"]["component_scope"].startswith("documented direct")
    for signal_id in ("korea_ewy", "korea_koru"):
        auxiliary = next(item for item in result["signals"] if item["id"] == signal_id)
        assert auxiliary["change_24h_percent"] is not None
        assert auxiliary["session_change_percent"] is None
        assert auxiliary["session_baseline"] is None
        assert auxiliary["session_baseline_status"] == "not_applicable_24h_auxiliary"
        assert auxiliary["session_role"] == "auxiliary_24h_only"
    assert "xyz:EWY" not in provider.baseline_calls
    assert "xyz:KORU" not in provider.baseline_calls
    assert "confidence" not in korea
    assert korea["evidence_quality"] in {"low", "medium", "high"}
    assert korea["session"]["active"] is True
    assert result["calendar_day_type"] == "weekend"
    assert result["market_session"] == "korea_and_nasdaq_internal_price_discovery"
    assert "not spot prices or Monday-open forecasts" in result["disclaimer"]["en"]
    assert "rolling-24h auxiliaries" in result["disclaimer"]["en"]
    assert "5m candle close" in result["source"]["session_change_basis"]
    assert result["source"]["session_baseline_scope"]["korea_direct_contracts"] == [
        "xyz:KR200",
        "xyz:SMSN",
        "xyz:SKHX",
        "xyz:HYUNDAI",
    ]


def test_default_weekend_provider_caps_dex_and_baseline_calls_to_once_per_five_minutes(
    monkeypatch,
):
    calls: list[dict] = []
    clock_value = [10.0]
    wall = datetime(2026, 8, 15, 3, 0, tzinfo=UTC)

    def transport(payload, _timeout):
        calls.append(payload)
        if payload["type"] == "metaAndAssetCtxs":
            if payload["dex"] == "xyz":
                return _response(
                    [
                        ("xyz:KR200", _context("102", "100")),
                        ("xyz:EWY", _context("103", "100")),
                        ("xyz:KORU", _context("109", "100")),
                        ("xyz:XYZ100", _context("202", "200")),
                    ]
                )
            return _response([("mkts:USTECH", _context("201", "200"))])

        request = payload["req"]
        close_at = datetime.fromtimestamp(request["endTime"] / 1000, tz=UTC)
        return [_candle(request["coin"], "100", close_at)]

    provider = HyperliquidProvider(
        transport=transport,
        timeout=2,
        retries=0,
        max_request_seconds=2.5,
        ttl=300,
        stale_ttl=1800,
        clock=lambda: clock_value[0],
        wall_clock=lambda: wall,
    )
    monkeypatch.setattr(weekend_signals, "_DEFAULT_PROVIDER", provider)

    first = weekend_signals.build_weekend_signals(now=wall)
    clock_value[0] = 309.0
    second = weekend_signals.build_weekend_signals(now=wall)

    assert len(calls) == 4
    assert {
        item["dex"] for item in calls if item["type"] == "metaAndAssetCtxs"
    } == {"xyz", "mkts"}
    assert {
        item["req"]["coin"] for item in calls if item["type"] == "candleSnapshot"
    } == {"xyz:KR200", "xyz:XYZ100"}
    assert set(second["source"]["cached_dexes"]) == {"xyz", "mkts"}
    second_kr200 = next(item for item in second["signals"] if item["id"] == "kospi_200")
    assert second_kr200["session_baseline"]["cached"] is True
    budget = first["source"]["upstream_cache"]
    assert budget["ttl_seconds"] == 300
    assert budget["stale_if_error_seconds"] == 1800
    assert budget["maximum_candle_items"] == 288
    assert budget["maximum_candle_weight_each"] == 24
    assert budget["maximum_burst_weight"] == 160
    assert budget["steady_state_weight_per_minute_per_process"] == 32
    assert budget["official_ip_limit_weight_per_minute"] == 1200

    clock_value[0] = 311.0
    weekend_signals.build_weekend_signals(now=wall)
    assert len(calls) == 8


def test_missing_session_baseline_is_null_not_rolling_24h_substitute():
    provider = FixtureProvider(
        {"xyz": [("xyz:SKHX", _context("105", "100", "50000"))], "mkts": []},
        baselines={"xyz:SKHX": None},
    )

    result = build_weekend_signals(provider, now=datetime(2026, 8, 15, 3, 0, tzinfo=UTC))
    signal = next(item for item in result["signals"] if item["id"] == "sk_hynix")

    assert signal["change_24h_percent"] == 5.0
    assert signal["session_baseline"] is None
    assert signal["session_change_percent"] is None
    assert signal["session_baseline_status"] == "unavailable"
    assert result["source"]["baseline_errors"]["xyz:SKHX"] == "no_pre_session_candle"


def test_delisted_weekend_market_is_missing_and_never_used_as_a_baseline():
    provider = FixtureProvider(
        {"xyz": [("xyz:SKHX", _context("105", "100"))], "mkts": []},
        delisted={"xyz:SKHX"},
    )

    result = build_weekend_signals(provider, now=datetime(2026, 8, 15, 3, 0, tzinfo=UTC))
    signal = next(item for item in result["signals"] if item["id"] == "sk_hynix")

    assert signal["mark"] is None
    assert signal["change_24h_percent"] is None
    assert signal["session_baseline"] is None
    assert signal["session_baseline_status"] == "unavailable"
    assert signal["liquidity_status"] == "unavailable"
    assert provider.baseline_calls == []
    assert result["composites"]["korea_weekend"]["status"] == "unavailable"


def test_missing_markets_and_one_failed_dex_return_partial_result():
    provider = FixtureProvider(
        {"xyz": [("xyz:SKHX", _context("105", "100", "50000"))]},
        failing={"mkts"},
    )

    result = build_weekend_signals(provider, now=datetime(2026, 8, 15, 3, 0, tzinfo=UTC))

    assert [signal["symbol"] for signal in result["signals"]] == [
        "xyz:SKHX",
        "xyz:SMSN",
        "xyz:KR200",
        "xyz:HYUNDAI",
        "xyz:EWY",
        "xyz:KORU",
        "xyz:XYZ100",
        "mkts:USTECH",
    ]
    unavailable = next(signal for signal in result["signals"] if signal["symbol"] == "xyz:KR200")
    assert unavailable["mark"] is None
    assert unavailable["change_24h_percent"] is None
    assert unavailable["session_change_percent"] is None
    assert unavailable["liquidity_status"] == "unavailable"
    assert result["source"]["errors"] == {"mkts": "unavailable"}
    assert result["composites"]["korea_weekend"]["status"] == "limited"
    assert result["composites"]["nasdaq_weekend"]["status"] == "unavailable"


def test_samsung_uses_documented_smsn_market_and_stays_null_when_missing():
    missing = build_weekend_signals(FixtureProvider({"xyz": [], "mkts": []}))
    present = build_weekend_signals(
        FixtureProvider(
            {
                "xyz": [("xyz:SMSN", _context("193", "190", "3000000"))],
                "mkts": [],
            }
        ),
        now=datetime(2026, 8, 15, 3, 0, tzinfo=UTC),
    )

    missing_samsung = next(
        signal for signal in missing["signals"] if signal["id"] == "samsung_electronics"
    )
    samsung = next(signal for signal in present["signals"] if signal["id"] == "samsung_electronics")
    assert missing_samsung["symbol"] == "xyz:SMSN"
    assert missing_samsung["mark"] is None
    assert missing_samsung["liquidity_status"] == "unavailable"
    assert samsung["symbol"] == "xyz:SMSN"
    assert samsung["mark"] == 193.0
    assert samsung["liquidity_status"] == "high"


def test_weekend_endpoint_exposes_cache_and_source_headers(monkeypatch, hip3_public_display):
    payload = {
        "generated_at": "2026-08-16T00:00:00Z",
        "calendar_day_type": "weekend",
        "market_session": "korea_and_nasdaq_internal_price_discovery",
        "signals": [],
        "composites": {},
        "disclaimer": {"ko": "참고용", "en": "Reference only"},
        "source": {"provider": "Hyperliquid HIP-3"},
    }
    monkeypatch.setattr("app.main.build_weekend_signals", lambda: payload)

    response = TestClient(app).get("/api/market/weekend")

    assert response.status_code == 200
    assert response.json() == payload
    assert response.headers["x-data-source"] == "Hyperliquid HIP-3"
    assert "stale-while-revalidate" in response.headers["cache-control"]
