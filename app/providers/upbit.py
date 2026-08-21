"""Upbit (Dunamu) public quotation client — KRW tickers only, no key, read-only.

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.19): the Upbit Open API terms
(2023-12-15) define quotation lookups as part of the service and assert in §5
that "Open API 서비스상에서 제공되는 모든 데이터 및 내용에 대한 저작권은 두나무에
있으므로 사용자는 이를 무단으로 사용하거나 변경하여서는 안 됩니다"; they neither
permit nor forbid public redisplay explicitly.  The lane therefore ships behind
``UPBIT_ENABLED`` (default false) as ``pending_rights`` until a written answer or
a recorded operator risk acceptance opens it.

Operational facts (docs.upbit.com, 2026-08-21): the quotation API needs no
authentication, limits are per IP (10 req/s, 600/min for the ticker group —
``Remaining-Req: group=ticker; min=600; sec=8`` observed), and requests that
carry an ``Origin`` header are throttled to one per ten seconds, which is why
Mulmit relays from its server (one call per TTL) rather than from browsers.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import DataUnavailable, RateLimited
from .http_cache import TtlCache

UPBIT_PROVIDER_ID = "upbit"
UPBIT_PUBLISHER = "업비트 (두나무)"
UPBIT_PUBLISHER_EN = "Upbit (Dunamu)"
UPBIT_TICKER_URL = "https://api.upbit.com/v1/ticker"
UPBIT_DOCS_URL = "https://docs.upbit.com/kr/reference/ticker"
UPBIT_TERMS_URL = "https://static.upbit.com/terms/legacy/openapi_agreement_20231215.html"
UPBIT_RATE_LIMIT_DOCS = "https://docs.upbit.com/kr/reference/rate-limits"
UPBIT_TERMS_QUOTE = (
    "Open API 서비스상에서 제공되는 모든 데이터 및 내용에 대한 저작권은 두나무에 있으므로 "
    "사용자는 이를 무단으로 사용하거나 변경하여서는 안 됩니다. (Open API 이용약관 제5조, 2023-12-15)"
)
DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 1
DEFAULT_TTL = 15.0
DEFAULT_STALE_TTL = 300.0
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

Transport = Callable[[str, float], Any]


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _millis_iso(value: Any) -> str | None:
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    try:
        return _utc_iso(dt.datetime.fromtimestamp(millis / 1000.0, tz=dt.UTC))
    except (OverflowError, OSError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _default_transport(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}, method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def parse_tickers(raw: Any, *, fetched_at: str) -> dict[str, Any]:
    """Keep only the fields the kimchi lane uses; malformed rows are dropped."""
    if not isinstance(raw, list):
        raise DataUnavailable("Upbit returned a non-list ticker payload")
    tickers: dict[str, dict[str, Any]] = {}
    latest_ms = 0
    for item in raw:
        if not isinstance(item, dict):
            continue
        market = str(item.get("market") or "").strip().upper()
        price = _number(item.get("trade_price"))
        if not market or price is None or price <= 0:
            continue
        try:
            stamp = int(item.get("timestamp") or 0)
        except (TypeError, ValueError):
            stamp = 0
        latest_ms = max(latest_ms, stamp)
        rate = _number(item.get("signed_change_rate"))
        tickers[market] = {
            "market": market,
            "trade_price": price,
            "prev_closing_price": _number(item.get("prev_closing_price")),
            "signed_change_rate": rate,
            "change_24h_percent": round(rate * 100.0, 4) if rate is not None else None,
            "acc_trade_price_24h": _number(item.get("acc_trade_price_24h")),
            "timestamp": stamp or None,
            "traded_at": _millis_iso(stamp) if stamp else None,
        }
    if not tickers:
        raise DataUnavailable("Upbit returned no readable tickers")
    return {
        "fetched_at": fetched_at,
        "as_of": _millis_iso(latest_ms) if latest_ms else fetched_at,
        "tickers": tickers,
    }


class UpbitProvider:
    """Fetch a fixed set of KRW tickers with a single-flight TTL cache."""

    name = UPBIT_PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        ttl: float = DEFAULT_TTL,
        stale_ttl: float = DEFAULT_STALE_TTL,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep
        self._cache = TtlCache(ttl=ttl, stale_ttl=stale_ttl)

    def clear_cache(self) -> None:
        self._cache.clear()

    def fetch_tickers(self, markets: list[str]) -> dict[str, Any]:
        wanted = sorted({str(m).strip().upper() for m in markets if str(m).strip()})
        if not wanted:
            raise ValueError("at least one market is required")
        query = urllib.parse.urlencode({"markets": ",".join(wanted)})
        url = f"{UPBIT_TICKER_URL}?{query}"

        def load() -> dict[str, Any]:
            raw = self._request(url)
            return parse_tickers(raw, fetched_at=_utc_iso(self._wall_clock()))

        return self._cache.fetch(",".join(wanted), load, label="Upbit ticker")

    def _request(self, url: str) -> Any:
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._transport(url, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    if attempt >= self.retries:
                        raise RateLimited("Upbit rate limit reached") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(f"Upbit rejected the request with HTTP {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("Upbit returned an unreadable response") from exc
            if attempt < self.retries:
                self._sleep(min(0.3 * (2**attempt), 1.0))
        raise DataUnavailable("Upbit ticker data is unavailable") from last_error
