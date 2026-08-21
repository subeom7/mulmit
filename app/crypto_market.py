"""Crypto section lanes — Phase 1 (see docs/PLAN_CRYPTO_SECTION.md).

Three endpoints share this module and each keeps the rights posture of the
data it relays:

* ``build_crypto_overview`` — Hyperliquid's own perpetuals (BTC, ETH, SOL …):
  mark/oracle price, the 24h reference change, hourly funding (annualised), open
  interest, notional volume, the venue-by-venue *predicted* funding that
  Hyperliquid publishes for its own book and for Binance/Bybit, and the ETH/BTC
  ratio.  One ``metaAndAssetCtxs`` call plus one ``predictedFundings`` call,
  both behind the provider's TTL cache.  Same gate and the same "synthetic
  perpetual, not a spot quote" posture as the HIP-3 asset cards.

* ``build_crypto_sentiment`` — the alternative.me Crypto Fear & Greed Index,
  relayed from a blob the ingest lane stores.  The request path never calls the
  publisher.  The payload carries the attribution the publisher's terms require
  "right next to the display of the data".

* ``build_crypto_volatility`` — realized volatility and BTC-versus-synthetic-
  asset correlations computed only from daily closes the HIP-3 history lane
  already stores.  Derived numbers, no new provider, no implied volatility.

Nothing here reads Binance, Bybit, OKX, Coinbase, Deribit or any other venue
directly: their terms forbid public redisplay without written consent
(docs/PLAN_CRYPTO_SECTION.md §3).  The Binance/Bybit numbers that do appear are
Hyperliquid's own published predictions and are labelled as relayed by it.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from . import config, data_rights, hip3_history, store
from .market_assets import realized_volatility_series
from .providers.alternative_me import (
    ALTERNATIVE_ME_API_URL,
    ALTERNATIVE_ME_ATTRIBUTION,
    ALTERNATIVE_ME_INDEX_NAME,
    ALTERNATIVE_ME_INDEX_URL,
    ALTERNATIVE_ME_PROVIDER_ID,
    ALTERNATIVE_ME_PUBLISHER,
    ALTERNATIVE_ME_TERMS_ACCESSED,
    ALTERNATIVE_ME_TERMS_QUOTE,
    COMPONENTS,
    AlternativeMeProvider,
    classification_label,
)
from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import (
    API_URL,
    HYPERLIQUID_INFO_DOCS,
    HYPERLIQUID_PERP_DOCS,
    MAIN_DEX,
    PREDICTED_FUNDING_REQUEST_TYPE,
    REQUEST_TYPE,
    HyperliquidProvider,
)

# --- Hyperliquid native perpetuals ------------------------------------------

OVERVIEW_CACHE_TTL_SECONDS = 15.0
OVERVIEW_STALE_TTL_SECONDS = 300.0
# Hyperliquid funding is paid hourly; the annualised figure is rate × 24 × 365.
FUNDING_INTERVAL_HOURS = 1
HOURS_PER_YEAR = 24 * 365
# Editorial bands for the funding "heat" badge, in annualised percent. Stated
# in the payload so a reader can disagree with the threshold, not the number.
FUNDING_HEAT_ELEVATED_APR = 15.0
FUNDING_HEAT_HIGH_APR = 30.0

VENUE_LABELS: dict[str, dict[str, str]] = {
    "HlPerp": {"ko": "Hyperliquid", "en": "Hyperliquid"},
    "BinPerp": {"ko": "Binance 퍼프 (Hyperliquid 전달값)", "en": "Binance perp (as relayed by Hyperliquid)"},
    "BybitPerp": {"ko": "Bybit 퍼프 (Hyperliquid 전달값)", "en": "Bybit perp (as relayed by Hyperliquid)"},
}


@dataclass(frozen=True)
class CoinSpec:
    symbol: str
    label_ko: str
    label_en: str


# Hyperliquid's own listings, no HIP-3 prefix. The roster is fixed so a symbol
# that Hyperliquid delists simply goes missing — it is never swapped for another.
COIN_SPECS: tuple[CoinSpec, ...] = (
    CoinSpec("BTC", "비트코인", "Bitcoin"),
    CoinSpec("ETH", "이더리움", "Ethereum"),
    CoinSpec("SOL", "솔라나", "Solana"),
    CoinSpec("XRP", "리플 (XRP)", "XRP"),
    CoinSpec("BNB", "BNB", "BNB"),
    CoinSpec("DOGE", "도지코인", "Dogecoin"),
    CoinSpec("HYPE", "하이퍼리퀴드 (HYPE)", "Hyperliquid (HYPE)"),
    CoinSpec("SUI", "수이", "Sui"),
    CoinSpec("LINK", "체인링크", "Chainlink"),
    CoinSpec("AVAX", "아발란체", "Avalanche"),
)
# Coins whose daily closes the history lane also stores, for realized volatility
# and the cross-market correlations.
HISTORY_COINS: tuple[str, ...] = ("BTC", "ETH", "SOL")


def coin_symbols() -> list[str]:
    return [spec.symbol for spec in COIN_SPECS]


def history_symbols() -> list[str]:
    """Symbols the HIP-3 history lane should add while the crypto section is on."""
    return list(HISTORY_COINS) if config.CRYPTO_SECTION_ENABLED else []


class OverviewProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...

    def fetch_predicted_fundings(self) -> dict[str, Any]: ...


_DEFAULT_PROVIDER = HyperliquidProvider(
    timeout=2.5,
    retries=0,
    max_request_seconds=3.0,
    ttl=OVERVIEW_CACHE_TTL_SECONDS,
    stale_ttl=OVERVIEW_STALE_TTL_SECONDS,
)


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _liquidity_status(volume: float | None) -> str:
    if volume is None or volume <= 0:
        return "unavailable"
    if volume >= 1_000_000:
        return "high"
    if volume >= 100_000:
        return "medium"
    return "low"


def annualize_funding(rate: float | None, interval_hours: float | None) -> float | None:
    """Funding per interval → annualised percent. ``None`` when either input is missing."""
    if rate is None or interval_hours is None or interval_hours <= 0:
        return None
    return rate * (HOURS_PER_YEAR / interval_hours) * 100.0


def funding_heat(apr_percent: float | None) -> str | None:
    if apr_percent is None:
        return None
    magnitude = abs(apr_percent)
    if magnitude >= FUNDING_HEAT_HIGH_APR:
        return "high"
    if magnitude >= FUNDING_HEAT_ELEVATED_APR:
        return "elevated"
    return "normal"


def funding_side(rate: float | None) -> str | None:
    if rate is None:
        return None
    if rate > 0:
        return "longs_pay"
    if rate < 0:
        return "shorts_pay"
    return "balanced"


_RIGHTS = {
    "status": "provider_terms_apply",
    "notice": (
        "Public API availability does not itself grant redistribution rights. "
        "Hyperliquid terms may apply; these are perpetual-futures references on "
        "Hyperliquid's own venue, not spot-exchange quotes or recommendations."
    ),
    "notice_localized": {
        "ko": (
            "공개 API 조회 가능 여부가 재배포 권리를 보장하지 않습니다. Hyperliquid 약관이 "
            "적용될 수 있으며, 표시값은 Hyperliquid 자체 무기한선물의 참고값으로 현물 거래소 "
            "호가나 투자 권유가 아닙니다."
        ),
        "en": (
            "Public API availability does not itself grant redistribution rights. "
            "Hyperliquid terms may apply; values are references from Hyperliquid's own "
            "perpetual futures, not spot-exchange quotes or recommendations."
        ),
    },
}


def _predicted_for(predicted: dict[str, Any] | None, symbol: str) -> list[dict[str, Any]]:
    if not predicted or not isinstance(predicted.get("coins"), dict):
        return []
    rows = predicted["coins"].get(symbol)
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        venue = str(row.get("venue") or "")
        rate = _number(row.get("funding_rate"))
        interval = _number(row.get("interval_hours"))
        apr = annualize_funding(rate, interval)
        result.append(
            {
                "venue": venue,
                "label": VENUE_LABELS.get(venue, {"ko": venue, "en": venue}),
                "funding_rate": rate,
                "funding_percent": _round(rate * 100.0, 6) if rate is not None else None,
                "interval_hours": interval,
                "apr_percent": _round(apr, 3),
                "next_funding_at": row.get("next_funding_at"),
                # Hyperliquid publishes these; Mulmit does not query the named venues.
                "relayed_by": "Hyperliquid",
                "relay_basis": (
                    "Hyperliquid info `predictedFundings`; values for other venues are "
                    "Hyperliquid's published predictions, not Mulmit queries of those venues"
                ),
            }
        )
    return result


def _coin_card(
    spec: CoinSpec,
    market: dict[str, Any],
    snapshot: dict[str, Any],
    predicted: dict[str, Any] | None,
) -> dict[str, Any] | None:
    metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
    if metadata.get("isDelisted") is True:
        return None
    context = market.get("context") if isinstance(market.get("context"), dict) else {}
    mark = _number(context.get("markPx"))
    oracle = _number(context.get("oraclePx"))
    mid = _number(context.get("midPx"))
    price = mark if mark is not None else oracle
    if price is None:
        return None
    price_field = "markPx" if mark is not None else "oraclePx_fallback"

    previous = _number(context.get("prevDayPx"))
    change_value = change_percent = None
    if previous is not None:
        change_value = price - previous
        if previous != 0:
            change_percent = change_value / previous * 100.0

    volume = _number(context.get("dayNtlVlm"))
    funding = _number(context.get("funding"))
    open_interest = _number(context.get("openInterest"))
    premium = _number(context.get("premium"))
    apr = annualize_funding(funding, FUNDING_INTERVAL_HOURS)
    stale = bool(snapshot.get("stale"))
    as_of = snapshot.get("as_of") or snapshot.get("fetched_at")

    return {
        "id": spec.symbol.lower(),
        "symbol": spec.symbol,
        "label": {"ko": spec.label_ko, "en": spec.label_en},
        "status": "stale" if stale else "fresh",
        "price": {
            "value": price,
            "mark": mark,
            "oracle": oracle,
            "mid": mid,
            "field": price_field,
            "currency": "USD",
            "basis": "Hyperliquid markPx (oracle fallback); oraclePx is Hyperliquid's external spot reference",
        },
        "change_24h": {
            "value": _round(change_value, 6),
            "percent": _round(change_percent, 4),
            "reference": previous,
            "basis": "current price versus Hyperliquid prevDayPx (rolling 24h reference)",
        },
        "funding": {
            "hourly_rate": funding,
            "hourly_percent": _round(funding * 100.0, 6) if funding is not None else None,
            "apr_percent": _round(apr, 3),
            "interval_hours": FUNDING_INTERVAL_HOURS,
            "side": funding_side(funding),
            "heat": funding_heat(apr),
            "basis": (
                "Hyperliquid hourly funding, annualised as rate × 24 × 365; positive means "
                "longs pay shorts. Heat bands: |APR| ≥ "
                f"{FUNDING_HEAT_ELEVATED_APR:g}% elevated, ≥ {FUNDING_HEAT_HIGH_APR:g}% high"
            ),
        },
        "predicted_funding": _predicted_for(predicted, spec.symbol),
        "open_interest": {
            "base_units": open_interest,
            "usd": _round(open_interest * price, 2) if open_interest is not None else None,
            "basis": "Hyperliquid openInterest in coin units × current price",
        },
        "volume_24h_usd": volume,
        "premium_percent": _round(premium * 100.0, 4) if premium is not None else None,
        "liquidity_status": _liquidity_status(volume),
        "source": {
            "provider": "Hyperliquid",
            "publisher": "Hyperliquid",
            "venue": MAIN_DEX,
            "url": f"https://app.hyperliquid.xyz/trade/{quote(spec.symbol)}",
            "api_url": API_URL,
            "documentation_url": HYPERLIQUID_PERP_DOCS,
            "market_symbol": spec.symbol,
            "instrument_type": "perpetual future (Hyperliquid native listing)",
            "price_field": price_field,
        },
        "freshness": {
            "status": "stale" if stale else "fresh",
            "as_of": as_of,
            "as_of_basis": "Hyperliquid response fetch time; contexts carry no per-market timestamp",
            "age_seconds": _number(snapshot.get("age_seconds")),
            "max_age_seconds": OVERVIEW_CACHE_TTL_SECONDS,
            "stale_if_error_seconds": OVERVIEW_STALE_TTL_SECONDS,
            "cached": bool(snapshot.get("cached")),
        },
        "rights": _RIGHTS,
    }


def _ratio(numerator: dict[str, Any] | None, denominator: dict[str, Any] | None) -> dict[str, Any] | None:
    """ETH/BTC from the two oracle prices — arithmetic on displayed values only."""
    if not numerator or not denominator:
        return None
    top = _number(numerator["price"].get("oracle")) or _number(numerator["price"].get("value"))
    bottom = _number(denominator["price"].get("oracle")) or _number(denominator["price"].get("value"))
    if top is None or bottom in (None, 0):
        return None
    ratio = top / bottom
    prev_top = _number(numerator["change_24h"].get("reference"))
    prev_bottom = _number(denominator["change_24h"].get("reference"))
    change_percent = None
    if prev_top is not None and prev_bottom not in (None, 0):
        previous_ratio = prev_top / prev_bottom
        if previous_ratio:
            change_percent = (ratio / previous_ratio - 1.0) * 100.0
    return {
        "id": "eth_btc",
        "pair": f"{numerator['symbol']}/{denominator['symbol']}",
        "value": round(ratio, 8),
        "change_24h_percent": _round(change_percent, 4),
        "basis": (
            "oraclePx(ETH) ÷ oraclePx(BTC) on Hyperliquid, 24h change from the same ratio of "
            "prevDayPx values; derived, not a quoted pair"
        ),
    }


def _overview_provider_block(snapshot: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    snapshot = snapshot or {}
    as_of = snapshot.get("as_of") or snapshot.get("fetched_at")
    return {
        "id": "hyperliquid",
        "name": "Hyperliquid",
        "url": HYPERLIQUID_INFO_DOCS,
        "api_url": API_URL,
        "read_path": "live_public_info_only",
        "request_types": [REQUEST_TYPE, PREDICTED_FUNDING_REQUEST_TYPE],
        "dex": MAIN_DEX,
        "cached": bool(snapshot.get("cached")),
        "stale": bool(snapshot.get("stale")),
        "age_seconds": _number(snapshot.get("age_seconds")),
        "ttl_seconds": OVERVIEW_CACHE_TTL_SECONDS,
        "stale_if_error_seconds": OVERVIEW_STALE_TTL_SECONDS,
        "as_of": as_of,
        "as_of_basis": "Hyperliquid response fetch time",
        "error": error if error is not None else snapshot.get("error"),
    }


_OVERVIEW_DISCLAIMER = {
    "ko": (
        "표시값은 Hyperliquid 자체 DEX에 상장된 무기한선물의 참고값입니다. 현물 거래소 가격, "
        "원화 시세, 투자 권유가 아니며 유동성이 낮은 시장은 왜곡될 수 있습니다. Binance·Bybit "
        "예상 펀딩은 Hyperliquid가 공표하는 전달값이고 Mulmit은 해당 거래소를 조회하지 않습니다."
    ),
    "en": (
        "Values are references from perpetual futures listed on Hyperliquid's own DEX — not "
        "spot-exchange prices, KRW quotes or recommendations; thin markets can be distorted. "
        "Binance/Bybit predicted funding is Hyperliquid's published relay; Mulmit does not query "
        "those venues."
    ),
}

_OVERVIEW_METHOD = {
    "ko": (
        "가격 = markPx(없으면 oraclePx), 24h = prevDayPx 대비, 펀딩 APR = 시간당 펀딩 × 24 × 365, "
        "OI(USD) = openInterest × 가격, ETH/BTC = 두 오라클가의 비율. 전부 표시값의 산술 파생입니다."
    ),
    "en": (
        "Price = markPx (oraclePx fallback); 24h versus prevDayPx; funding APR = hourly funding × 24 "
        "× 365; OI (USD) = openInterest × price; ETH/BTC = ratio of the two oracle prices. All "
        "arithmetic on displayed values."
    ),
}


def _empty_overview(error: str) -> dict[str, Any]:
    return {
        "generated_at": _iso_utc(),
        "as_of": None,
        "provider": _overview_provider_block(None, error),
        "venues": VENUE_LABELS,
        "coins": [],
        "missing": coin_symbols(),
        "eth_btc": None,
        "coverage": {"available": 0, "total": len(COIN_SPECS), "ratio": 0.0},
        "methodology": _OVERVIEW_METHOD,
        "disclaimer": _OVERVIEW_DISCLAIMER,
        "rights": _RIGHTS,
    }


def build_crypto_overview(provider: OverviewProvider | None = None) -> dict[str, Any]:
    """One Hyperliquid main-venue snapshot plus its predicted-funding table."""
    client = provider or _DEFAULT_PROVIDER
    try:
        snapshot = client.fetch_dex(MAIN_DEX)
    except RateLimited:
        return _empty_overview("rate_limited")
    except DataUnavailable:
        return _empty_overview("unavailable")

    predicted: dict[str, Any] | None
    try:
        predicted = client.fetch_predicted_fundings()
    except (RateLimited, DataUnavailable):
        # Predicted funding is an enrichment; its outage costs only that column.
        predicted = None

    markets: dict[str, dict[str, Any]] = {}
    for market in snapshot.get("markets") or []:
        if isinstance(market, dict) and isinstance(market.get("symbol"), str):
            markets[market["symbol"].strip().casefold()] = market

    coins: list[dict[str, Any]] = []
    missing: list[str] = []
    for spec in COIN_SPECS:
        market = markets.get(spec.symbol.casefold())
        card = _coin_card(spec, market, snapshot, predicted) if market else None
        if card is None:
            missing.append(spec.symbol)
            continue
        coins.append(card)
    by_symbol = {card["symbol"]: card for card in coins}

    return {
        "generated_at": _iso_utc(),
        "as_of": snapshot.get("as_of") or snapshot.get("fetched_at"),
        "provider": _overview_provider_block(snapshot, None),
        "predicted_funding": {
            "status": "ok" if predicted else "unavailable",
            "as_of": (predicted or {}).get("as_of"),
            "basis": (
                "Hyperliquid `predictedFundings`: next-interval funding per venue with its "
                "interval; APR = rate × (24 ÷ interval hours) × 365"
            ),
        },
        "venues": VENUE_LABELS,
        "coins": coins,
        "missing": missing,
        "eth_btc": _ratio(by_symbol.get("ETH"), by_symbol.get("BTC")),
        "coverage": {
            "available": len(coins),
            "total": len(COIN_SPECS),
            "ratio": round(len(coins) / len(COIN_SPECS), 4),
        },
        "methodology": _OVERVIEW_METHOD,
        "disclaimer": _OVERVIEW_DISCLAIMER,
        "rights": _RIGHTS,
    }


# --- alternative.me Crypto Fear & Greed -------------------------------------

SENTIMENT_CACHE_KEY = "crypto_fear_greed_v1"
# The index is daily; a stored blob keeps serving for two days if the lane
# stalls, and the UI says when it is stale.
SENTIMENT_SERVE_TTL_SECONDS = 60 * 60 * 48
SENTIMENT_STALE_AFTER_SECONDS = 60 * 60 * 30
SENTIMENT_HISTORY_DAYS = 366
SENTIMENT_CHART_DAYS = 90
LOAD_CACHE_SECONDS = 60.0

_sentiment_lock = threading.Lock()
_sentiment_cache: tuple[float, dict[str, Any] | None] | None = None


class CryptoSentimentUnavailable(Exception):
    """Raised with ``reason`` = ``disabled`` or ``collecting``; the route maps it to 503."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def sentiment_enabled() -> bool:
    return data_rights.alternative_me_serving_enabled()


