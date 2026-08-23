"""Read-only Hyperliquid HIP-3 market and candle client.

The public ``info`` endpoint needs no API key.  This module deliberately keeps
Hyperliquid's positional response schema at the provider edge, bounds retry
latency, and coalesces concurrent cold-cache requests inside one process.
"""

from __future__ import annotations

import copy
import itertools
import json
import math
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .base import DataUnavailable, RateLimited

API_URL = "https://api.hyperliquid.xyz/info"
REQUEST_TYPE = "metaAndAssetCtxs"
CANDLE_REQUEST_TYPE = "candleSnapshot"
PREDICTED_FUNDING_REQUEST_TYPE = "predictedFundings"
# Hyperliquid's own perpetual venue. The API addresses it with an empty dex
# name; this project spells it out so a blank value is never mistaken for one.
MAIN_DEX = "main"
DEFAULT_TIMEOUT = 3.0
DEFAULT_RETRIES = 1
DEFAULT_MAX_REQUEST_SECONDS = 7.0
DEFAULT_TTL = 20.0
DEFAULT_STALE_TTL = 300.0
CANDLE_INTERVALS = frozenset(
    {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "3d", "1w", "1M"}
)

HYPERLIQUID_INFO_DOCS = (
    "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint"
)
HYPERLIQUID_PERP_DOCS = (
    "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/" "info-endpoint/perpetuals"
)
HYPERLIQUID_RATE_LIMIT_DOCS = (
    "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/"
    "rate-limits-and-user-limits"
)

Transport = Callable[[dict[str, Any], float], Any]
WallClock = Callable[[], datetime]
CacheKey = tuple[str, ...]
CacheEntry = tuple[float, dict[str, Any]]
FailureEntry = tuple[float, str]


def _utc_iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _millis_iso(value: Any) -> str | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    try:
        return _utc_iso(datetime.fromtimestamp(millis / 1000.0, tz=UTC))
    except (OverflowError, OSError, ValueError):
        return None


def _finite_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _default_transport(payload: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "mulmit-market-monitor/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    raw = exc.headers.get("Retry-After") if exc.headers is not None else None
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), 2.0))
    except (TypeError, ValueError):
        return None


def _join_market_contexts(data: Any, dex: str) -> list[dict[str, Any]]:
    """Validate and join ``universe`` with its same-index asset contexts."""
    if not isinstance(data, list) or len(data) != 2:
        raise DataUnavailable(f"Hyperliquid returned an invalid {dex!r} response envelope")

    metadata, contexts = data
    universe = metadata.get("universe") if isinstance(metadata, dict) else None
    if not isinstance(universe, list) or not isinstance(contexts, list):
        raise DataUnavailable(f"Hyperliquid returned an invalid {dex!r} market schema")

    markets: list[dict[str, Any]] = []
    for index, raw_meta in enumerate(universe):
        if not isinstance(raw_meta, dict):
            continue
        symbol = raw_meta.get("name")
        if not isinstance(symbol, str) or not symbol.strip():
            continue
        raw_context = contexts[index] if index < len(contexts) else {}
        context = raw_context if isinstance(raw_context, dict) else {}
        markets.append(
            {
                "symbol": symbol.strip(),
                "dex": dex,
                "metadata": dict(raw_meta),
                "context": dict(context),
            }
        )
    return markets


def _join_predicted_fundings(data: Any) -> dict[str, list[dict[str, Any]]]:
    """Validate ``predictedFundings``: ``[[coin, [[venue, {...}], ...]], ...]``.

    Venues without a listing arrive as ``[venue, null]`` and are skipped; a
    malformed row is dropped rather than guessed at.
    """
    if not isinstance(data, list):
        raise DataUnavailable("Hyperliquid returned an invalid predicted-funding envelope")
    coins: dict[str, list[dict[str, Any]]] = {}
    for entry in data:
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        coin, venues = entry
        if not isinstance(coin, str) or not coin.strip() or not isinstance(venues, list):
            continue
        rows: list[dict[str, Any]] = []
        for venue_entry in venues:
            if not isinstance(venue_entry, list) or len(venue_entry) != 2:
                continue
            venue, detail = venue_entry
            if not isinstance(venue, str) or not isinstance(detail, dict):
                continue
            rate = _finite_number(detail.get("fundingRate"))
            if rate is None:
                continue
            interval = _finite_number(detail.get("fundingIntervalHours"))
            rows.append(
                {
                    "venue": venue,
                    "funding_rate": rate,
                    "interval_hours": interval,
                    "next_funding_at": _millis_iso(detail.get("nextFundingTime")),
                }
            )
        coins[coin.strip()] = rows
    return coins


