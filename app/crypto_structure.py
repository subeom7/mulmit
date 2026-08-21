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
    CMC_SITE_URL,
    CoinMarketCapProvider,
)

CACHE_KEY = "crypto_global_metrics_v1"
SERVE_TTL_SECONDS = 60 * 60 * 12
STALE_AFTER_SECONDS = 60 * 60 * 2
LOAD_CACHE_SECONDS = 60.0

_lock = threading.Lock()
_cache: tuple[float, dict[str, Any] | None] | None = None


class CryptoStructureUnavailable(Exception):
    """``reason`` is ``disabled`` or ``collecting``; the route maps it to a 503 contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def serving_enabled() -> bool:
    return data_rights.cmc_serving_enabled()


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


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


def _load_blob() -> dict[str, Any] | None:
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache is not None and _cache[0] > now:
            return _cache[1]
    blob = store.load_report(CACHE_KEY, SERVE_TTL_SECONDS)
    with _lock:
        _cache = (now + LOAD_CACHE_SECONDS, blob)
    return blob


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
    "ko": "BTC·ETH 도미넌스와 총시총은 CoinMarketCap 값 그대로, '기타' = 100 − BTC − ETH(산술).",
    "en": "BTC/ETH dominance and total market cap as published by CoinMarketCap; 'others' = 100 − BTC − ETH (arithmetic).",
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