def clear_sentiment_cache() -> None:
    global _sentiment_cache
    with _sentiment_lock:
        _sentiment_cache = None


def refresh_crypto_sentiment(
    *,
    force: bool = False,
    provider: Any | None = None,
) -> dict[str, Any]:
    """Ingest lane: fetch the daily index history and store one blob.

    Skipped entirely while the lane is off (zero network calls), and skipped
    while the stored blob is younger than ``ALTERNATIVE_ME_MAX_AGE``.  A failed
    fetch leaves the previous blob in place.
    """
    if not sentiment_enabled():
        return {"skipped": "disabled"}
    if not force and store.load_report(SENTIMENT_CACHE_KEY, config.ALTERNATIVE_ME_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or AlternativeMeProvider(
        timeout=config.ALTERNATIVE_ME_TIMEOUT,
        retries=config.ALTERNATIVE_ME_RETRIES,
    )
    snapshot = client.fetch_fear_greed(limit=SENTIMENT_HISTORY_DAYS + 7)
    observations = snapshot.get("observations") or []
    if not observations:
        raise DataUnavailable("alternative.me returned an empty index history")
    store.save_report(
        SENTIMENT_CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": snapshot.get("fetched_at"),
            "index_name": snapshot.get("index_name") or ALTERNATIVE_ME_INDEX_NAME,
            "next_update_in_seconds": snapshot.get("next_update_in_seconds"),
            "observations": observations[-SENTIMENT_HISTORY_DAYS:],
        },
    )
    clear_sentiment_cache()
    return {"updated": 1, "observations": len(observations)}


