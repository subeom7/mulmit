"""Kimchi premium — Upbit KRW quotes against Hyperliquid's dollar oracle.

Two premiums, each honest about its exchange rate:

* ``usdt_basis`` — (KRW-BTC ÷ KRW-USDT) ÷ Hyperliquid oracle BTC − 1.  Both
  numerators come from Upbit at the same moment and the USDT leg cancels the
  won/dollar rate, so this needs no live FX licence and is the headline number.
* ``official_basis`` — (KRW-BTC ÷ official won/dollar) ÷ oracle − 1, using the
  Bank of Korea ECOS daily reference rate the site already serves.  The rate's
  date travels with the value; it is not a live rate.

The "tether premium" (KRW-USDT ÷ official rate − 1) is shown on its own so a
reader can see how much of the headline is the dollar itself.

Rights: the Upbit lane is ``pending_rights`` (register §3.19) and defaults off;
Hyperliquid values ride the HIP-3 display gate; the FX rate is the ECOS lane.
Nothing here calls a foreign CEX.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Protocol

from . import data_rights
from .crypto_market import _DEFAULT_PROVIDER as _HL_PROVIDER
from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import API_URL as HL_API_URL
from .providers.hyperliquid import MAIN_DEX
from .providers.upbit import (
    UPBIT_DOCS_URL,
    UPBIT_PROVIDER_ID,
    UPBIT_PUBLISHER,
    UPBIT_PUBLISHER_EN,
    UPBIT_RATE_LIMIT_DOCS,
    UPBIT_TERMS_QUOTE,
    UPBIT_TERMS_URL,
    UPBIT_TICKER_URL,
    UpbitProvider,
)

USDT_MARKET = "KRW-USDT"


@dataclass(frozen=True)
class KimchiCoin:
    symbol: str
    market: str
    label_ko: str
    label_en: str


# Coins quoted on both venues. BTC first because the headline reads "BTC premium".
KIMCHI_COINS: tuple[KimchiCoin, ...] = (
    KimchiCoin("BTC", "KRW-BTC", "비트코인", "Bitcoin"),
    KimchiCoin("ETH", "KRW-ETH", "이더리움", "Ethereum"),
    KimchiCoin("SOL", "KRW-SOL", "솔라나", "Solana"),
    KimchiCoin("XRP", "KRW-XRP", "리플 (XRP)", "XRP"),
    KimchiCoin("DOGE", "KRW-DOGE", "도지코인", "Dogecoin"),
)

_DEFAULT_UPBIT = UpbitProvider()


class TickerProvider(Protocol):
    def fetch_tickers(self, markets: list[str]) -> dict[str, Any]: ...


class DexProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...


def enabled() -> bool:
    return data_rights.upbit_serving_enabled()


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _pct(ratio: float | None) -> float | None:
    return None if ratio is None else round((ratio - 1.0) * 100.0, 4)


def _oracle_prices(hl_provider: DexProvider) -> tuple[dict[str, float], dict[str, Any]]:
    """Hyperliquid oracle prices (its external spot reference) for the kimchi coins."""
    snapshot = hl_provider.fetch_dex(MAIN_DEX)
    prices: dict[str, float] = {}
    for market in snapshot.get("markets") or []:
        if not isinstance(market, dict):
            continue
        symbol = str(market.get("symbol") or "").strip()
        context = market.get("context") if isinstance(market.get("context"), dict) else {}
        metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
        if metadata.get("isDelisted") is True:
            continue
        oracle = _number(context.get("oraclePx")) or _number(context.get("markPx"))
        if symbol and oracle is not None and oracle > 0:
            prices[symbol] = oracle
    return prices, snapshot


_RIGHTS = {
    "status": "pending_rights",
    "notice": (
        "Upbit quotation data is relayed under a recorded operator decision while written "
        "confirmation of public-display rights is pending (Upbit Open API Terms §5 asserts "
        "copyright over the data and neither permits nor forbids redisplay). Hyperliquid and "
        "Bank of Korea terms apply to the other inputs. Not spot quotes on any single venue's "
        "order book as seen by you, not a recommendation."
    ),
    "notice_localized": {
        "ko": (
            "업비트 시세는 공개 표시 권리의 서면 확인이 나기 전까지 운영자 결정 기록 아래 전달됩니다"
            "(업비트 Open API 이용약관 제5조는 데이터 저작권을 두나무에 두며 재표시를 허가도 금지도 "
            "하지 않습니다). Hyperliquid·한국은행 약관은 각 입력에 적용됩니다. 투자 권유가 아닙니다."
        ),
        "en": (
            "Upbit quotes are relayed under a recorded operator decision while written confirmation "
            "of public-display rights is pending (Upbit Open API Terms §5 asserts copyright over the "
            "data and neither permits nor forbids redisplay). Hyperliquid and Bank of Korea terms "
            "apply to the other inputs. Not a recommendation."
        ),
    },
    "terms_quote": UPBIT_TERMS_QUOTE,
    "terms_url": UPBIT_TERMS_URL,
}

_METHOD = {
    "ko": (
        "USDT 기준 프리미엄 = (업비트 KRW-코인 ÷ 업비트 KRW-USDT) ÷ Hyperliquid 오라클가 − 1 — 같은 "
        "시각 두 업비트 시세의 비라 환율이 소거됩니다. 공식환율 기준 = (KRW-코인 ÷ 한국은행 일별 매매기준율) "
        "÷ 오라클가 − 1, 고시 날짜 표시. 테더 프리미엄 = KRW-USDT ÷ 공식환율 − 1. 전부 표시값의 산술 파생입니다."
    ),
    "en": (
        "USDT-basis premium = (Upbit KRW-coin ÷ Upbit KRW-USDT) ÷ Hyperliquid oracle − 1 — a ratio of two "
        "same-moment Upbit quotes, so the exchange rate cancels. Official-basis = (KRW-coin ÷ BOK daily "
        "reference rate) ÷ oracle − 1, with the rate's date. Tether premium = KRW-USDT ÷ official rate − 1. "
        "All arithmetic on displayed values."
    ),
}

_DISCLAIMER = {
    "ko": (
        "업비트 최근 체결가와 Hyperliquid 오라클 참고가의 비교 참고값입니다. 거래소별 호가·수수료·출금 "
        "조건을 반영하지 않으며 차익거래 가능성이나 투자 권유를 뜻하지 않습니다. 공식환율은 한국은행 일별 "
        "고시값이라 실시간이 아닙니다."
    ),
    "en": (
        "A reference comparison of Upbit's last trade price against Hyperliquid's oracle; it ignores order "
        "books, fees and withdrawal conditions and implies no arbitrage or recommendation. The official "
        "rate is the Bank of Korea's daily quotation, not a live rate."
    ),
}


def _empty(reason: str, *, fx: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "generated_at": _iso_utc(),
        "status": reason,
        "as_of": None,
        "usdt": None,
        "coins": [],
        "fx": fx,
        "source": _source_block(None, None),
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
        "rights": _RIGHTS,
    }


def _source_block(upbit_snapshot: dict[str, Any] | None, hl_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    upbit_snapshot = upbit_snapshot or {}
    hl_snapshot = hl_snapshot or {}
    return {
        "upbit": {
            "provider": UPBIT_PROVIDER_ID,
            "publisher": UPBIT_PUBLISHER,
            "publisher_en": UPBIT_PUBLISHER_EN,
            "api_url": UPBIT_TICKER_URL,
            "documentation_url": UPBIT_DOCS_URL,
            "rate_limit_url": UPBIT_RATE_LIMIT_DOCS,
            "terms_url": UPBIT_TERMS_URL,
            "read_path": "server_relay_ttl_cache",
            "as_of": upbit_snapshot.get("as_of"),
            "cached": bool(upbit_snapshot.get("cached")),
            "stale": bool(upbit_snapshot.get("stale")),
            "age_seconds": _number(upbit_snapshot.get("age_seconds")),
            "attribution": {"ko": "시세: 업비트(두나무)", "en": "Quotes: Upbit (Dunamu)"},
        },
        "hyperliquid": {
            "provider": "hyperliquid",
            "publisher": "Hyperliquid",
            "api_url": HL_API_URL,
            "price_field": "oraclePx",
            "as_of": hl_snapshot.get("as_of"),
            "stale": bool(hl_snapshot.get("stale")),
        },
    }


def kimchi_symbols() -> set[str]:
    return {coin.symbol for coin in KIMCHI_COINS}


def build_for_coin(symbol: str, **kwargs: Any) -> dict[str, Any] | None:
    """One coin's KRW row with the context it needs to be read — or ``None`` when not covered.

    The Upbit provider keeps a single-flight TTL cache, so a coin page asking for
    this costs the same upstream call the dashboard section already makes.
    """
    if not enabled() or symbol.upper() not in kimchi_symbols():
        return None
    payload = build_crypto_kimchi(**kwargs)
    row = next((coin for coin in payload.get("coins") or [] if coin.get("symbol") == symbol.upper()), None)
    if row is None:
        return None
    return {
        **row,
        "as_of": payload.get("as_of"),
        "usdt": payload.get("usdt"),
        "fx": payload.get("fx"),
        "source": payload.get("source"),
        "methodology": payload.get("methodology"),
        "disclaimer": payload.get("disclaimer"),
        "rights": payload.get("rights"),
    }


def build_crypto_kimchi(
    provider: TickerProvider | None = None,
    hl_provider: DexProvider | None = None,
    fx_loader: Any | None = None,
) -> dict[str, Any]:
    """KRW quotes and premiums for the kimchi coins. Missing inputs null their fields."""
    if fx_loader is None:
        # Imported lazily: kr_overnight pulls in the whole Korea stack.
        from .kr_overnight import _load_fx as fx_loader  # noqa: PLC0415

    fx = fx_loader()
    official_rate = _number(fx.get("rate")) if fx.get("status") == "ok" else None

    upbit = provider or _DEFAULT_UPBIT
    markets = [USDT_MARKET, *[coin.market for coin in KIMCHI_COINS]]
    try:
        upbit_snapshot = upbit.fetch_tickers(markets)
    except RateLimited:
        return _empty("rate_limited", fx=fx)
    except DataUnavailable:
        return _empty("unavailable", fx=fx)
    tickers = upbit_snapshot.get("tickers") or {}

    hl_prices: dict[str, float] = {}
    hl_snapshot: dict[str, Any] = {}
    try:
        hl_prices, hl_snapshot = _oracle_prices(hl_provider or _HL_PROVIDER)
    except (RateLimited, DataUnavailable):
        hl_prices, hl_snapshot = {}, {"error": "unavailable"}

    usdt_ticker = tickers.get(USDT_MARKET)
    usdt_krw = _number(usdt_ticker.get("trade_price")) if usdt_ticker else None
    usdt_block = None
    if usdt_krw is not None:
        usdt_block = {
            "market": USDT_MARKET,
            "krw": usdt_krw,
            "change_24h_percent": usdt_ticker.get("change_24h_percent"),
            "traded_at": usdt_ticker.get("traded_at"),
            "tether_premium_percent": (
                _pct(usdt_krw / official_rate) if official_rate else None
            ),
            "official_rate": official_rate,
            "official_rate_date": fx.get("date") if official_rate else None,
            "basis": "KRW-USDT last trade ÷ BOK ECOS daily reference rate − 1; null without an official rate",
        }

    coins: list[dict[str, Any]] = []
    for coin in KIMCHI_COINS:
        ticker = tickers.get(coin.market)
        if not ticker:
            continue
        krw = _number(ticker.get("trade_price"))
        if krw is None:
            continue
        oracle = hl_prices.get(coin.symbol)
        usd_via_usdt = krw / usdt_krw if usdt_krw else None
        usd_via_official = krw / official_rate if official_rate else None
        coins.append(
            {
                "symbol": coin.symbol,
                "market": coin.market,
                "label": {"ko": coin.label_ko, "en": coin.label_en},
                "krw": krw,
                "change_24h_percent": ticker.get("change_24h_percent"),
                "volume_24h_krw": ticker.get("acc_trade_price_24h"),
                "traded_at": ticker.get("traded_at"),
                "usd_via_usdt": round(usd_via_usdt, 6) if usd_via_usdt is not None else None,
                "usd_via_official": round(usd_via_official, 6) if usd_via_official is not None else None,
                "oracle_usd": oracle,
                "premium_usdt_basis_percent": (
                    _pct(usd_via_usdt / oracle) if usd_via_usdt is not None and oracle else None
                ),
                "premium_official_basis_percent": (
                    _pct(usd_via_official / oracle) if usd_via_official is not None and oracle else None
                ),
                "status": "ok" if oracle else "no_reference",
            }
        )

    return {
        "generated_at": _iso_utc(),
        "status": "ok" if coins else "unavailable",
        "as_of": upbit_snapshot.get("as_of"),
        "usdt": usdt_block,
        "coins": coins,
        "fx": {
            "status": fx.get("status"),
            "rate": official_rate,
            "date": fx.get("date") if official_rate else None,
            "series_key": fx.get("series_key"),
            "publisher": fx.get("publisher"),
            "basis_ko": fx.get("basis_ko"),
            "basis_en": fx.get("basis_en"),
        },
        "source": _source_block(upbit_snapshot, hl_snapshot),
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
        "rights": _RIGHTS,
    }
