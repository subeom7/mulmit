"""Live public market cards backed by one Hyperliquid HIP-3 snapshot.

The monitor intentionally does not read the legacy Yahoo price cache.  A cold
request performs one ``metaAndAssetCtxs`` call for the ``xyz`` DEX and exposes
only values actually present in that response.  Hyperliquid contexts do not
carry historical highs or a per-market exchange timestamp, so drawdowns and
chart observations remain null/empty instead of being inferred.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import (
    API_URL,
    HYPERLIQUID_INFO_DOCS,
    REQUEST_TYPE,
    HyperliquidProvider,
)

HISTORY_DAYS = {
    "1y": 366,
    "2y": 366 * 2,
    "3y": 366 * 3,
    "5y": 366 * 5,
    "max": None,
}
MAX_PUBLIC_OBSERVATIONS = 1500
ASSET_CACHE_TTL_SECONDS = 30.0
ASSET_STALE_TTL_SECONDS = 300.0

TRADE_XYZ_DOCS = "https://docs.trade.xyz/"
TRADE_XYZ_EQUITY_DOCS = (
    "https://docs.trade.xyz/xyz-perps-specification/equity-perpetuals/"
    "xyz100-and-index-perpetuals"
)
TRADE_XYZ_EXTERNAL_PRICE_DOCS = "https://docs.trade.xyz/perp-mechanics/external-price"


@dataclass(frozen=True)
class AssetSpec:
    asset_id: str
    provider_symbol: str | None
    public_symbol: str
    group: str
    label_ko: str
    label_en: str
    description_ko: str
    description_en: str
    underlying: str
    currency: str | None
    units_long: str
    units_short: str
    instrument_kind: str
    documentation_url: str = TRADE_XYZ_DOCS


ASSETS = (
    AssetSpec(
        "sp500",
        "xyz:SP500",
        "SP500",
        "global",
        "S&P 500 합성 무기한선물",
        "S&P 500 synthetic perpetual",
        "S&P 500 현물지수를 참조하는 trade.xyz 무기한선물입니다. 현물지수 자체가 아닙니다.",
        "A trade.xyz perpetual referencing the S&P 500 cash index; it is not the cash index itself.",
        "S&P 500 Index reference",
        None,
        "Index-reference points quoted in USDC",
        "pt",
        "equity_index_perpetual",
        TRADE_XYZ_EQUITY_DOCS,
    ),
    AssetSpec(
        "nasdaq",
        "xyz:XYZ100",
        "XYZ100",
        "global",
        "XYZ100 (나스닥 대용 지표)",
        "XYZ100 (Nasdaq proxy)",
        "미국 대형 비금융주 100종목을 추종하는 trade.xyz 지수 무기한선물입니다. 나스닥 종합지수나 공식 Nasdaq-100은 아닙니다.",
        "A trade.xyz 100-stock, technology-heavy index perpetual used as a Nasdaq proxy; it is neither the Nasdaq Composite nor the official Nasdaq-100.",
        "trade.xyz XYZ100 index (Nasdaq proxy)",
        None,
        "Index-reference points quoted in USDC",
        "pt",
        "equity_index_perpetual",
        TRADE_XYZ_EQUITY_DOCS,
    ),
    AssetSpec(
        "gold",
        "xyz:GOLD",
        "GOLD",
        "global",
        "금 합성 무기한선물",
        "Gold synthetic perpetual",
        "달러 표시 금 가격을 참조하는 trade.xyz 무기한선물입니다. 실물 금이나 현물 호가가 아닙니다.",
        "A trade.xyz perpetual referencing a U.S.-dollar gold price; it is not physical gold or a spot quote.",
        "Gold price reference",
        "USD",
        "USDC per troy-ounce reference unit",
        "USD/oz",
        "commodity_perpetual",
    ),
    AssetSpec(
        "bitcoin",
        None,
        "BTC",
        "global",
        "비트코인",
        "Bitcoin",
        "현재 자산 카드 클라이언트는 Hyperliquid 메인 DEX를 조회하지 않아 값을 제공하지 않습니다.",
        "Unavailable because this asset-card client does not query Hyperliquid's main DEX.",
        "Bitcoin / USD",
        "USD",
        "U.S. dollars",
        "USD",
        "crypto_spot_reference",
    ),
    AssetSpec(
        "kospi",
        "xyz:KR200",
        "KR200",
        "korea",
        "KR200 (KOSPI 200 대용 지표)",
        "KR200 (KOSPI 200 proxy)",
        "한국 대형주 200 지수를 참조하는 trade.xyz 무기한선물입니다. KOSPI 종합지수 현물값이 아닙니다.",
        "A trade.xyz perpetual referencing a Korea 200 large-cap index; it is a KOSPI 200 proxy, not the KOSPI Composite cash index.",
        "Korea 200 index reference (KOSPI 200 proxy)",
        None,
        "Korean equity index-reference points",
        "pt",
        "korea_index_perpetual",
    ),
    AssetSpec(
        "kosdaq",
        None,
        "KOSDAQ",
        "korea",
        "KOSDAQ",
        "KOSDAQ",
        "현재 xyz DEX에 검증된 KOSDAQ 연계 시장이 없어 값을 제공하지 않습니다.",
        "Unavailable because no verified KOSDAQ-linked market is present on the xyz DEX.",
        "KOSDAQ cash index",
        None,
        "Index points",
        "pt",
        "cash_index",
    ),
    AssetSpec(
        "samsung",
        "xyz:SMSN",
        "SMSN",
        "korea",
        "삼성전자 USD 환산 무기한선물",
        "Samsung Electronics USD-converted perpetual",
        "삼성전자 보통주(KRX 005930)의 원화 기준가를 USD/USDC로 환산해 참조하는 합성 무기한선물입니다. 삼성전자 원화 현물 주가가 아닙니다.",
        "A synthetic perpetual referencing Samsung Electronics ordinary shares (KRX 005930) after KRW-to-USD/USDC conversion; it is not the KRW cash share price.",
        "Samsung Electronics ordinary share (KRX 005930), KRW-to-USD converted reference",
        "USD",
        "USDC per converted share-reference unit",
        "USDC",
        "korea_equity_perpetual",
    ),
    AssetSpec(
        "usdkrw",
        "xyz:KRW",
        "KRW",
        "korea",
        "원/달러 합성 무기한선물",
        "USD/KRW synthetic perpetual",
        "미국 달러 1단위당 원화(KRW per USD)를 참조하는 trade.xyz 무기한선물입니다.",
        "A trade.xyz perpetual referencing Korean won per one U.S. dollar (KRW per USD).",
        "USD/KRW (KRW per USD)",
        "KRW",
        "Korean won per U.S. dollar reference",
        "KRW/USD",
        "fx_perpetual",
    ),
    AssetSpec(
        "ewz",
        "xyz:EWZ",
        "EWZ",
        "emerging",
        "브라질 EWZ 무기한선물",
        "Brazil EWZ perpetual",
        "미국 상장 iShares MSCI Brazil ETF(EWZ)를 참조하는 trade.xyz 무기한선물입니다.",
        "A trade.xyz perpetual referencing the U.S.-listed iShares MSCI Brazil ETF (EWZ).",
        "iShares MSCI Brazil ETF (EWZ)",
        "USD",
        "USDC per ETF-share reference unit",
        "USDC",
        "etf_perpetual",
    ),
    AssetSpec(
        "inda",
        "xyz:NIFTY",
        "NIFTY",
        "emerging",
        "인도 NIFTY 50 (INDA 대체 지표)",
        "India NIFTY 50 (not INDA)",
        "인도 NIFTY 50 지수를 참조하는 무기한선물입니다. 미국 상장 INDA ETF 가격이 아닙니다.",
        "A perpetual referencing India's NIFTY 50 index; it is not the U.S.-listed INDA ETF price.",
        "NIFTY 50 index reference (not INDA ETF)",
        None,
        "NIFTY 50 index-reference points",
        "pt",
        "equity_index_perpetual",
    ),
    AssetSpec(
        "vnm",
        None,
        "VNM",
        "emerging",
        "베트남 VNM",
        "Vietnam VNM",
        "현재 xyz DEX에 검증된 VNM 또는 베트남 주가지수 연계 시장이 없어 값을 제공하지 않습니다.",
        "Unavailable because no verified VNM- or Vietnam-index-linked market is present on the xyz DEX.",
        "VanEck Vietnam ETF (VNM)",
        "USD",
        "U.S. dollars",
        "USD",
        "etf_reference",
    ),
    AssetSpec(
        "ewj",
        "xyz:EWJ",
        "EWJ",
        "emerging",
        "일본 EWJ 무기한선물",
        "Japan EWJ perpetual",
        "미국 상장 iShares MSCI Japan ETF(EWJ)를 참조하는 trade.xyz 무기한선물입니다.",
        "A trade.xyz perpetual referencing the U.S.-listed iShares MSCI Japan ETF (EWJ).",
        "iShares MSCI Japan ETF (EWJ)",
        "USD",
        "USDC per ETF-share reference unit",
        "USDC",
        "etf_perpetual",
    ),
    AssetSpec(
        "dxy",
        "xyz:DXY",
        "DXY",
        "macro",
        "달러인덱스 합성 무기한선물",
        "Dollar-index synthetic perpetual",
        "미국 달러인덱스(DXY)를 참조하는 trade.xyz 무기한선물입니다. ICE 현물 데이터 피드가 아닙니다.",
        "A trade.xyz perpetual referencing the U.S. Dollar Index (DXY); it is not an ICE cash-data feed.",
        "U.S. Dollar Index (DXY) reference",
        None,
        "Index-reference points",
        "pt",
        "fx_index_perpetual",
    ),
    AssetSpec(
        "usdjpy",
        "xyz:JPY",
        "JPY",
        "macro",
        "달러/엔 합성 무기한선물",
        "USD/JPY synthetic perpetual",
        "미국 달러 1단위당 일본 엔(JPY per USD)을 참조하는 trade.xyz 무기한선물입니다.",
        "A trade.xyz perpetual referencing Japanese yen per one U.S. dollar (JPY per USD).",
        "USD/JPY (JPY per USD)",
        "JPY",
        "Japanese yen per U.S. dollar reference",
        "JPY/USD",
        "fx_perpetual",
    ),
    AssetSpec(
        "vix",
        "xyz:VIX",
        "VIX",
        "risk",
        "VIX 연계 합성 무기한선물",
        "VIX-linked synthetic perpetual",
        "trade.xyz의 변동성 참조값에 연계된 합성 무기한선물입니다. Cboe VIX 공식 지수값이나 Cboe 데이터 피드가 아닙니다.",
        "A synthetic perpetual linked to trade.xyz's volatility reference; it is not the official Cboe VIX value or a Cboe data feed.",
        "trade.xyz VIX-linked reference (not an official Cboe VIX feed)",
        None,
        "Volatility index-reference points",
        "pt",
        "volatility_index_perpetual",
    ),
    AssetSpec(
        "wti",
        "xyz:CL",
        "CL",
        "macro",
        "WTI/CL 연계 합성 무기한선물",
        "WTI/CL-linked synthetic perpetual",
        "trade.xyz의 CL 원유 참조값에 연계된 합성 무기한선물입니다. WTI 현물 호가나 CME/NYMEX 공식 결제값이 아닙니다.",
        "A synthetic perpetual linked to trade.xyz's CL oil reference; it is not a WTI spot quote or an official CME/NYMEX settlement feed.",
        "trade.xyz CL oil reference (WTI/CL proxy)",
        "USD",
        "USDC per barrel-reference unit",
        "USD/bbl ref",
        "energy_commodity_perpetual",
    ),
    AssetSpec(
        "copper",
        "xyz:COPPER",
        "COPPER",
        "macro",
        "구리 연계 합성 무기한선물",
        "Copper-linked synthetic perpetual",
        "trade.xyz의 COPPER 가격 참조값에 연계된 합성 무기한선물입니다. IMF 구리 시계열, 현물 호가 또는 공식 거래소 결제값이 아닙니다.",
        "A synthetic perpetual linked to trade.xyz's COPPER price reference; it is not the IMF copper series, a spot quote, or an official exchange settlement feed.",
        "trade.xyz COPPER reference (copper-price proxy, not IMF copper)",
        "USD",
        "USDC per pound-reference unit",
        "USD/lb ref",
        "metal_commodity_perpetual",
    ),
)

# Asset cards no longer schedule legacy Yahoo ingestion.  These names remain
# exported because ``app.ingest`` imports them during the migration period.
ASSET_TICKERS: tuple[str, ...] = ()
CORRELATION_TICKERS = ("SPY", "TLT", "GLD", "UUP", "USO", "BTC-USD")

GROUPS = (
    ("global", "글로벌 자산", "Global assets"),
    ("korea", "한국 자산", "Korean assets"),
    ("emerging", "글로벌 지역 지표", "Regional indicators"),
    ("risk", "시장 위험", "Market risk"),
    ("macro", "매크로·원자재", "Macro & commodities"),
)


class DexProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...


_DEFAULT_PROVIDER = HyperliquidProvider(
    timeout=2.5,
    retries=0,
    max_request_seconds=3.0,
    ttl=ASSET_CACHE_TTL_SECONDS,
    stale_ttl=ASSET_STALE_TTL_SECONDS,
)


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _liquidity_status(context: dict[str, Any]) -> str:
    volume = _number(context.get("dayNtlVlm"))
    if volume is None or volume <= 0:
        return "unavailable"
    if volume >= 1_000_000:
        return "high"
    if volume >= 100_000:
        return "medium"
    return "low"


def _market_index(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    markets = snapshot.get("markets")
    if not isinstance(markets, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for market in markets:
        if not isinstance(market, dict):
            continue
        symbol = market.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            result[symbol.strip().casefold()] = market
    return result


def _source(spec: AssetSpec, metadata: dict[str, Any], price_field: str) -> dict[str, Any]:
    annotation = metadata.get("perpAnnotation")
    return {
        "provider": "Hyperliquid HIP-3",
        "publisher": "trade.xyz",
        "url": f"https://app.hyperliquid.xyz/trade/{quote(spec.provider_symbol or '', safe=':')}",
        "api_url": API_URL,
        "documentation_url": spec.documentation_url,
        "external_price_documentation_url": TRADE_XYZ_EXTERNAL_PRICE_DOCS,
        "market_symbol": spec.provider_symbol,
        "underlying": spec.underlying,
        "instrument_type": "synthetic perpetual future",
        "price_field": price_field,
        "provider_annotation": annotation if isinstance(annotation, str) else None,
    }


def _payload(spec: AssetSpec, market: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
    # Delisted contexts can remain in Hyperliquid's universe with a frozen mark,
    # zero open interest and zero volume.  Treat those as missing, never live.
    if metadata.get("isDelisted") is True:
        return None

    raw_context = market.get("context")
    context = raw_context if isinstance(raw_context, dict) else {}
    mark = _number(context.get("markPx"))
    oracle = _number(context.get("oraclePx"))
    latest_value = mark if mark is not None else oracle
    if latest_value is None:
        return None

    price_field = "markPx" if mark is not None else "oraclePx_fallback"
    previous_value = _number(context.get("prevDayPx"))
    change_value = None
    change_percent = None
    if previous_value is not None:
        change_value = latest_value - previous_value
        if previous_value != 0:
            change_percent = change_value / previous_value * 100.0

    stale = bool(snapshot.get("stale"))
    age_seconds = _number(snapshot.get("age_seconds"))
    as_of = snapshot.get("as_of") or snapshot.get("fetched_at")
    volume = _number(context.get("dayNtlVlm"))
    funding = _number(context.get("funding"))
    open_interest = _number(context.get("openInterest"))

    return {
        "id": spec.asset_id,
        "key": spec.asset_id,
        "symbol": spec.provider_symbol,
        "display_symbol": spec.public_symbol,
        "group": spec.group,
        "label": {"ko": spec.label_ko, "en": spec.label_en},
        "description": {"ko": spec.description_ko, "en": spec.description_en},
        "status": "stale" if stale else "fresh",
        "source": _source(spec, metadata, price_field),
        "units": {"long": spec.units_long, "short": spec.units_short},
        "currency": spec.currency,
        "instrument_kind": spec.instrument_kind,
        "latest": {"date": as_of, "value": latest_value},
        "previous": {
            "date": None,
            "value": previous_value,
            "basis": "Hyperliquid prevDayPx rolling-day reference",
        },
        "change": {
            "value": change_value,
            "percent": change_percent,
            "basis": "24h reference: current markPx (oracle fallback) versus prevDayPx",
        },
        "drawdown": {
            "value": None,
            "ath": None,
            "date": None,
            "status": "unavailable_without_history",
        },
        "market": {
            "mark": mark,
            "oracle": oracle,
            "previous_24h_reference": previous_value,
            "funding_hourly_rate": funding,
            "open_interest_base_units": open_interest,
            "day_volume_usd_notional": volume,
            "liquidity_status": _liquidity_status(context),
            "listing_status": "active",
        },
        "freshness": {
            "status": "stale" if stale else "fresh",
            "as_of": as_of,
            "as_of_basis": "Hyperliquid response fetch time; contexts have no per-market timestamp",
            "age_seconds": age_seconds,
            "max_age_seconds": ASSET_CACHE_TTL_SECONDS,
            "stale_if_error_seconds": ASSET_STALE_TTL_SECONDS,
            "cached": bool(snapshot.get("cached")),
        },
        "history_status": "not_requested_to_bound_public_api_latency",
        "observation_count": {"available": 0, "returned": 0, "limit": MAX_PUBLIC_OBSERVATIONS},
        "observations": [],
        "rights": {
            "status": "provider_terms_apply",
            "notice": (
                "Public API availability does not itself grant redistribution rights. "
                "Hyperliquid, trade.xyz, and underlying-data terms may apply; this is a "
                "synthetic-perpetual reference, not a spot quote or recommendation."
            ),
            "notice_localized": {
                "ko": (
                    "공개 API 조회 가능 여부가 재배포 권리를 보장하지 않습니다. Hyperliquid, "
                    "trade.xyz 및 기초 데이터 제공자의 약관이 적용될 수 있으며, 표시값은 현물 "
                    "호가나 투자 권유가 아닌 합성 무기한선물 참고값입니다."
                ),
                "en": (
                    "Public API availability does not itself grant redistribution rights. "
                    "Hyperliquid, trade.xyz, and underlying-data terms may apply; values are "
                    "synthetic-perpetual references, not spot quotes or recommendations."
                ),
            },
        },
    }


def _empty_snapshot(history: str, error: str) -> dict[str, Any]:
    generated_at = _iso_utc()
    return {
        "generated_at": generated_at,
        "as_of": None,
        "history": history,
        "provider": {
            "id": "hyperliquid",
            "name": "Hyperliquid HIP-3 / trade.xyz",
            "url": HYPERLIQUID_INFO_DOCS,
            "api_url": API_URL,
            "read_path": "live_public_info_only",
            "request_type": REQUEST_TYPE,
            "dex": "xyz",
            "error": error,
            "cached": False,
            "stale": False,
            "age_seconds": None,
            "ttl_seconds": ASSET_CACHE_TTL_SECONDS,
            "stale_if_error_seconds": ASSET_STALE_TTL_SECONDS,
        },
        "groups": _groups(),
        "assets": [],
        "missing": [spec.asset_id for spec in ASSETS],
        "coverage": {"available": 0, "total": len(ASSETS), "ratio": 0.0},
        "disclaimer": _disclaimer(),
    }


def _groups() -> list[dict[str, Any]]:
    return [
        {
            "id": group_id,
            "label": {"ko": label_ko, "en": label_en},
            "asset_ids": [spec.asset_id for spec in ASSETS if spec.group == group_id],
        }
        for group_id, label_ko, label_en in GROUPS
    ]


def _disclaimer() -> dict[str, str]:
    return {
        "ko": (
            "표시값은 trade.xyz가 Hyperliquid HIP-3에 상장한 합성 무기한선물의 참고값입니다. "
            "현물 가격, 공식 거래소 지수 또는 다음 정규장 시가 예측이 아니며 유동성이 낮은 시장은 왜곡될 수 있습니다."
        ),
        "en": (
            "Values are references from synthetic trade.xyz perpetuals listed through Hyperliquid HIP-3. "
            "They are not spot prices, official exchange index feeds, or forecasts of the next regular-session open; thin markets can be distorted."
        ),
    }


def build_asset_snapshot(
    history: str = "3y",
    provider: DexProvider | None = None,
) -> dict[str, Any]:
    """Build cards from one bounded xyz DEX context request.

    ``history`` remains in the public contract for the chart controls, but this
    low-latency endpoint deliberately returns empty observations.  Historical
    candles can be added later through a separately cached/background path.
    """
    if history not in HISTORY_DAYS:
        raise ValueError(f"unsupported history: {history}")

    client = provider or _DEFAULT_PROVIDER
    try:
        snapshot = client.fetch_dex("xyz")
    except RateLimited:
        return _empty_snapshot(history, "rate_limited")
    except DataUnavailable:
        return _empty_snapshot(history, "unavailable")

    markets = _market_index(snapshot)
    assets: list[dict[str, Any]] = []
    missing: list[str] = []
    for spec in ASSETS:
        if spec.provider_symbol is None:
            missing.append(spec.asset_id)
            continue
        market = markets.get(spec.provider_symbol.casefold())
        if market is None:
            missing.append(spec.asset_id)
            continue
        payload = _payload(spec, market, snapshot)
        if payload is None:
            missing.append(spec.asset_id)
            continue
        assets.append(payload)

    as_of = snapshot.get("as_of") or snapshot.get("fetched_at")
    age_seconds = _number(snapshot.get("age_seconds"))
    return {
        "generated_at": _iso_utc(),
        "as_of": as_of,
        "history": history,
        "provider": {
            "id": "hyperliquid",
            "name": "Hyperliquid HIP-3 / trade.xyz",
            "url": HYPERLIQUID_INFO_DOCS,
            "api_url": API_URL,
            "read_path": "live_public_info_only",
            "request_type": REQUEST_TYPE,
            "dex": "xyz",
            "cached": bool(snapshot.get("cached")),
            "stale": bool(snapshot.get("stale")),
            "age_seconds": age_seconds,
            "ttl_seconds": ASSET_CACHE_TTL_SECONDS,
            "stale_if_error_seconds": ASSET_STALE_TTL_SECONDS,
            "as_of": as_of,
            "as_of_basis": "Hyperliquid response fetch time",
            "error": snapshot.get("error"),
        },
        "groups": _groups(),
        "assets": assets,
        "missing": missing,
        "coverage": {
            "available": len(assets),
            "total": len(ASSETS),
            "ratio": round(len(assets) / len(ASSETS), 4),
        },
        "disclaimer": _disclaimer(),
    }
