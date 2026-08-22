"""Market-wide regime, and the cached half of every coin's regime read.

Two jobs, one module, because they share the same arithmetic:

* ``refresh_coin_price_parts`` (ingest) stores the candle-derived half of the
  regime read for the curated coins.  Funding moves minute to minute, so it is
  *not* stored — the request path scores it live against the card it is about to
  serve and composes the two halves.  That keeps the 5-second overview poll free
  of upstream candle calls while the badge it shows still reflects the funding
  the same card is displaying.
* ``build_crypto_regime`` reads the whole venue instead of one market: how many
  liquid markets are paying crowded funding, how many are up on the day, where
  the anchor coin's own regime sits, and what the sentiment lane says.

Everything is derived from lanes the section already relays (Hyperliquid
contexts and candles, alternative.me's index).  No new provider, no new right.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Any

from . import config, crypto_board, crypto_market, crypto_signal, data_rights, store
from .crypto_coin import parse_candles
from .crypto_market import _DEFAULT_PROVIDER, COIN_SPECS
from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import MAIN_DEX

log = logging.getLogger(__name__)

PRICE_PARTS_CACHE_KEY = "crypto_coin_price_parts_v1"
SERVE_TTL_SECONDS = 60 * 60 * 12
LOAD_CACHE_SECONDS = 60.0
REQUEST_GAP_SECONDS = 0.25

ANCHOR_SYMBOL = "BTC"
# A market is "crowded" when funding sits this far from Hyperliquid's baseline —
# the same 15pp step the coin-level funding scale calls half-hot.
CROWDED_EXCESS_APR = 15.0
# Share of liquid markets that are crowded → heat.  Anchored on the live
# distribution measured 2026-08-22 (110 liquid markets, 52% crowded on a day the
# whole market was up 7.5% at the median).
BREADTH_ANCHORS = ((0.0, 0.0), (0.15, 40.0), (0.35, 75.0), (0.60, 100.0))
MARKET_WEIGHTS = {"anchor": 0.35, "funding_breadth": 0.30, "sentiment": 0.20, "advance_breadth": 0.15}

_lock = threading.Lock()
_cache: tuple[float, dict[str, Any] | None] | None = None
_sleep = time.sleep


class RegimeUnavailable(Exception):
    """``reason`` is ``disabled`` or ``unavailable``; the route maps it to a 503."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None


# --- the cached (candle-derived) half of a coin's read ------------------------