class HyperliquidProvider:
    """Fetch HIP-3 contexts/candles with single-flight TTL and stale fallback."""

    name = "hyperliquid"
    _cache: dict[CacheKey, CacheEntry] = {}
    # 주입된 transport마다 붙는 일련번호. id(self)를 쓰면 안 되는 이유는 아래.
    _namespace_seq = itertools.count(1)
    _failures: dict[CacheKey, FailureEntry] = {}
    _inflight: dict[CacheKey, threading.Event] = {}
    _cache_lock = threading.Lock()

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        max_request_seconds: float = DEFAULT_MAX_REQUEST_SECONDS,
        ttl: float = DEFAULT_TTL,
        stale_ttl: float = DEFAULT_STALE_TTL,
        transport: Transport | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: WallClock | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self.max_request_seconds = max(self.timeout, float(max_request_seconds))
        self.ttl = max(0.0, float(ttl))
        self.stale_ttl = max(self.ttl, float(stale_ttl))
        self._transport = transport or _default_transport
        self._clock = clock
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        # 기본 클라이언트는 캐시를 함께 쓰고, 주입된 transport는 서로 격리한다.
        #
        # 예전에는 이름을 `id(self)`로 지었다. CPython의 id()는 메모리 주소라
        # **객체가 사라지면 그 주소가 곧바로 재사용된다.** 캐시는 클래스에
        # 붙어 있어 인스턴스가 사라져도 남으므로, 앞선 provider가 수거된 자리에
        # 새 provider가 앉으면 죽은 인스턴스의 캐시를 그대로 물려받았다.
        # 드문 일이 아니다 — 만들고 버리기를 200번 반복하면 198번 겹친다(실측).
        # 격리를 약속해 놓고 지키지 못하고 있었던 셈이다.
        #
        # 증상은 조용하다. CI에서 test_hyperliquid의 5분 상한 테스트가 첫 패스에
        # xyz dex를 부르지 않고 지나가 호출 수가 4가 아니라 2로 나왔다.
        # 재사용되지 않는 일련번호를 쓴다.
        if transport is None:
            self._cache_namespace = "default"
        else:
            with self._cache_lock:
                self._cache_namespace = f"transport:{next(self._namespace_seq)}"

    @classmethod
    def clear_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache.clear()
            cls._failures.clear()

    def _cache_key(self, *parts: str) -> CacheKey:
        return (self._cache_namespace, *parts)

    def _decorate(
        self,
        entry: CacheEntry,
        *,
        cached: bool,
        stale: bool,
        error: str | None = None,
    ) -> dict[str, Any]:
        stored_at, raw_snapshot = entry
        snapshot = copy.deepcopy(raw_snapshot)
        snapshot["cached"] = cached
        snapshot["stale"] = stale
        snapshot["age_seconds"] = round(max(0.0, self._clock() - stored_at), 3)
        if error is not None:
            snapshot["error"] = error
        else:
            snapshot.pop("error", None)
        return snapshot

    def _cached_fetch(
        self,
        key: CacheKey,
        loader: Callable[[], dict[str, Any]],
        *,
        label: str,
    ) -> dict[str, Any]:
        """Load a snapshot once per key while concurrent callers wait for its result."""
        with self._cache_lock:
            now = self._clock()
            existing = self._cache.get(key)
            if existing is not None and now - existing[0] <= self.ttl:
                return self._decorate(existing, cached=True, stale=False)
            failure = self._failures.get(key)
            if failure is not None and now < failure[0]:
                error_name = failure[1]
                if existing is not None and now - existing[0] <= self.stale_ttl:
                    return self._decorate(
                        existing,
                        cached=True,
                        stale=True,
                        error=error_name,
                    )
                if error_name == "RateLimited":
                    raise RateLimited(
                        f"Hyperliquid {label} retry is cooling down after a rate limit"
                    )
                raise DataUnavailable(
                    f"Hyperliquid {label} retry is cooling down after an upstream failure"
                )
            if failure is not None:
                self._failures.pop(key, None)
            event = self._inflight.get(key)
            owner = event is None
            if owner:
                event = threading.Event()
                self._inflight[key] = event

        assert event is not None
        if not owner:
            if not event.wait(timeout=self.max_request_seconds + 0.5):
                raise DataUnavailable(
                    f"Timed out waiting for a coalesced Hyperliquid {label} request"
                )
            with self._cache_lock:
                completed = self._cache.get(key)
                failure = self._failures.get(key)
            if completed is None:
                if failure is not None and failure[1] == "RateLimited":
                    raise RateLimited(f"Coalesced Hyperliquid {label} request was rate limited")
                raise DataUnavailable(f"Coalesced Hyperliquid {label} request failed")
            age = self._clock() - completed[0]
            is_stale = age > self.ttl
            return self._decorate(
                completed,
                cached=True,
                stale=is_stale,
                error=failure[1] if is_stale and failure is not None else None,
            )

        try:
            snapshot = loader()
            entry = (self._clock(), copy.deepcopy(snapshot))
            with self._cache_lock:
                self._cache[key] = entry
                self._failures.pop(key, None)
            return self._decorate(entry, cached=False, stale=False)
        except (DataUnavailable, RateLimited) as exc:
            with self._cache_lock:
                fallback = self._cache.get(key)
                failed_at = self._clock()
                # A stale fallback must not turn an outage into one upstream call
                # per HTTP request. Keep the original observation timestamp and
                # suppress retries for at least this client's normal TTL.
                self._failures[key] = (
                    failed_at + max(self.ttl, 1.0),
                    type(exc).__name__,
                )
            if fallback is not None and failed_at - fallback[0] <= self.stale_ttl:
                return self._decorate(
                    fallback,
                    cached=True,
                    stale=True,
                    error=type(exc).__name__,
                )
            raise
        finally:
            with self._cache_lock:
                completed_event = self._inflight.pop(key, None)
                if completed_event is not None:
                    completed_event.set()

    def _request(self, payload: dict[str, Any], label: str) -> Any:
        deadline = time.monotonic() + self.max_request_seconds
        last_error: BaseException | None = None

        for attempt in range(self.retries + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                return self._transport(payload, min(self.timeout, remaining))
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code != 429 and not 500 <= exc.code < 600:
                    raise DataUnavailable(
                        f"Hyperliquid rejected the {label} request with HTTP {exc.code}"
                    ) from exc
                delay = _retry_after_seconds(exc)
            except RateLimited as exc:
                last_error = exc
                delay = None
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
                delay = None
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable(
                    f"Hyperliquid returned an unreadable {label} response"
                ) from exc

            if attempt >= self.retries:
                break
            retry_delay = delay if delay is not None else min(0.25 * (2**attempt), 1.0)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._sleep(min(retry_delay, remaining))

        if isinstance(last_error, RateLimited) or (
            isinstance(last_error, urllib.error.HTTPError) and last_error.code == 429
        ):
            raise RateLimited("Hyperliquid rate limit reached; try again shortly") from last_error
        raise DataUnavailable(f"Hyperliquid {label} data is unavailable") from last_error

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        """Return one DEX context snapshot, with a recent stale fallback on failure.

        Hyperliquid names its own venue with an empty string, while HIP-3
        deployments have real names. An empty argument would silently mean
        "whatever the API defaults to", so callers spell the main venue as
        :data:`MAIN_DEX` and the translation happens here.
        """
        normalized_dex = dex.strip().lower()
        if not normalized_dex or not normalized_dex.replace("-", "").isalnum():
            raise ValueError("dex must be a non-empty alphanumeric DEX name")
        request_dex = "" if normalized_dex == MAIN_DEX else normalized_dex

        def load() -> dict[str, Any]:
            raw = self._request(
                {"type": REQUEST_TYPE, "dex": request_dex},
                f"{normalized_dex!r} market",
            )
            fetched_at = _utc_iso(self._wall_clock())
            return {
                "dex": normalized_dex,
                "fetched_at": fetched_at,
                "as_of": fetched_at,
                "markets": _join_market_contexts(raw, normalized_dex),
            }

        return self._cached_fetch(
            self._cache_key("dex", normalized_dex),
            load,
            label=f"{normalized_dex!r} market",
        )

    def fetch_predicted_fundings(self) -> dict[str, Any]:
        """Venue-by-venue predicted funding for every perp, as Hyperliquid publishes it.

        The Binance/Bybit rows are Hyperliquid's own published predictions; this
        client never queries those venues.
        """

        def load() -> dict[str, Any]:
            raw = self._request({"type": PREDICTED_FUNDING_REQUEST_TYPE}, "predicted funding")
            fetched_at = _utc_iso(self._wall_clock())
            return {
                "fetched_at": fetched_at,
                "as_of": fetched_at,
                "coins": _join_predicted_fundings(raw),
            }

        return self._cached_fetch(
            self._cache_key("predicted_fundings"), load, label="predicted funding"
        )

    def fetch_candles(
        self,
        symbol: str,
        *,
        interval: str,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        """Return an official candle snapshot for a bounded time window."""
        # HIP-3 symbols carry their DEX prefix (``xyz:SP500``); Hyperliquid's
        # own listings do not (``BTC``). Both are valid candle coins.
        normalized_symbol = symbol.strip()
        if not normalized_symbol:
            raise ValueError("candle symbol must not be empty")
        if interval not in CANDLE_INTERVALS:
            raise ValueError(f"unsupported candle interval: {interval}")
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        start_millis = int(start.astimezone(UTC).timestamp() * 1000)
        end_millis = int(end.astimezone(UTC).timestamp() * 1000)
        if end_millis < start_millis:
            raise ValueError("candle end must not precede start")

        payload = {
            "type": CANDLE_REQUEST_TYPE,
            "req": {
                "coin": normalized_symbol,
                "interval": interval,
                "startTime": start_millis,
                "endTime": end_millis,
            },
        }

        def load() -> dict[str, Any]:
            raw = self._request(payload, f"{normalized_symbol!r} candle")
            if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
                raise DataUnavailable(
                    f"Hyperliquid returned an invalid {normalized_symbol!r} candle schema"
                )
            fetched_at = _utc_iso(self._wall_clock())
            close_times = [int(item["T"]) for item in raw if str(item.get("T", "")).isdigit()]
            return {
                "symbol": normalized_symbol,
                "interval": interval,
                "fetched_at": fetched_at,
                "as_of": _millis_iso(max(close_times)) if close_times else None,
                "candles": copy.deepcopy(raw),
                "request": copy.deepcopy(payload["req"]),
            }

        return self._cached_fetch(
            self._cache_key(
                "candles",
                normalized_symbol,
                interval,
                str(start_millis),
                str(end_millis),
            ),
            load,
            label=f"{normalized_symbol!r} candle",
        )

    def fetch_session_baseline(
        self,
        symbol: str,
        boundary: datetime,
        *,
        interval: str = "5m",
    ) -> dict[str, Any] | None:
        """Find the final candle close strictly before an internal-session boundary."""
        if boundary.tzinfo is None:
            boundary = boundary.replace(tzinfo=UTC)
        boundary_utc = boundary.astimezone(UTC)
        snapshot = self.fetch_candles(
            symbol,
            interval=interval,
            start=boundary_utc - timedelta(hours=24),
            end=boundary_utc - timedelta(milliseconds=1),
        )
        boundary_millis = int(boundary_utc.timestamp() * 1000)
        candidates: list[tuple[int, dict[str, Any], float]] = []
        for candle in snapshot["candles"]:
            try:
                close_millis = int(candle.get("T"))
            except (TypeError, ValueError):
                continue
            close = _finite_number(candle.get("c"))
            if close is not None and close_millis < boundary_millis:
                candidates.append((close_millis, candle, close))
        if not candidates:
            return None

        close_millis, candle, close = max(candidates, key=lambda item: item[0])
        distance_seconds = max(0.0, (boundary_millis - close_millis - 1) / 1000.0)
        if distance_seconds <= 15 * 60:
            proximity_quality = "high"
        elif distance_seconds <= 2 * 60 * 60:
            proximity_quality = "medium"
        else:
            proximity_quality = "low"
        return {
            "price": close,
            "interval": interval,
            "boundary_at": _utc_iso(boundary_utc),
            "candle_open_at": _millis_iso(candle.get("t")),
            "candle_close_at": _millis_iso(close_millis),
            "distance_seconds": round(distance_seconds, 3),
            "proximity_quality": proximity_quality,
            "fetched_at": snapshot["fetched_at"],
            "as_of": _millis_iso(close_millis),
            "cached": snapshot["cached"],
            "stale": snapshot["stale"],
            "age_seconds": snapshot["age_seconds"],
        }