def _load_sentiment_blob() -> dict[str, Any] | None:
    global _sentiment_cache
    now = time.monotonic()
    with _sentiment_lock:
        if _sentiment_cache is not None and _sentiment_cache[0] > now:
            return _sentiment_cache[1]
    blob = store.load_report(SENTIMENT_CACHE_KEY, SENTIMENT_SERVE_TTL_SECONDS)
    with _sentiment_lock:
        _sentiment_cache = (now + LOAD_CACHE_SECONDS, blob)
    return blob


def _parse_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _observation_on_or_before(rows: list[dict[str, Any]], date: dt.date) -> dict[str, Any] | None:
    target = date.isoformat()
    candidate = None
    for row in rows:
        if str(row.get("date", "")) <= target:
            candidate = row
        else:
            break
    return candidate


_SENTIMENT_DISCLAIMER = {
    "ko": (
        "alternative.me가 산출·발표하는 지수를 그대로 전달합니다(일 1회, 00:00 UTC). 비트코인 중심의 "
        "지표이며 Mulmit 시장 심리 게이지나 CNN 공포·탐욕 지수와 정의가 달라 수치를 직접 비교할 수 "
        "없습니다. 투자 권유가 아닙니다."
    ),
    "en": (
        "Relayed as published by alternative.me (daily, 00:00 UTC). The index is bitcoin-centric "
        "and is defined differently from Mulmit's own sentiment gauge and CNN's equity index, so "
        "the numbers are not directly comparable. Not a recommendation."
    ),
}