def refresh_coin_price_parts(*, force: bool = False, provider: Any | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Ingest lane: one daily-candle window per curated coin, stored as scored components."""
    if not data_rights.crypto_overview_enabled():
        return {"skipped": "disabled"}
    if not force and store.load_report(PRICE_PARTS_CACHE_KEY, config.CRYPTO_HEAT_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or _DEFAULT_PROVIDER
    moment = now or dt.datetime.now(dt.UTC)
    start, end = crypto_signal.signal_window(moment)
    parts: dict[str, Any] = {}
    failed = 0
    for index, spec in enumerate(COIN_SPECS):
        if index and REQUEST_GAP_SECONDS > 0:
            _sleep(REQUEST_GAP_SECONDS)
        try:
            snapshot = client.fetch_candles(spec.symbol, interval=crypto_signal.SIGNAL_INTERVAL, start=start, end=end)
        except RateLimited:
            failed += 1
            log.warning("Hyperliquid rate limit — stopping the coin-heat pass after %d symbols", index)
            break
        except DataUnavailable as exc:
            failed += 1
            log.warning("coin heat for %s failed: %s", spec.symbol, exc)
            continue
        part = crypto_signal.price_components(parse_candles(snapshot.get("candles")))
        if part is None:
            continue
        part["as_of"] = snapshot.get("as_of") or snapshot.get("fetched_at")
        parts[spec.symbol] = part
    if not parts:
        raise DataUnavailable("coin heat refresh produced no usable series")
    store.save_report(PRICE_PARTS_CACHE_KEY, {"generated_at": _iso_utc(), "fetched_at": _iso_utc(), "parts": parts})
    clear_cache()
    return {"updated": len(parts), "failed": failed}


def coin_price_parts() -> dict[str, Any]:
    global _cache
    now = time.monotonic()
    with _lock:
        if _cache is not None and _cache[0] > now:
            return (_cache[1] or {}).get("parts") or {}
    blob = store.load_report(PRICE_PARTS_CACHE_KEY, SERVE_TTL_SECONDS)
    with _lock:
        _cache = (now + LOAD_CACHE_SECONDS, blob)
    return (blob or {}).get("parts") or {}


def attach_coin_signals(overview: dict[str, Any]) -> dict[str, Any]:
    """Add a compact regime badge to each tape card, composed with that card's live funding."""
    parts = coin_price_parts()
    if not parts:
        return overview
    for card in overview.get("coins") or []:
        part = parts.get(card.get("symbol"))
        if not isinstance(part, dict):
            continue
        apr = (card.get("funding") or {}).get("apr_percent")
        signal = crypto_signal.compose(part, crypto_signal.funding_component(apr), as_of=part.get("as_of"))
        if signal["status"] != "ok":
            continue
        card["signal"] = {
            "heat": signal["heat"]["score"],
            "band": signal["heat"]["band"],
            "label": signal["heat"]["label"],
            "direction": signal["direction"]["score"],
            "direction_band": signal["direction"]["band"],
            "as_of": part.get("as_of"),
            "url": f"/crypto/{card.get('symbol')}",
        }
    return overview


# --- the whole venue ----------------------------------------------------------

_METHOD = {
    "ko": (
        f"시장 과열도 = 기준 코인({ANCHOR_SYMBOL}) 자체 과열도 {MARKET_WEIGHTS['anchor']:.0%} + 펀딩 쏠림 폭 {MARKET_WEIGHTS['funding_breadth']:.0%} + "
        f"공포·탐욕 지수 {MARKET_WEIGHTS['sentiment']:.0%} + 24시간 상승 폭 {MARKET_WEIGHTS['advance_breadth']:.0%}입니다. 쏠림 폭은 24h 거래대금 "
        f"$1M 이상 시장 가운데 펀딩이 기준선(+{crypto_signal.FUNDING_BASELINE_APR:g}% APR)에서 {CROWDED_EXCESS_APR:g}%p 이상 벌어진 비율이며, "
        "비율 0→0, 15%→40, 35%→75, 60%→100의 구간 선형으로 환산합니다. 상승 폭은 같은 표본에서 24시간 상승한 시장의 비율입니다. "
        "구성요소가 없으면(예: 지수 수집 중) 남은 가중치로 재정규화합니다."
    ),
    "en": (
        f"Market heat = the anchor coin's own heat ({ANCHOR_SYMBOL}) {MARKET_WEIGHTS['anchor']:.0%} + funding-crowding breadth "
        f"{MARKET_WEIGHTS['funding_breadth']:.0%} + the Fear & Greed index {MARKET_WEIGHTS['sentiment']:.0%} + 24h advance breadth "
        f"{MARKET_WEIGHTS['advance_breadth']:.0%}. Breadth counts markets with at least $1M of 24h volume whose funding sits "
        f"{CROWDED_EXCESS_APR:g}pp or more from the +{crypto_signal.FUNDING_BASELINE_APR:g}% APR baseline, mapped 0→0, 15%→40, 35%→75, "
        "60%→100. Advance breadth is the share of that same sample up over 24 hours. Missing components (a collecting index, say) are "
        "dropped and the remaining weights renormalised."
    ),
}

_DISCLAIMER = {
    "ko": (
        "시장 상태를 요약한 지표이며 매수·매도 신호나 투자 자문이 아닙니다. 과열이 곧 하락을, 냉각이 곧 상승을 뜻하지 않습니다. "
        "표본은 Hyperliquid 자체 DEX에 상장된 무기한선물이며 크립토 시장 전체의 대표 표본이 아닙니다."
    ),
    "en": (
        "A summary of market conditions — not a buy or sell signal and not investment advice. Overheated does not imply a fall, nor cool a "
        "rise. The sample is the perpetuals listed on Hyperliquid's own DEX, not the whole crypto market."
    ),
}


def _reading(heat: float, heat_label: dict[str, str], direction_label: dict[str, str], components: list[dict[str, Any]]) -> dict[str, str]:
    ranked = sorted(
        (c for c in components if c["heat_score"] is not None and c["weight"]),
        key=lambda c: c["heat_score"] * c["weight"], reverse=True,
    )[:2]
    drivers_ko = ", ".join(f"{c['label']['ko']}({c['note']['ko']})" for c in ranked)
    drivers_en = ", ".join(f"{c['label']['en']} ({c['note']['en']})" for c in ranked)
    return {
        "ko": f"시장 {direction_label['ko']} · 과열도 {heat:.0f}/100 ({heat_label['ko']})"
              + (f" — 온도를 가장 많이 끌어올린 요인은 {drivers_ko}입니다." if drivers_ko else "."),
        "en": f"Market {direction_label['en']} · heat {heat:.0f}/100 ({heat_label['en']})"
              + (f" — driven mostly by {drivers_en}." if drivers_en else "."),
    }


def _sentiment_value() -> tuple[float | None, dict[str, Any]]:
    """The stored Fear & Greed reading, or ``None`` when that lane is off or still collecting."""
    try:
        payload = crypto_market.build_crypto_sentiment()
    except crypto_market.CryptoSentimentUnavailable as exc:
        return None, {"status": exc.reason}
    except Exception:  # noqa: BLE001 - sentiment is an input, never the reason the page fails
        log.warning("sentiment lookup failed for the market regime", exc_info=True)
        return None, {"status": "error"}
    value = (payload or {}).get("value")
    classification = (payload or {}).get("classification")
    if isinstance(classification, dict):
        classification = classification.get("ko") or classification.get("en")
    return (float(value) if isinstance(value, (int, float)) else None), {
        "status": "ok",
        "as_of": (payload or {}).get("as_of"),
        "classification": classification,
        "index": (payload or {}).get("index"),
        "attribution": ((payload or {}).get("attribution") or {}).get("text"),
    }


def build_crypto_regime(provider: Any | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """One venue-wide read: breadth, the anchor coin's regime, and the sentiment lane."""
    if not data_rights.crypto_overview_enabled():
        raise RegimeUnavailable("disabled")
    client = provider or _DEFAULT_PROVIDER
    try:
        snapshot = client.fetch_dex(MAIN_DEX)
    except RateLimited as exc:
        raise RegimeUnavailable("rate_limited") from exc
    except DataUnavailable as exc:
        raise RegimeUnavailable("unavailable") from exc

    rows = [row for row in (crypto_board._row(m) for m in snapshot.get("markets") or [] if isinstance(m, dict)) if row]
    liquid = [row for row in rows if (row.get("volume_24h_usd") or 0) >= crypto_board.MIN_VOLUME_USD]
    with_funding = [row for row in liquid if row.get("funding_apr_percent") is not None]
    crowded = [row for row in with_funding
               if abs(row["funding_apr_percent"] - crypto_signal.FUNDING_BASELINE_APR) >= CROWDED_EXCESS_APR]
    with_change = [row for row in liquid if row.get("change_24h_percent") is not None]
    advancing = [row for row in with_change if row["change_24h_percent"] > 0]

    crowded_share = (len(crowded) / len(with_funding)) if with_funding else None
    advance_share = (len(advancing) / len(with_change)) if with_change else None

    parts = coin_price_parts()
    anchor_part = parts.get(ANCHOR_SYMBOL)
    anchor_row = next((row for row in rows if row.get("symbol") == ANCHOR_SYMBOL), None)
    anchor_signal = None
    if isinstance(anchor_part, dict):
        anchor_signal = crypto_signal.compose(
            anchor_part,
            crypto_signal.funding_component((anchor_row or {}).get("funding_apr_percent")),
            as_of=anchor_part.get("as_of"),
        )
        if anchor_signal.get("status") != "ok":
            anchor_signal = None

    sentiment_value, sentiment_meta = _sentiment_value()

    components = [
        crypto_signal._component(
            "anchor", f"{ANCHOR_SYMBOL} 과열도", f"{ANCHOR_SYMBOL} heat",
            None if anchor_signal is None else anchor_signal["heat"]["score"],
            None if anchor_signal is None else anchor_signal["heat"]["score"],
            "—" if anchor_signal is None else f"{anchor_signal['heat']['label']['ko']} · {anchor_signal['direction']['label']['ko']}",
            "—" if anchor_signal is None else f"{anchor_signal['heat']['label']['en']} · {anchor_signal['direction']['label']['en']}",
            {"symbol": ANCHOR_SYMBOL, "direction": None if anchor_signal is None else anchor_signal["direction"]["score"],
             "as_of": None if anchor_signal is None else anchor_signal.get("as_of")},
        ),
        crypto_signal._component(
            "funding_breadth", "펀딩 쏠림 폭", "funding crowding breadth",
            None if crowded_share is None else round(crowded_share * 100, 1),
            None if crowded_share is None else crypto_signal._interpolate(BREADTH_ANCHORS, crowded_share),
            "—" if crowded_share is None else f"유동 시장 {len(with_funding)}개 중 {len(crowded)}개({crowded_share * 100:.0f}%)가 기준선 ±{CROWDED_EXCESS_APR:g}%p 밖",
            "—" if crowded_share is None else f"{len(crowded)} of {len(with_funding)} liquid markets ({crowded_share * 100:.0f}%) beyond ±{CROWDED_EXCESS_APR:g}pp",
            {"crowded": len(crowded), "sample": len(with_funding), "threshold_excess_apr": CROWDED_EXCESS_APR,
             "anchors": [{"share": a, "heat": h} for a, h in BREADTH_ANCHORS]},
        ),
        crypto_signal._component(
            "sentiment", "공포·탐욕", "fear & greed",
            sentiment_value, sentiment_value,
            "—" if sentiment_value is None else f"{sentiment_value:.0f}/100" + (f" · {sentiment_meta.get('classification')}" if sentiment_meta.get("classification") else ""),
            "—" if sentiment_value is None else f"{sentiment_value:.0f}/100" + (f" · {sentiment_meta.get('classification')}" if sentiment_meta.get("classification") else ""),
            sentiment_meta,
        ),
        crypto_signal._component(
            "advance_breadth", "24h 상승 폭", "24h advance breadth",
            None if advance_share is None else round(advance_share * 100, 1),
            None if advance_share is None else crypto_signal._clamp(advance_share * 100),
            "—" if advance_share is None else f"유동 시장의 {advance_share * 100:.0f}%가 24시간 상승",
            "—" if advance_share is None else f"{advance_share * 100:.0f}% of liquid markets are up over 24h",
            {"advancing": len(advancing), "sample": len(with_change)},
        ),
    ]
    for component in components:
        component["weight"] = MARKET_WEIGHTS.get(component["id"])

    scored = [(c["heat_score"], c["weight"]) for c in components if c["heat_score"] is not None and c["weight"]]
    total_weight = sum(weight for _score, weight in scored)
    if not total_weight:
        raise RegimeUnavailable("unavailable")
    heat = round(crypto_signal._clamp(sum(score * weight for score, weight in scored) / total_weight), 1)
    heat_key, heat_label = crypto_signal._band(crypto_signal.HEAT_BANDS, heat)

    anchor_direction = anchor_signal["direction"]["score"] if anchor_signal else 0.0
    breadth_direction = ((advance_share - 0.5) * 200.0) if advance_share is not None else 0.0
    direction = round(max(-100.0, min(100.0, anchor_direction * 0.6 + breadth_direction * 0.4)), 1)
    direction_key, direction_label = crypto_signal._band(crypto_signal.DIRECTION_BANDS, direction)

    return {
        "generated_at": _iso_utc(),
        "as_of": snapshot.get("as_of") or snapshot.get("fetched_at"),
        "heat": {"score": heat, "band": heat_key, "label": heat_label, "weights": MARKET_WEIGHTS},
        "direction": {"score": direction, "band": direction_key, "label": direction_label,
                      "basis": f"{ANCHOR_SYMBOL} trend 60% + 24h advance breadth 40%"},
        "components": components,
        "sample": {
            "markets": len(rows),
            "liquid": len(liquid),
            "min_volume_usd": crypto_board.MIN_VOLUME_USD,
            "with_funding": len(with_funding),
            "crowded": len(crowded),
            "advancing": len(advancing),
        },
        "reading": _reading(heat, heat_label, direction_label, components),
        "anchor": None if anchor_signal is None else {
            "symbol": ANCHOR_SYMBOL,
            "heat": anchor_signal["heat"]["score"],
            "band": anchor_signal["heat"]["band"],
            "direction": anchor_signal["direction"]["score"],
            "url": f"/crypto/{ANCHOR_SYMBOL}",
        },
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
        "rights": crypto_market._RIGHTS,
    }
