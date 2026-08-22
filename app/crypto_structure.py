"""Crypto market structure — BTC/ETH dominance and total market cap (CoinMarketCap).

Ingest stores one small blob from ``/v1/global-metrics/quotes/latest`` every
``CMC_MAX_AGE`` seconds; the request path reads the blob only.  The lane is
keyed and defaults off: ``CRYPTO_SECTION_ENABLED`` + ``CMC_ENABLED`` open serving,
and the key (``CMC_API_KEY``, ingest-only) is what makes the refresh run.  The
payload carries the attribution the UI must keep next to the values
(docs/DATA_SOURCE_REGISTER.md §3.20).

Nothing is derived beyond subtraction: "others" dominance = 100 − BTC − ETH.
Dominance depends on the publisher's universe, so the publisher travels with
the number rather than being presented as *the* dominance.

Stablecoin supply (USDT, USDC) rides the same key through a second, hourly blob
from ``/v2/cryptocurrency/quotes/latest``.  Share = stablecoin market cap ÷ total
market cap (arithmetic on two published numbers); 7d/30d supply changes come from
Mulmit's own daily points accumulated inside that blob — dated, never back-filled.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

from . import config, data_rights, store
from .providers.base import DataUnavailable
from .providers.coinmarketcap import (
    CMC_COMMERCIAL_TERMS_URL,
    CMC_DOCS_URL,
    CMC_GLOBAL_METRICS_URL,
    CMC_PRICING_QUOTE,
    CMC_PRICING_URL,
    CMC_PROVIDER_ID,
    CMC_PUBLISHER,
    CMC_QUOTES_URL,
    CMC_SITE_URL,
    STABLECOIN_IDS,
    CoinMarketCapProvider,
)

CACHE_KEY = "crypto_global_metrics_v1"
SERVE_TTL_SECONDS = 60 * 60 * 12
STALE_AFTER_SECONDS = 60 * 60 * 2
LOAD_CACHE_SECONDS = 60.0
STABLE_CACHE_KEY = "crypto_stablecoins_v1"
STABLE_STALE_AFTER_SECONDS = 60 * 60 * 3
HISTORY_KEEP_POINTS = 400
# The refresh reads its own previous blob back regardless of age to carry the history forward.
HISTORY_READ_TTL_SECONDS = 10 * 365 * 24 * 3600

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


class CryptoStructureUnavailable(Exception):
    """``reason`` is ``disabled`` or ``collecting``; the route maps it to a 503 contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def serving_enabled() -> bool:
    return data_rights.cmc_serving_enabled()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def refresh_crypto_structure(*, force: bool = False, provider: Any | None = None) -> dict[str, Any]:
    """Ingest lane: one keyed call, one blob. Zero network calls while the lane is off."""
    if not data_rights.cmc_ingest_enabled():
        return {"skipped": "not_configured" if serving_enabled() else "disabled"}
    if not force and store.load_report(CACHE_KEY, config.CMC_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or CoinMarketCapProvider(
        config.CMC_API_KEY, timeout=config.CMC_TIMEOUT, retries=config.CMC_RETRIES
    )
    metrics = client.fetch_global_metrics()
    if metrics.get("btc_dominance") is None:
        raise DataUnavailable("CoinMarketCap global metrics arrived without dominance")
    store.save_report(
        CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": metrics.get("fetched_at"),
            "metrics": metrics,
        },
    )
    clear_cache()
    return {"updated": 1, "credit_count": metrics.get("credit_count")}


def _load_cached(key: str, ttl: int) -> dict[str, Any] | None:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    blob = store.load_report(key, ttl)
    with _lock:
        _cache[key] = (now + LOAD_CACHE_SECONDS, blob)
    return blob


def _load_blob() -> dict[str, Any] | None:
    return _load_cached(CACHE_KEY, SERVE_TTL_SECONDS)