def build_crypto_sentiment(now: dt.datetime | None = None) -> dict[str, Any]:
    """Serve the stored index with 1d/7d/30d changes and the required attribution."""
    if not sentiment_enabled():
        raise CryptoSentimentUnavailable("disabled")
    blob = _load_sentiment_blob()
    rows = blob.get("observations") if isinstance(blob, dict) else None
    if not isinstance(rows, list) or not rows:
        raise CryptoSentimentUnavailable("collecting")
    rows = [row for row in rows if isinstance(row, dict) and _number(row.get("value")) is not None]
    rows.sort(key=lambda row: str(row.get("date", "")))
    if not rows:
        raise CryptoSentimentUnavailable("collecting")

    moment = now or dt.datetime.now(dt.UTC)
    latest = rows[-1]
    latest_date = dt.date.fromisoformat(str(latest["date"]))
    previous = _observation_on_or_before(rows, latest_date - dt.timedelta(days=1))
    week_ago = _observation_on_or_before(rows, latest_date - dt.timedelta(days=7))
    month_ago = _observation_on_or_before(rows, latest_date - dt.timedelta(days=30))
    latest_value = int(latest["value"])

    def delta(reference: dict[str, Any] | None) -> dict[str, Any] | None:
        if reference is None or reference is latest:
            return None
        return {
            "date": reference["date"],
            "value": int(reference["value"]),
            "classification": classification_label(reference.get("classification")),
            "change_points": latest_value - int(reference["value"]),
        }

    fetched_at = _parse_iso(blob.get("fetched_at"))
    next_update_in = blob.get("next_update_in_seconds")
    next_update_at = None
    if fetched_at is not None and isinstance(next_update_in, int):
        next_update_at = (fetched_at + dt.timedelta(seconds=next_update_in)).isoformat().replace("+00:00", "Z")
    age_seconds = (moment - fetched_at).total_seconds() if fetched_at is not None else None
    stale = age_seconds is None or age_seconds > SENTIMENT_STALE_AFTER_SECONDS

    chart_cutoff = (latest_date - dt.timedelta(days=SENTIMENT_CHART_DAYS)).isoformat()
    observations = [
        {"date": row["date"], "value": int(row["value"]), "classification": row.get("classification")}
        for row in rows
        if str(row.get("date", "")) >= chart_cutoff
    ]

    return {
        "generated_at": _iso_utc(),
        "index": blob.get("index_name") or ALTERNATIVE_ME_INDEX_NAME,
        "as_of": latest["date"],
        "timestamp": latest.get("timestamp"),
        "value": latest_value,
        "classification": classification_label(latest.get("classification")),
        "classification_raw": latest.get("classification"),
        "previous": delta(previous),
        "week_ago": delta(week_ago),
        "month_ago": delta(month_ago),
        "scale": {"min": 0, "max": 100, "low_label": {"ko": "극단적 공포", "en": "Extreme fear"},
                  "high_label": {"ko": "극단적 탐욕", "en": "Extreme greed"}},
        "next_update_at": next_update_at,
        "observations": observations,
        "observation_count": {"available": len(rows), "returned": len(observations)},
        "freshness": {
            "status": "stale" if stale else "fresh",
            "fetched_at": blob.get("fetched_at"),
            "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
            "cadence": "publisher updates daily at 00:00 UTC; Mulmit polls hourly",
            "stale_after_seconds": SENTIMENT_STALE_AFTER_SECONDS,
        },
        "components": [dict(component) for component in COMPONENTS],
        "attribution": {
            "text": ALTERNATIVE_ME_ATTRIBUTION,
            "url": ALTERNATIVE_ME_INDEX_URL,
            "placement": "adjacent_to_value",
            "required": True,
            "terms_quote": ALTERNATIVE_ME_TERMS_QUOTE,
            "terms_url": ALTERNATIVE_ME_INDEX_URL,
            "terms_accessed": ALTERNATIVE_ME_TERMS_ACCESSED,
        },
        "source": {
            "provider": ALTERNATIVE_ME_PROVIDER_ID,
            "provider_name": ALTERNATIVE_ME_PUBLISHER,
            "publisher": ALTERNATIVE_ME_PUBLISHER,
            "url": ALTERNATIVE_ME_INDEX_URL,
            "api_url": ALTERNATIVE_ME_API_URL,
            "read_path": "stored_daily_blob",
        },
        "rights": {
            "status": "approved",
            "evidence": "official_terms",
            "notice": (
                f"{ALTERNATIVE_ME_INDEX_NAME} © alternative.me, relayed under the publisher's "
                "stated terms: commercial use allowed with attribution right next to the data."
            ),
            "terms_quote": ALTERNATIVE_ME_TERMS_QUOTE,
            "terms_url": ALTERNATIVE_ME_INDEX_URL,
            "terms_accessed": ALTERNATIVE_ME_TERMS_ACCESSED,
        },
        "disclaimer": _SENTIMENT_DISCLAIMER,
    }


