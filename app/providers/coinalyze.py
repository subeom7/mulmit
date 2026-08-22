"""Coinalyze — cross-venue liquidation totals and open interest (keyed, ingest-only).

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.27, `DS-2026-019`): written
permission from contact@coinalyze.net on 2026-08-22, answering a question that
listed exactly this use — aggregated liquidation totals and open interest for a
few coins, relayed through our own server with a short cache, daily aggregates
stored privately, advertising allowed. The single condition is that the link
back to Coinalyze is **dofollow**; `tests/test_outbound_links.py` guards it.

Two things measured on 2026-08-22 shape this module:

1. **Silence is not zero.** An unknown symbol and a symbol the venue simply has
   no data for both come back as `200 []` — there is no error to catch. A sum
   over five symbols quietly becomes a sum over three (Hyperliquid, Gate.io,
   dYdX and Kraken return nothing for BTC liquidations; Binance, Bybit, OKX,
   Huobi and BitMEX answer). So every read here reports which venues actually
   answered, and the card names them. A total is "these venues", never "the
   market".

2. **Each symbol costs one API call**, even though `symbols` accepts twenty
   comma-separated (documented). The budget is 40 calls a minute per key, so
   the venue list is deliberately short and symbols are resolved from the
   market list rather than guessed — asking for a symbol that does not exist
   spends a call and returns the same empty list as a real one.
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

COINALYZE_PROVIDER_ID = "coinalyze"
COINALYZE_PUBLISHER = "Coinalyze"
COINALYZE_API_URL = "https://api.coinalyze.net/v1"
COINALYZE_SITE_URL = "https://coinalyze.net/"
COINALYZE_DOCS_URL = "https://api.coinalyze.net/v1/doc/"
COINALYZE_ATTRIBUTION = "Data: Coinalyze"
# Quoted in the register and carried in the payload, so the condition travels
# with the values it applies to.
COINALYZE_PERMISSION_QUOTE = (
    "Yes, you can use our API for your project. Regarding the attribution, the "
    "link(s) to Coinalyze website must be a dofollow link."
)
COINALYZE_PERMISSION_SOURCE = "contact@coinalyze.net, 2026-08-22"

DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

# Venue codes are the suffix after the dot in a Coinalyze symbol. These five are
# the ones measured to publish liquidation history for the majors; the others
# come back empty and would silently shrink the total.
LIQUIDATION_VENUES: tuple[str, ...] = ("A", "6", "3", "4", "0")
# Open interest is published more widely — Hyperliquid answers here even though
# it has no liquidation feed.
OPEN_INTEREST_VENUES: tuple[str, ...] = ("A", "6", "3", "H")
VENUE_NAMES: dict[str, str] = {
    "A": "Binance",
    "6": "Bybit",
    "3": "OKX",
    "4": "Huobi",
    "0": "BitMEX",
    "H": "Hyperliquid",
}
MAX_SYMBOLS_PER_CALL = 20

Transport = Callable[[str, dict[str, str], float], Any]


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def venue_code(symbol: str) -> str:
    """The exchange code Coinalyze appends after the dot (`BTCUSDT_PERP.A` gives `A`)."""
    return symbol.rsplit(".", 1)[-1] if "." in symbol else ""


def venue_name(symbol: str) -> str:
    code = venue_code(symbol)
    return VENUE_NAMES.get(code, code or symbol)


def _preference(candidate: dict[str, str]) -> tuple[int, int, str]:
    quote_rank = {"USDT": 0, "USDC": 1, "USD": 2}.get(candidate["quote"].upper(), 3)
    return (quote_rank, len(candidate["symbol"]), candidate["symbol"])


def resolve_symbols(
    markets: Any, base_asset: str, venues: tuple[str, ...]
) -> list[dict[str, str]]:
    """Perpetual symbols for one asset on the given venues, at most one per venue.

    A stable-quoted market is preferred: those are denominated in the base asset
    and convert to USD cleanly, while coin-margined ones are quoted in the
    contract currency. Where a venue lists several, the shortest symbol wins so
    the pick does not drift between refreshes.
    """
    wanted = base_asset.strip().upper()
    by_venue: dict[str, dict[str, str]] = {}
    for market in markets if isinstance(markets, list) else []:
        if not isinstance(market, dict) or not market.get("is_perpetual"):
            continue
        if str(market.get("base_asset") or "").upper() != wanted:
            continue
        symbol = market.get("symbol")
        code = market.get("exchange")
        if not isinstance(symbol, str) or code not in venues:
            continue
        if str(market.get("quote_asset") or "").upper() not in ("USDT", "USD", "USDC"):
            continue
        candidate = {
            "symbol": symbol,
            "venue": code,
            "venue_name": VENUE_NAMES.get(code, code),
            "quote": str(market.get("quote_asset") or ""),
            "denominated_in": str(market.get("oi_lq_vol_denominated_in") or ""),
        }
        current = by_venue.get(code)
        if current is None or _preference(candidate) < _preference(current):
            by_venue[code] = candidate
    return [by_venue[code] for code in venues if code in by_venue]


def parse_liquidations(raw: Any, asked: list[str]) -> dict[str, Any]:
    """Per-venue long/short series, plus the symbols that stayed silent.

    The silence matters as much as the numbers: it is the difference between a
    total and a partial total, and the API offers no other signal.
    """
    if not isinstance(raw, list):
        raise DataUnavailable("Coinalyze returned a non-list liquidation payload")
    answered: dict[str, list[dict[str, float]]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        history = entry.get("history")
        if not isinstance(symbol, str) or not isinstance(history, list):
            continue
        points: list[dict[str, float]] = []
        for point in history:
            if not isinstance(point, dict):
                continue
            stamp = point.get("t")
            longs, shorts = _number(point.get("l")), _number(point.get("s"))
            if not isinstance(stamp, int) or longs is None or shorts is None:
                continue
            points.append({"t": stamp, "long": longs, "short": shorts})
        if points:
            answered[symbol] = sorted(points, key=lambda row: row["t"])
    return {
        "series": answered,
        "answered": [symbol for symbol in asked if symbol in answered],
        "silent": [symbol for symbol in asked if symbol not in answered],
    }


def parse_open_interest(raw: Any, asked: list[str]) -> dict[str, Any]:
    if not isinstance(raw, list):
        raise DataUnavailable("Coinalyze returned a non-list open-interest payload")
    values: dict[str, dict[str, Any]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        value = _number(entry.get("value"))
        if not isinstance(symbol, str) or value is None:
            continue
        updated = entry.get("update")
        values[symbol] = {
            "value": value,
            "updated_at": _utc_iso(dt.datetime.fromtimestamp(updated / 1000, tz=dt.UTC))
            if isinstance(updated, (int, float))
            else None,
        }
    return {
        "values": values,
        "answered": [symbol for symbol in asked if symbol in values],
        "silent": [symbol for symbol in asked if symbol not in values],
    }


class CoinalyzeProvider:
    """Thin keyed client. One call per symbol, so callers keep the lists short."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: Transport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = (api_key or "").strip()
        if not key:
            raise DataUnavailable("Coinalyze API key is not configured")
        self._key = key
        self._transport = transport or _default_transport
        self._timeout = timeout
        self._retries = max(0, retries)
        self._sleep = sleep

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None})
        url = f"{COINALYZE_API_URL}{path}" + (f"?{query}" if query else "")
        headers = {"api_key": self._key, "User-Agent": USER_AGENT, "Accept": "application/json"}
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                return self._transport(url, headers, self._timeout)
            except urllib.error.HTTPError as exc:  # noqa: PERF203
                if exc.code == 429:
                    # Documented: the response carries Retry-After. 40 calls a
                    # minute is easy to trip if a caller widens the venue list.
                    raise RateLimited("Coinalyze rate limit reached") from exc
                if exc.code in (401, 403):
                    raise DataUnavailable("Coinalyze rejected the API key") from exc
                last = exc
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                last = exc
            if attempt < self._retries:
                self._sleep(0.6 * (attempt + 1))
        raise DataUnavailable(f"Coinalyze request failed: {last}")

    def fetch_markets(self) -> Any:
        return self._get("/future-markets")

    def fetch_liquidations(
        self, symbols: list[str], *, interval: str, start: int, end: int
    ) -> dict[str, Any]:
        if not symbols:
            return {"series": {}, "answered": [], "silent": []}
        if len(symbols) > MAX_SYMBOLS_PER_CALL:
            raise DataUnavailable("Coinalyze accepts at most 20 symbols per call")
        raw = self._get(
            "/liquidation-history",
            {
                "symbols": ",".join(symbols),
                "interval": interval,
                "from": start,
                "to": end,
                # Markets are denominated in the base asset, the quote asset or
                # contracts depending on the venue; without this the numbers are
                # neither addable nor dollars.
                "convert_to_usd": "true",
            },
        )
        return parse_liquidations(raw, symbols)

    def fetch_open_interest(self, symbols: list[str]) -> dict[str, Any]:
        if not symbols:
            return {"values": {}, "answered": [], "silent": []}
        if len(symbols) > MAX_SYMBOLS_PER_CALL:
            raise DataUnavailable("Coinalyze accepts at most 20 symbols per call")
        raw = self._get(
            "/open-interest", {"symbols": ",".join(symbols), "convert_to_usd": "true"}
        )
        return parse_open_interest(raw, symbols)
