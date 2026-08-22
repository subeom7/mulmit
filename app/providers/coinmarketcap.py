"""CoinMarketCap global metrics (BTC/ETH dominance, total market cap) — keyed, ingest-only.

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.20): CoinMarketCap's pricing page
(accessed 2026-08-21) lists "Commercial use rights — the free Basic tier
included", 15,000 credits/month and 50 requests/minute for the Basic plan, and
the Commercial Terms require attribution (the customary wording is "Data
provided by CoinMarketCap" with a link) and forbid redistributing the data as a
standalone service.  Some third-party summaries call Basic personal-use only,
so the operator confirms the exact scope and attribution text in the Commercial
Terms when issuing the key; the text is configurable and travels inside the
payload for the UI to place next to the values.

Two endpoints are used, one credit per call each: ``/v1/global-metrics/quotes/latest``
every ``CMC_MAX_AGE`` seconds and ``/v2/cryptocurrency/quotes/latest`` for the
USDT/USDC circulating supply every ``CMC_STABLECOIN_MAX_AGE`` seconds.  The ingest
lane stores small blobs and the request path reads those blobs, so the monthly
budget stays at a few thousand credits.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import DataUnavailable, RateLimited

CMC_PROVIDER_ID = "coinmarketcap"
CMC_PUBLISHER = "CoinMarketCap"
CMC_GLOBAL_METRICS_URL = "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest"
CMC_SITE_URL = "https://coinmarketcap.com/"
CMC_PRICING_URL = "https://coinmarketcap.com/api/pricing/"
CMC_COMMERCIAL_TERMS_URL = "https://pro.coinmarketcap.com/user-agreement-commercial/"
CMC_DOCS_URL = "https://coinmarketcap.com/api/documentation/v1/#operation/getV1GlobalmetricsQuotesLatest"
CMC_QUOTES_URL = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest"
CMC_QUOTES_DOCS_URL = "https://coinmarketcap.com/api/documentation/v1/#operation/getV2CryptocurrencyQuotesLatest"
# CoinMarketCap ids are stable where tickers are not (several assets share a symbol).
STABLECOIN_IDS: dict[int, str] = {825: "USDT", 3408: "USDC"}
CMC_DEFAULT_ATTRIBUTION = "Data provided by CoinMarketCap"
CMC_PRICING_QUOTE = "Commercial use rights — the free Basic tier included (pricing page, accessed 2026-08-21)"
DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 2
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

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


def parse_global_metrics(raw: Any, *, fetched_at: str) -> dict[str, Any]:
    """Flatten the fields the dominance card uses; anything missing stays ``None``."""
    if not isinstance(raw, dict):
        raise DataUnavailable("CoinMarketCap returned a non-object payload")
    status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
    if status.get("error_code") not in (None, 0, "0"):
        raise DataUnavailable(
            f"CoinMarketCap error {status.get('error_code')}: {status.get('error_message')}"
        )
    data = raw.get("data")
    if not isinstance(data, dict):
        raise DataUnavailable("CoinMarketCap returned no global-metrics data")
    quote = data.get("quote") if isinstance(data.get("quote"), dict) else {}
    usd = quote.get("USD") if isinstance(quote.get("USD"), dict) else {}
    btc = _number(data.get("btc_dominance"))
    eth = _number(data.get("eth_dominance"))
    if btc is None:
        raise DataUnavailable("CoinMarketCap global metrics carry no btc_dominance")
    return {
        "fetched_at": fetched_at,
        "as_of": data.get("last_updated") or usd.get("last_updated") or fetched_at,
        "btc_dominance": btc,
        "eth_dominance": eth,
        "btc_dominance_yesterday": _number(data.get("btc_dominance_yesterday")),
        "eth_dominance_yesterday": _number(data.get("eth_dominance_yesterday")),
        "btc_dominance_24h_change_points": _number(data.get("btc_dominance_24h_percentage_change")),
        "eth_dominance_24h_change_points": _number(data.get("eth_dominance_24h_percentage_change")),
        "active_cryptocurrencies": data.get("active_cryptocurrencies"),
        "active_exchanges": data.get("active_exchanges"),
        "total_market_cap_usd": _number(usd.get("total_market_cap")),
        "total_market_cap_24h_change_percent": _number(usd.get("total_market_cap_yesterday_percentage_change")),
        "total_volume_24h_usd": _number(usd.get("total_volume_24h")),
        "total_volume_24h_change_percent": _number(usd.get("total_volume_24h_yesterday_percentage_change")),
        "altcoin_market_cap_usd": _number(usd.get("altcoin_market_cap")),
        "stablecoin_market_cap_usd": _number(usd.get("stablecoin_market_cap")),
        "stablecoin_24h_change_percent": _number(data.get("stablecoin_24h_percentage_change")),
        "stablecoin_volume_24h_usd": _number(
            usd.get("stablecoin_volume_24h") if usd.get("stablecoin_volume_24h") is not None else data.get("stablecoin_volume_24h")
        ),
        "defi_market_cap_usd": _number(usd.get("defi_market_cap")),
        "credit_count": status.get("credit_count"),
    }


def parse_quotes(raw: Any, *, fetched_at: str) -> dict[str, Any]:
    """Flatten ``/v2/cryptocurrency/quotes/latest``. ``data`` is keyed by id (object) when
    requested by id, or by symbol (list of candidates) when requested by symbol; both are read."""
    if not isinstance(raw, dict):
        raise DataUnavailable("CoinMarketCap returned a non-object payload")
    status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
    if status.get("error_code") not in (None, 0, "0"):
        raise DataUnavailable(
            f"CoinMarketCap error {status.get('error_code')}: {status.get('error_message')}"
        )
    data = raw.get("data")
    if not isinstance(data, dict):
        raise DataUnavailable("CoinMarketCap returned no quotes data")
    coins: list[dict[str, Any]] = []
    for entry in data.values():
        for item in entry if isinstance(entry, list) else [entry]:
            if not isinstance(item, dict):
                continue
            quote = item.get("quote") if isinstance(item.get("quote"), dict) else {}
            usd = quote.get("USD") if isinstance(quote.get("USD"), dict) else {}
            supply = _number(item.get("circulating_supply"))
            market_cap = _number(usd.get("market_cap"))
            if supply is None and market_cap is None:
                continue
            coins.append({
                "id": item.get("id"),
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "slug": item.get("slug"),
                "price_usd": _number(usd.get("price")),
                "market_cap_usd": market_cap,
                "circulating_supply": supply,
                "total_supply": _number(item.get("total_supply")),
                "volume_24h_usd": _number(usd.get("volume_24h")),
                "market_cap_dominance_percent": _number(usd.get("market_cap_dominance")),
                "as_of": usd.get("last_updated") or item.get("last_updated"),
            })
    if not coins:
        raise DataUnavailable("CoinMarketCap quotes carry no usable rows")
    return {"fetched_at": fetched_at, "coins": coins, "credit_count": status.get("credit_count")}


class CoinMarketCapProvider:
    """One keyed GET per refresh; the key never leaves the ingest process."""

    name = CMC_PROVIDER_ID

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("CoinMarketCap API key is required")
        self._api_key = api_key.strip()
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep

    def fetch_global_metrics(self) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-CMC_PRO_API_KEY": self._api_key,
        }
        raw = self._request(f"{CMC_GLOBAL_METRICS_URL}?convert=USD", headers)
        return parse_global_metrics(raw, fetched_at=_utc_iso(self._wall_clock()))

    def fetch_quotes(self, ids: list[int] | tuple[int, ...]) -> dict[str, Any]:
        """Latest quotes for CoinMarketCap ids (one credit per 100 ids)."""
        if not ids:
            raise ValueError("at least one CoinMarketCap id is required")
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-CMC_PRO_API_KEY": self._api_key,
        }
        joined = ",".join(str(int(i)) for i in ids)
        raw = self._request(f"{CMC_QUOTES_URL}?id={joined}&convert=USD", headers)
        return parse_quotes(raw, fetched_at=_utc_iso(self._wall_clock()))

    def _request(self, url: str, headers: dict[str, str]) -> Any:
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._transport(url, headers, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    if attempt >= self.retries:
                        raise RateLimited("CoinMarketCap rate limit or credit cap reached") from exc
                elif exc.code in (401, 403):
                    raise DataUnavailable(
                        f"CoinMarketCap rejected the API key (HTTP {exc.code})"
                    ) from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(
                        f"CoinMarketCap rejected the request with HTTP {exc.code}"
                    ) from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("CoinMarketCap returned an unreadable response") from exc
            if attempt < self.retries:
                self._sleep(min(0.5 * (2**attempt), 2.0))
        raise DataUnavailable("CoinMarketCap global metrics are unavailable") from last_error