# --- Realized volatility and cross-market correlation -----------------------

REALIZED_VOL_WINDOWS: tuple[int, ...] = (7, 30)
# Perpetuals trade every calendar day, so crypto volatility is annualised by
# √365 rather than the √252 used for the equity-index perps elsewhere.
CRYPTO_ANNUALIZATION_DAYS = 365
CORRELATION_WINDOWS: tuple[int, ...] = (30, 90)
CORRELATION_MIN_POINTS = 20
CORRELATION_PEERS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("xyz:SP500", "sp500", {"ko": "S&P 500 퍼프", "en": "S&P 500 perp"}),
    ("xyz:XYZ100", "nasdaq", {"ko": "XYZ100 퍼프 (나스닥 대용)", "en": "XYZ100 perp (Nasdaq proxy)"}),
    ("xyz:GOLD", "gold", {"ko": "금 퍼프", "en": "Gold perp"}),
    ("xyz:KR200", "kospi", {"ko": "KR200 퍼프 (코스피 200 대용)", "en": "KR200 perp (KOSPI 200 proxy)"}),
)

_VOLATILITY_BASIS = {
    "ko": (
        "Hyperliquid 일봉 종가(UTC)의 로그수익률 표본표준편차 × √365(연율화, %). 마지막 봉은 진행 "
        "중인 날입니다. 이미 일어난 변동의 크기이며 옵션 내재변동성(DVOL 등)이 아닙니다. 상관은 "
        "같은 날짜의 일간 로그수익률 피어슨 상관이며 인과관계가 아닙니다."
    ),
    "en": (
        "Sample standard deviation of daily log returns on Hyperliquid daily closes (UTC) × √365, "
        "in percent; the last bar is the running day. Realized, not implied (not DVOL). "
        "Correlations are Pearson on same-date daily log returns and are not causation."
    ),
}


