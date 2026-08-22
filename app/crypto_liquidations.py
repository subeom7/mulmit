"""Cross-venue liquidation totals and open interest for the majors.

The number this lane reports is a sum over a named handful of venues, never
"the market". Coinalyze publishes no aggregate symbol — every symbol belongs to
one exchange — and a symbol it has no data for returns `200 []` exactly like a
symbol that does not exist. So a total assembled here is only as complete as
the venues that actually answered, and both the venues included and any that
went silent travel with the value for the card to print.

Ingest fetches; the request path reads the stored blob. One symbol costs one
API call against a 40-a-minute budget, and a refresh spends roughly nineteen
(the market list, then liquidations and open interest for two coins).

How often that happens is the ingest tick, not the constant below:
`INGEST_INTERVAL` defaults to 15 minutes, so the values are up to that old and
the lane averages well under two calls a minute. `REFRESH_INTERVAL` is only a
floor — it stops an extra tick or a manual run from re-fetching what was just
collected.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import config, data_rights, store
from .providers.base import DataUnavailable, RateLimited
from .providers.coinalyze import (
    COINALYZE_ATTRIBUTION,
    COINALYZE_DOCS_URL,
    COINALYZE_PERMISSION_QUOTE,
    COINALYZE_PERMISSION_SOURCE,
    COINALYZE_PROVIDER_ID,
    COINALYZE_PUBLISHER,
    COINALYZE_SITE_URL,
    LIQUIDATION_VENUES,
    OPEN_INTEREST_VENUES,
    CoinalyzeProvider,
    resolve_symbols,
    venue_name,
)

log = logging.getLogger(__name__)

CACHE_KEY = "crypto_liquidations_v1"
CACHE_TTL = 900  # the refresh runs every 5 minutes; serve a little past that
# A floor, not a schedule: the collection cadence is config.INGEST_INTERVAL.
REFRESH_INTERVAL = 300
WINDOW_HOURS = 24
# Two coins keeps the call budget comfortable and the card readable. Every
# extra coin costs nine calls a cycle.
COINS: tuple[tuple[str, str, str], ...] = (
    ("BTC", "비트코인", "Bitcoin"),
    ("ETH", "이더리움", "Ethereum"),
)


class LiquidationsUnavailable(RuntimeError):
    """Nothing has been collected yet."""


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.UTC)


def _provider() -> CoinalyzeProvider:
    return CoinalyzeProvider(config.COINALYZE_API_KEY)


def _coin_block(
    provider: CoinalyzeProvider,
    markets: Any,
    symbol: str,
    label_ko: str,
    label_en: str,
    *,
    now: dt.datetime,
) -> dict[str, Any]:
    end = int(now.timestamp())
    start = end - (WINDOW_HOURS + 2) * 3600

    liquidation_markets = resolve_symbols(markets, symbol, LIQUIDATION_VENUES)
    liquidations = provider.fetch_liquidations(
        [market["symbol"] for market in liquidation_markets],
        interval="1hour",
        start=start,
        end=end,
    )

    venues: list[dict[str, Any]] = []
    long_total = short_total = 0.0
    newest_bucket: int | None = None
    last_long = last_short = 0.0
    for market in liquidation_markets:
        points = liquidations["series"].get(market["symbol"])
        if not points:
            continue
        window = points[-WINDOW_HOURS:]
        venue_long = sum(point["long"] for point in window)
        venue_short = sum(point["short"] for point in window)
        long_total += venue_long
        short_total += venue_short
        newest = points[-1]
        if newest_bucket is None or newest["t"] > newest_bucket:
            newest_bucket = newest["t"]
        venues.append(
            {
                "venue": market["venue_name"],
                "symbol": market["symbol"],
                "long_usd": venue_long,
                "short_usd": venue_short,
            }
        )
    # Only the venues sharing the newest bucket contribute to the hour figure —
    # a venue whose latest bucket is older would otherwise be counted as zero.
    for market in liquidation_markets:
        points = liquidations["series"].get(market["symbol"])
        if points and newest_bucket is not None and points[-1]["t"] == newest_bucket:
            last_long += points[-1]["long"]
            last_short += points[-1]["short"]

    open_interest_markets = resolve_symbols(markets, symbol, OPEN_INTEREST_VENUES)
    open_interest = provider.fetch_open_interest(
        [market["symbol"] for market in open_interest_markets]
    )
    oi_venues = [
        {
            "venue": market["venue_name"],
            "symbol": market["symbol"],
            "value_usd": open_interest["values"][market["symbol"]]["value"],
            "updated_at": open_interest["values"][market["symbol"]]["updated_at"],
        }
        for market in open_interest_markets
        if market["symbol"] in open_interest["values"]
    ]

    total = long_total + short_total
    return {
        "symbol": symbol,
        "name": {"ko": label_ko, "en": label_en},
        "hub": f"/crypto/{symbol}",
        "liquidations": {
            "window_hours": WINDOW_HOURS,
            "long_usd": long_total,
            "short_usd": short_total,
            "total_usd": total,
            # Which side got hit is the reading; the ratio says it without a verdict.
            "long_share_percent": (long_total / total * 100.0) if total > 0 else None,
            "latest_hour": {
                "bucket_start": _iso(dt.datetime.fromtimestamp(newest_bucket, tz=dt.UTC))
                if newest_bucket
                else None,
                "long_usd": last_long,
                "short_usd": last_short,
            },
            "venues": sorted(venues, key=lambda row: -(row["long_usd"] + row["short_usd"])),
            "venues_silent": [venue_name(item) for item in liquidations["silent"]],
        },
        "open_interest": {
            "total_usd": sum(row["value_usd"] for row in oi_venues),
            "venues": sorted(oi_venues, key=lambda row: -row["value_usd"]),
            "venues_silent": [venue_name(item) for item in open_interest["silent"]],
        },
    }


def _source_block() -> dict[str, Any]:
    return {
        "provider": COINALYZE_PROVIDER_ID,
        "provider_name": COINALYZE_PUBLISHER,
        "publisher": COINALYZE_PUBLISHER,
        "url": COINALYZE_SITE_URL,
        "docs_url": COINALYZE_DOCS_URL,
        "notice": COINALYZE_ATTRIBUTION,
        "permission_quote": COINALYZE_PERMISSION_QUOTE,
        "permission_source": COINALYZE_PERMISSION_SOURCE,
    }


def refresh_crypto_liquidations(*, force: bool = False) -> dict[str, Any]:
    """Collect one snapshot into the blob the request path serves."""
    if not data_rights.coinalyze_ingest_enabled():
        return {"status": "disabled"}
    stored = store.load_report(CACHE_KEY, REFRESH_INTERVAL if not force else 0)
    if stored is not None and not force:
        return {"status": "fresh"}

    provider = _provider()
    now = _now()
    markets = provider.fetch_markets()
    coins: list[dict[str, Any]] = []
    for symbol, label_ko, label_en in COINS:
        try:
            coins.append(_coin_block(provider, markets, symbol, label_ko, label_en, now=now))
        except (DataUnavailable, RateLimited):
            log.warning("Coinalyze lane: %s could not be collected", symbol, exc_info=True)
    if not coins:
        raise DataUnavailable("Coinalyze returned nothing for any coin")

    named = sorted({row["venue"] for coin in coins for row in coin["liquidations"]["venues"]})
    payload = {
        "generated_at": _iso(now),
        "coins": coins,
        "basis_ko": (
            f"최근 {WINDOW_HOURS}시간 청산 합계입니다. {'·'.join(named)} {len(named)}개 거래소의 합이며 "
            "전체 시장 합계가 아닙니다 — 나머지 거래소는 이 API가 청산 데이터를 주지 않습니다. "
            "값은 1시간 단위로 집계되며 실시간 체결 피드가 아니고, 가장 최근 구간은 아직 채워지는 중일 수 있습니다. "
            "거래소마다 표시 단위가 달라 USD로 환산한 값입니다."
        ),
        "basis_en": (
            f"Liquidations over the last {WINDOW_HOURS} hours, summed across "
            f"{len(named)} venues ({', '.join(named)}) — not a market-wide total; the other "
            "venues publish no liquidation data through this API. Bucketed hourly, not a live "
            "trade feed, and the newest bucket may still be filling. Converted to USD because "
            "venues denominate these differently."
        ),
        "attribution": {
            "required": True,
            "text": COINALYZE_ATTRIBUTION,
            "text_ko": "데이터: Coinalyze",
            "url": COINALYZE_SITE_URL,
            # The written permission asks for this explicitly; never add
            # nofollow, ugc or sponsored to this link.
            "dofollow": True,
        },
        "source": _source_block(),
    }
    store.save_report(CACHE_KEY, payload)
    return {"status": "ok", "coins": len(coins), "venues": len(named)}


def build_crypto_liquidations() -> dict[str, Any]:
    """Serve the stored snapshot; never call upstream on a request."""
    if not data_rights.coinalyze_serving_enabled():
        raise LiquidationsUnavailable("lane disabled")
    payload = store.load_report(CACHE_KEY, CACHE_TTL)
    if payload is None:
        raise LiquidationsUnavailable("nothing collected yet")
    return payload
