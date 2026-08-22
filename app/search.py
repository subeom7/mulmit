"""One search box for everything the site has a page for.

Three rosters, three hubs, all local: Korean listings (the FSC snapshot the
Korea lane already keeps), the US tickers whose filings we cover, and the
perpetual markets Hyperliquid lists.  Nothing here calls an upstream API on a
keystroke — the coin roster reuses the same cached snapshot the dashboard is
already polling, and the two equity rosters are stored tables.

Each hit carries the hub it opens, so the front end never has to know how a
symbol maps to a page.  A roster that is switched off (or empty) contributes
nothing rather than failing the search.
"""

from __future__ import annotations

import logging
from typing import Any

from . import data_rights, kr_stocks, store
from .crypto_market import _DEFAULT_PROVIDER, COIN_SPECS
from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import MAIN_DEX

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 6
MAX_LIMIT = 15
# Korean display names for the curated coins, so "비트코인" finds BTC.
_COIN_LABELS = {spec.symbol: (spec.label_ko, spec.label_en) for spec in COIN_SPECS}


def _score(needle: str, *fields: str | None) -> int | None:
    """Lower is better: exact symbol, then prefix, then substring; ``None`` is no match."""
    best: int | None = None
    for index, field in enumerate(fields):
        if not field:
            continue
        haystack = field.casefold()
        if haystack == needle:
            rank = 0
        elif haystack.startswith(needle):
            rank = 1
        elif needle in haystack:
            rank = 2
        else:
            continue
        rank = rank * 10 + index  # earlier fields win ties
        best = rank if best is None else min(best, rank)
    return best


def _coin_hits(needle: str, limit: int) -> list[dict[str, Any]]:
    if not data_rights.crypto_overview_enabled():
        return []
    try:
        snapshot = _DEFAULT_PROVIDER.fetch_dex(MAIN_DEX)
    except (RateLimited, DataUnavailable):
        return []  # the coin roster is one of three; its outage must not break search
    hits: list[tuple[int, dict[str, Any]]] = []
    for market in snapshot.get("markets") or []:
        if not isinstance(market, dict):
            continue
        symbol = market.get("symbol")
        metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
        if not isinstance(symbol, str) or metadata.get("isDelisted") is True:
            continue
        label_ko, label_en = _COIN_LABELS.get(symbol, (None, None))
        score = _score(needle, symbol, label_ko, label_en)
        if score is None:
            continue
        context = market.get("context") if isinstance(market.get("context"), dict) else {}
        try:
            volume = float(context.get("dayNtlVlm"))
        except (TypeError, ValueError):
            volume = 0.0
        hits.append((score, {
            "kind": "crypto",
            "symbol": symbol,
            "name": label_ko or symbol,
            "name_en": label_en or symbol,
            "market": "Hyperliquid perp",
            "volume_24h_usd": volume,
            "hub": f"/crypto/{symbol}",
        }))
    # Ties break on liquidity: the market someone means is usually the busy one.
    hits.sort(key=lambda item: (item[0], -(item[1]["volume_24h_usd"] or 0.0)))
    return [hit for _score_value, hit in hits[:limit]]


def _kr_hits(needle: str, limit: int) -> list[dict[str, Any]]:
    try:
        payload = kr_stocks.search(needle, limit)
    except kr_stocks.KrStockDisabled:
        return []
    except Exception:  # noqa: BLE001 - one roster must not break the others
        log.warning("KR roster search failed", exc_info=True)
        return []
    return [
        {
            "kind": "kr_stock",
            "symbol": row["code"],
            "name": row["name"],
            "market": row.get("market"),
            "change_percent": row.get("change_percent"),
            "hub": f"/stock/{row['code']}",
        }
        for row in payload.get("results") or []
    ]


def _us_hits(needle: str, limit: int) -> list[dict[str, Any]]:
    try:
        roster = store.list_insider_companies(status="ok")
    except Exception:  # noqa: BLE001
        log.warning("US roster read failed", exc_info=True)
        return []
    hits: list[tuple[int, dict[str, Any]]] = []
    for row in roster:
        ticker = str(row.get("ticker") or "")
        name = row.get("name")
        score = _score(needle, ticker, name)
        if score is None:
            continue
        hits.append((score, {
            "kind": "us_stock",
            "symbol": ticker,
            "name": name or ticker,
            "market": row.get("exchange") or "US",
            "hub": f"/stock/{ticker}",
        }))
    hits.sort(key=lambda item: (item[0], item[1]["symbol"]))
    return [hit for _score_value, hit in hits[:limit]]


def search(query: str, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """Grouped hits across the coin, Korean and US rosters."""
    needle = (query or "").strip().casefold()
    limit = max(1, min(MAX_LIMIT, int(limit)))
    if not needle:
        return {"query": query, "groups": [], "count": 0}
    groups = [
        {"kind": "crypto", "label": {"ko": "코인", "en": "Coins"}, "results": _coin_hits(needle, limit)},
        {"kind": "kr_stock", "label": {"ko": "국내 종목", "en": "Korean stocks"}, "results": _kr_hits(needle, limit)},
        {"kind": "us_stock", "label": {"ko": "미국 종목", "en": "US stocks"}, "results": _us_hits(needle, limit)},
    ]
    filled = [group for group in groups if group["results"]]
    return {
        "query": query.strip(),
        "groups": filled,
        "count": sum(len(group["results"]) for group in filled),
        "basis": {
            "ko": "코인은 Hyperliquid 상장 무기한선물, 국내는 금융위 상장 로스터, 미국은 공시 수집 대상 티커입니다. 검색은 저장된 로스터만 읽습니다.",
            "en": "Coins are Hyperliquid-listed perpetuals, Korean names come from the FSC listing roster, US tickers from the filing roster. Search reads stored rosters only.",
        },
    }