def _closes(blob: dict[str, Any] | None, symbol: str) -> list[tuple[str, float]]:
    rows, _available = hip3_history.observations_for(blob, symbol, days=None, limit=0)
    closes: list[tuple[str, float]] = []
    for row in rows:
        value = _number(row.get("value")) if isinstance(row, dict) else None
        date = str(row.get("date") or "") if isinstance(row, dict) else ""
        if value is not None and value > 0 and date:
            closes.append((date, value))
    return closes


def _log_returns(closes: list[tuple[str, float]]) -> dict[str, float]:
    returns: dict[str, float] = {}
    for index in range(1, len(closes)):
        returns[closes[index][0]] = math.log(closes[index][1] / closes[index - 1][1])
    return returns


def pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    try:
        return statistics.correlation(xs, ys)
    except (statistics.StatisticsError, ValueError, ZeroDivisionError):
        return None


def _realized_block(symbol: str, closes: list[tuple[str, float]]) -> dict[str, Any]:
    rows = [{"date": date, "value": value} for date, value in closes]
    windows: list[dict[str, Any]] = []
    for window in REALIZED_VOL_WINDOWS:
        series = realized_volatility_series(rows, window, CRYPTO_ANNUALIZATION_DAYS)
        if not series:
            windows.append({"window_days": window, "value": None, "as_of": None, "status": "insufficient_history"})
            continue
        latest = series[-1]
        previous = series[-2] if len(series) > 1 else None
        windows.append(
            {
                "window_days": window,
                "value": latest["value"],
                "as_of": latest["date"],
                "previous": previous,
                "status": "ok",
                "series": series[-SENTIMENT_CHART_DAYS:],
            }
        )
    return {"symbol": symbol, "windows": windows, "observations": len(closes)}