def refresh_crypto_stablecoins(
    *, force: bool = False, provider: Any | None = None, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Ingest lane: USDT/USDC supply from ``/v2/cryptocurrency/quotes/latest`` (one credit per call,
    ``CMC_STABLECOIN_MAX_AGE`` cadence). Each refresh also keeps one point per UTC day inside the
    blob so 7d/30d supply changes can be shown once those days exist — Mulmit's accumulation, dated."""
    if not data_rights.cmc_ingest_enabled():
        return {"skipped": "not_configured" if serving_enabled() else "disabled"}
    if not force and store.load_report(STABLE_CACHE_KEY, config.CMC_STABLECOIN_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or CoinMarketCapProvider(
        config.CMC_API_KEY, timeout=config.CMC_TIMEOUT, retries=config.CMC_RETRIES
    )
    quotes = client.fetch_quotes(sorted(STABLECOIN_IDS))
    coins = [
        coin for coin in quotes.get("coins") or []
        if coin.get("id") in STABLECOIN_IDS or coin.get("symbol") in STABLECOIN_IDS.values()
    ]
    if not coins:
        raise DataUnavailable("CoinMarketCap quotes arrived without the requested stablecoins")
    for coin in coins:
        coin["symbol"] = STABLECOIN_IDS.get(coin.get("id"), coin.get("symbol"))
    moment = now or _parse_iso(quotes.get("fetched_at")) or dt.datetime.now(dt.UTC)
    previous = store.load_report(STABLE_CACHE_KEY, HISTORY_READ_TTL_SECONDS) or {}
    history = _append_history(previous.get("history"), coins, moment, quotes.get("fetched_at"))
    store.save_report(
        STABLE_CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": quotes.get("fetched_at"),
            "coins": coins,
            "history": history,
        },
    )
    clear_cache()
    return {"updated": len(coins), "credit_count": quotes.get("credit_count"), "history_points": len(history)}


def _append_history(history: Any, coins: list[dict[str, Any]], moment: dt.datetime, as_of: Any) -> list[dict[str, Any]]:
    """One point per UTC day; a later refresh on the same day replaces that day's point."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    day = moment.astimezone(dt.UTC).date().isoformat()
    points = [p for p in (history or []) if isinstance(p, dict) and isinstance(p.get("date"), str) and p["date"] != day]
    points.append({
        "date": day,
        "as_of": as_of,
        "supply": {coin["symbol"]: coin.get("circulating_supply") for coin in coins},
        "market_cap_usd": {coin["symbol"]: coin.get("market_cap_usd") for coin in coins},
    })
    points.sort(key=lambda p: p["date"])
    return points[-HISTORY_KEEP_POINTS:]


def _history_change(points: list[dict[str, Any]], symbol: Any, current: Any, today: dt.date, days: int) -> float | None:
    """Percent change of ``current`` vs the stored supply ``days`` ago (latest stored day within a 2-day grace window)."""
    if not isinstance(current, (int, float)) or current <= 0:
        return None
    target = today - dt.timedelta(days=days)
    earliest = target - dt.timedelta(days=2)
    base = None
    for point in points:
        try:
            day = dt.date.fromisoformat(point.get("date"))
        except (TypeError, ValueError):
            continue
        if earliest <= day <= target:
            value = (point.get("supply") or {}).get(symbol)
            if isinstance(value, (int, float)) and value > 0:
                base = float(value)  # points are date-sorted, so the latest qualifying day wins
    return None if base is None else (float(current) / base - 1.0) * 100.0


def _stablecoin_block(metrics: dict[str, Any], blob: dict[str, Any] | None, moment: dt.datetime) -> dict[str, Any]:
    total_cap = metrics.get("total_market_cap_usd")
    agg_cap = metrics.get("stablecoin_market_cap_usd")
    share = None
    if isinstance(total_cap, (int, float)) and total_cap and isinstance(agg_cap, (int, float)):
        share = agg_cap / total_cap * 100.0
    block: dict[str, Any] = {
        "status": "collecting",
        "as_of": None,
        "fetched_at": None,
        "stale": None,
        "aggregate": {
            "market_cap_usd": _round(agg_cap, 2),
            "share_of_total_percent": _round(share, 4),
            "change_24h_percent": _round(metrics.get("stablecoin_24h_change_percent"), 4),
            "volume_24h_usd": _round(metrics.get("stablecoin_volume_24h_usd"), 2),
            "basis": "CoinMarketCap stablecoin aggregate; share = stablecoin market cap ÷ total market cap (arithmetic)",
        },
        "coins": [],
        "history": {
            "status": "collecting",
            "since": None,
            "points": 0,
            "basis": (
                "Mulmit's own snapshots, one point per UTC day from the first collection onward; "
                "7d/30d changes appear once those days exist and are never back-filled"
            ),
        },
        "cadence": f"ingest refresh every {config.CMC_STABLECOIN_MAX_AGE}s",
        "api_url": CMC_QUOTES_URL,
    }
    coins = blob.get("coins") if isinstance(blob, dict) else None
    if not isinstance(coins, list) or not coins:
        return block
    points = [p for p in (blob.get("history") or []) if isinstance(p, dict) and isinstance(p.get("date"), str)]
    fetched_at = _parse_iso(blob.get("fetched_at"))
    age = (moment - fetched_at).total_seconds() if fetched_at else None
    today = (fetched_at or moment).astimezone(dt.UTC).date()
    rows: list[dict[str, Any]] = []
    any_change = False
    for coin in coins:
        if not isinstance(coin, dict):
            continue
        symbol = coin.get("symbol")
        supply = coin.get("circulating_supply")
        price = coin.get("price_usd")
        market_cap = coin.get("market_cap_usd")
        change_7d = _history_change(points, symbol, supply, today, 7)
        change_30d = _history_change(points, symbol, supply, today, 30)
        any_change = any_change or change_7d is not None
        share_of_stable = None
        if isinstance(market_cap, (int, float)) and isinstance(agg_cap, (int, float)) and agg_cap:
            share_of_stable = float(market_cap) / agg_cap * 100.0
        rows.append({
            "id": coin.get("id"),
            "symbol": symbol,
            "name": coin.get("name"),
            "circulating_supply": _round(supply, 2),
            "market_cap_usd": _round(market_cap, 2),
            "price_usd": _round(price, 6),
            "peg_deviation_bp": _round((float(price) - 1.0) * 10000.0, 2) if isinstance(price, (int, float)) else None,
            "share_of_stablecoins_percent": _round(share_of_stable, 4),
            "market_cap_dominance_percent": _round(coin.get("market_cap_dominance_percent"), 4),
            "volume_24h_usd": _round(coin.get("volume_24h_usd"), 2),
            "change_7d_percent": _round(change_7d, 4),
            "change_30d_percent": _round(change_30d, 4),
            "as_of": coin.get("as_of"),
            "source_url": f"https://coinmarketcap.com/currencies/{coin.get('slug')}/" if coin.get("slug") else CMC_SITE_URL,
        })
    block.update({
        "status": "ok",
        "as_of": blob.get("fetched_at"),
        "fetched_at": blob.get("fetched_at"),
        "stale": age is None or age > STABLE_STALE_AFTER_SECONDS,
        "coins": rows,
    })
    block["history"].update({
        "status": "ok" if any_change else "collecting",
        "since": points[0]["date"] if points else None,
        "points": len(points),
    })
    block["aggregate"]["share_basis"] = (
        "coin share of stablecoins = coin market cap (hourly blob) ÷ stablecoin aggregate (15-minute blob); timestamps differ slightly"
    )
    return block


def _parse_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _round(value: Any, digits: int) -> float | None:
    try:
        return None if value is None else round(float(value), digits)
    except (TypeError, ValueError):
        return None


_DISCLAIMER = {
    "ko": (
        "도미넌스와 총시총은 CoinMarketCap이 집계하는 유니버스 기준이며 산출 기관에 따라 값이 "
        "다릅니다(유니버스가 좁은 지수는 BTC 비중이 더 높게 나옵니다). 투자 권유가 아닙니다."
    ),
    "en": (
        "Dominance and total market cap are as aggregated by CoinMarketCap's universe; other "
        "publishers with narrower universes report different numbers. Not a recommendation."
    ),
}

_METHOD = {
    "ko": (
        "BTC·ETH 도미넌스와 총시총은 CoinMarketCap 값 그대로, '기타' = 100 − BTC − ETH(산술). 스테이블코인 비중 = 스테이블코인 시총 ÷ "
        "총시총(산술), USDT·USDC 유통 공급은 CoinMarketCap circulating supply 값 그대로이며 7d·30d 변화는 Mulmit이 매일 저장한 값으로 "
        "계산합니다(수집 시작일 표시, 과거치 발명 없음)."
    ),
    "en": (
        "BTC/ETH dominance and total market cap as published by CoinMarketCap; 'others' = 100 − BTC − ETH (arithmetic). Stablecoin "
        "share = stablecoin market cap ÷ total market cap (arithmetic); USDT/USDC circulating supply as published, with 7d/30d changes "
        "computed from Mulmit's own daily snapshots (start date shown, never back-filled)."
    ),
}


def build_crypto_structure(now: dt.datetime | None = None) -> dict[str, Any]:
    if not serving_enabled():
        raise CryptoStructureUnavailable("disabled")
    blob = _load_blob()
    metrics = blob.get("metrics") if isinstance(blob, dict) else None
    if not isinstance(metrics, dict) or metrics.get("btc_dominance") is None:
        raise CryptoStructureUnavailable("collecting")

    moment = now or dt.datetime.now(dt.UTC)
    fetched_at = _parse_iso(blob.get("fetched_at"))
    age = (moment - fetched_at).total_seconds() if fetched_at else None
    btc = float(metrics["btc_dominance"])
    eth = metrics.get("eth_dominance")
    others = None if eth is None else round(100.0 - btc - float(eth), 4)
    attribution_text = config.CMC_ATTRIBUTION_TEXT

    return {
        "generated_at": _iso_utc(),
        "as_of": metrics.get("as_of"),
        "dominance": {
            "btc_percent": _round(btc, 4),
            "eth_percent": _round(eth, 4),
            "others_percent": others,
            "btc_24h_change_points": _round(metrics.get("btc_dominance_24h_change_points"), 4),
            "eth_24h_change_points": _round(metrics.get("eth_dominance_24h_change_points"), 4),
            "btc_yesterday_percent": _round(metrics.get("btc_dominance_yesterday"), 4),
            "basis": "share of total crypto market cap, CoinMarketCap universe",
        },
        "market_cap": {
            "total_usd": _round(metrics.get("total_market_cap_usd"), 2),
            "total_24h_change_percent": _round(metrics.get("total_market_cap_24h_change_percent"), 4),
            "altcoin_usd": _round(metrics.get("altcoin_market_cap_usd"), 2),
            "stablecoin_usd": _round(metrics.get("stablecoin_market_cap_usd"), 2),
            "stablecoin_24h_change_percent": _round(metrics.get("stablecoin_24h_change_percent"), 4),
            "defi_usd": _round(metrics.get("defi_market_cap_usd"), 2),
        },
        "volume_24h": {
            "total_usd": _round(metrics.get("total_volume_24h_usd"), 2),
            "change_percent": _round(metrics.get("total_volume_24h_change_percent"), 4),
        },
        "universe": {
            "active_cryptocurrencies": metrics.get("active_cryptocurrencies"),
            "active_exchanges": metrics.get("active_exchanges"),
        },
        "stablecoins": _stablecoin_block(metrics, _load_cached(STABLE_CACHE_KEY, SERVE_TTL_SECONDS), moment),
        "freshness": {
            "status": "stale" if age is None or age > STALE_AFTER_SECONDS else "fresh",
            "fetched_at": blob.get("fetched_at"),
            "age_seconds": round(age, 1) if age is not None else None,
            "cadence": f"ingest refresh every {config.CMC_MAX_AGE}s; publisher updates about every minute",
            "stale_after_seconds": STALE_AFTER_SECONDS,
        },
        "attribution": {
            "text": attribution_text,
            "url": CMC_SITE_URL,
            "placement": "adjacent_to_value",
            "required": True,
            "terms_url": CMC_COMMERCIAL_TERMS_URL,
        },
        "source": {
            "provider": CMC_PROVIDER_ID,
            "provider_name": CMC_PUBLISHER,
            "publisher": CMC_PUBLISHER,
            "url": CMC_SITE_URL,
            "api_url": CMC_GLOBAL_METRICS_URL,
            "quotes_api_url": CMC_QUOTES_URL,
            "documentation_url": CMC_DOCS_URL,
            "read_path": "stored_blob",
        },
        "rights": {
            "status": "provider_terms_apply",
            "evidence": CMC_PRICING_QUOTE,
            "pricing_url": CMC_PRICING_URL,
            "terms_url": CMC_COMMERCIAL_TERMS_URL,
            "notice": (
                "Relayed under CoinMarketCap's Commercial Terms as accepted by the operator at "
                "key issuance; attribution shown next to the values; no standalone redistribution."
            ),
        },
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
    }