def _correlation_rows(base: dict[str, float], peer: dict[str, float]) -> list[dict[str, Any]]:
    shared = sorted(set(base) & set(peer))
    rows: list[dict[str, Any]] = []
    for window in CORRELATION_WINDOWS:
        dates = shared[-window:]
        if len(dates) < CORRELATION_MIN_POINTS:
            rows.append({"window_days": window, "value": None, "points": len(dates), "status": "insufficient_history"})
            continue
        value = pearson_correlation([base[d] for d in dates], [peer[d] for d in dates])
        rows.append(
            {
                "window_days": window,
                "value": None if value is None else round(value, 4),
                "points": len(dates),
                "from": dates[0],
                "to": dates[-1],
                "status": "ok" if value is not None else "undefined",
            }
        )
    return rows


def build_crypto_volatility() -> dict[str, Any]:
    """Derived-only: realized volatility per coin and BTC-vs-synthetic correlations."""
    generated_at = _iso_utc()
    if not hip3_history.enabled():
        return {
            "generated_at": generated_at,
            "status": hip3_history.STATUS_WITHHELD,
            "gate": "HIP3_HISTORY_ENABLED",
            "realized": [],
            "correlations": [],
            "basis": _VOLATILITY_BASIS,
            "rights": _RIGHTS,
        }
    blob = hip3_history.load()
    realized = []
    closes_by_symbol: dict[str, list[tuple[str, float]]] = {}
    for symbol in HISTORY_COINS:
        closes = _closes(blob, symbol)
        closes_by_symbol[symbol] = closes
        if closes:
            realized.append(_realized_block(symbol, closes))

    correlations = []
    base_returns = _log_returns(closes_by_symbol.get("BTC", []))
    if base_returns:
        for symbol, asset_id, label in CORRELATION_PEERS:
            peer_returns = _log_returns(_closes(blob, symbol))
            if not peer_returns:
                continue
            correlations.append(
                {
                    "base": "BTC",
                    "peer": symbol,
                    "peer_asset_id": asset_id,
                    "label": label,
                    "windows": _correlation_rows(base_returns, peer_returns),
                }
            )

    status = "ok" if realized or correlations else hip3_history.STATUS_COLLECTING
    return {
        "generated_at": generated_at,
        "status": status,
        "gate": "HIP3_HISTORY_ENABLED",
        "as_of": hip3_history.series_as_of(blob, "BTC"),
        "history_generated_at": (blob or {}).get("generated_at"),
        "annualization_days": CRYPTO_ANNUALIZATION_DAYS,
        "realized": realized,
        "correlations": correlations,
        "basis": _VOLATILITY_BASIS,
        "source": {
            "provider": "Hyperliquid",
            "publisher": "Hyperliquid / trade.xyz",
            "inputs": "candleSnapshot 1d closes stored by the HIP-3 history lane",
            "derived": True,
        },
        "rights": _RIGHTS,
    }
