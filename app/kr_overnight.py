"""Korean around-the-clock reference prices against the last official close.

The one number this section exists for: how far the HIP-3 synthetic perpetual
has moved since the last confirmed Korea Exchange close.  Equity marks are
quoted in USD, so they are converted through the latest official H.10 won/dollar
rate before the comparison; the KR200 index perpetual trades on the same point
scale as the official KOSPI 200 close and is compared directly, no FX involved.

Three lanes meet here and each keeps its own gate: the route refuses entirely
while HIP-3 public display is off, official closes disappear when the FSC lane
closes, and the conversion disappears when the H.10 series may not be served.
A missing input nulls the fields that depend on it — nothing is estimated.
The H.10 rate is a daily official quotation from a weekly release, not a live
rate, so both the FX date and the close date travel with every derived value.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from . import data_rights, store
from .providers.base import DataUnavailable, RateLimited
from .providers.fedboard import FEDBOARD_PROVIDER_ID, FEDBOARD_PUBLISHER
from .providers.fsc import (
    FSC_INDEX_DATASET_URL,
    FSC_PROVIDER_ID,
    FSC_PUBLISHER,
    FSC_STOCK_DATASET_URL,
)
from .providers.hyperliquid import (
    API_URL,
    HYPERLIQUID_INFO_DOCS,
    REQUEST_TYPE,
    HyperliquidProvider,
)
from .weekend_signals import _korea_weekend_session

OVERNIGHT_DEX = "xyz"
OVERNIGHT_CACHE_TTL_SECONDS = 30.0
OVERNIGHT_STALE_TTL_SECONDS = 300.0
FX_SERIES_KEY = "fx_usdkrw"
# The H.10 release publishes daily rates weekly; beyond this window the stored
# tail is a data problem worth surfacing as "unavailable", not a usable rate.
FX_LOOKBACK_DAYS = 45
KR_INDEX_CLASS = "KOSPI시리즈"
KR200_INDEX_NAME = "코스피 200"

_DEFAULT_PROVIDER = HyperliquidProvider(
    timeout=2.5,
    retries=0,
    max_request_seconds=3.0,
    ttl=OVERNIGHT_CACHE_TTL_SECONDS,
    stale_ttl=OVERNIGHT_STALE_TTL_SECONDS,
)


class DexProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OvernightTarget:
    id: str
    symbol: str
    kind: str  # "equity" | "index" | "adr"
    code: str | None
    label_ko: str
    label_en: str
    # ADR 전용: 원주 1주가 몇 ADR인지. 발행사 공시로 검증된 값만 넣는다.
    adr_per_ordinary: int | None = None


TARGETS = (
    OvernightTarget(
        "samsung_electronics", "xyz:SMSN", "equity", "005930", "삼성전자", "Samsung Electronics"
    ),
    OvernightTarget("sk_hynix", "xyz:SKHX", "equity", "000660", "SK하이닉스", "SK hynix"),
    OvernightTarget(
        "hyundai_motor", "xyz:HYUNDAI", "equity", "005380", "현대자동차", "Hyundai Motor"
    ),
    OvernightTarget("kospi_200", "xyz:KR200", "index", None, "코스피 200", "KOSPI 200"),
    # 나스닥 상장 SK하이닉스 ADR 퍼프. 비율은 발행사 공시(10 ADR = 원주 1주,
    # 2026-08-19 확인: SK하이닉스 뉴스룸·SEC F-1)로 검증된 값이다.
    OvernightTarget(
        "sk_hynix_adr", "xyz:SKHY", "adr", "000660",
        "SK하이닉스 ADR", "SK hynix ADR", adr_per_ordinary=10,
    ),
)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _iso_date(value: Any) -> str | None:
    """FSC snapshots carry ``YYYYMMDD`` basis dates; serve them as ISO."""
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text or None


def _fsc_servable() -> bool:
    return data_rights.series_values_servable(
        FSC_PROVIDER_ID, data_rights.SERVABLE_ROW_RIGHTS
    )


def _load_fx() -> dict[str, Any]:
    """Latest storable H.10 won/dollar rate, or an honest unavailable block.

    Same double gate as the stress composite: the stored series row names its
    provider and rights status, and both must pass before the value ships.
    """
    basis_ko = "미 연준 H.10 주간 릴리스의 일별 공식 고시값 — 실시간 환율이 아닙니다."
    basis_en = (
        "Daily official quotation from the Federal Reserve's weekly H.10 release; "
        "not a live exchange rate."
    )
    unavailable = {
        "status": "unavailable",
        "rate": None,
        "date": None,
        "series_key": FX_SERIES_KEY,
        "publisher": FEDBOARD_PUBLISHER,
        "basis_ko": basis_ko,
        "basis_en": basis_en,
    }
    record = store.get_economic_series(FX_SERIES_KEY)
    if record is None:
        return unavailable
    if not data_rights.series_values_servable(
        str(record.get("provider_id") or ""), str(record.get("rights_status") or "")
    ):
        return unavailable
    start = dt.date.today() - dt.timedelta(days=FX_LOOKBACK_DAYS)
    observations = store.load_economic_observations(FX_SERIES_KEY, start=start)
    if not observations:
        return unavailable
    date, rate = observations[-1]
    if _number(rate) is None or rate <= 0:
        return unavailable
    return {
        "status": "ok",
        "rate": float(rate),
        "date": date.isoformat(),
        "series_key": FX_SERIES_KEY,
        "publisher": FEDBOARD_PUBLISHER,
        "basis_ko": basis_ko,
        "basis_en": basis_en,
    }


def _official_close(target: OvernightTarget, fsc_ok: bool) -> dict[str, Any]:
    """Last confirmed close for the target, from the roster or index snapshot."""
    base = {
        "status": "unavailable",
        "close": None,
        "date": None,
        "unit": "pt" if target.kind == "index" else "KRW",
        "publisher": FSC_PUBLISHER,
        "dataset_url": (
            FSC_INDEX_DATASET_URL if target.kind == "index" else FSC_STOCK_DATASET_URL
        ),
    }
    if not fsc_ok:
        base["status"] = "lane_disabled"
        return base
    if target.kind in ("equity", "adr") and target.code:
        row = store.get_kr_listing(target.code)
        close = _number(row.get("clpr")) if row else None
        if row is None or close is None or close <= 0:
            return base
        return {**base, "status": "ok", "close": close, "date": _iso_date(row.get("bas_dt"))}
    rows = store.load_kr_index_snapshot([KR200_INDEX_NAME], idx_csf=KR_INDEX_CLASS)
    close = _number(rows[0].get("clpr")) if rows else None
    if not rows or close is None or close <= 0:
        return base
    return {**base, "status": "ok", "close": close, "date": _iso_date(rows[0].get("bas_dt"))}


def _perp_block(
    market: dict[str, Any] | None, snapshot: dict[str, Any], symbol: str
) -> dict[str, Any] | None:
    """The live mark and its context, or None when no live market exists."""
    if not isinstance(market, dict):
        return None
    metadata = market.get("metadata") if isinstance(market.get("metadata"), dict) else {}
    if metadata.get("isDelisted") is True:
        return None
    context = market.get("context") if isinstance(market.get("context"), dict) else {}
    mark = _number(context.get("markPx"))
    oracle = _number(context.get("oraclePx"))
    reference = mark if mark is not None else oracle
    if reference is None:
        return None
    previous = _number(context.get("prevDayPx"))
    change_24h = None
    if previous is not None and previous > 0:
        change_24h = (reference / previous - 1.0) * 100.0
    volume = _number(context.get("dayNtlVlm"))
    if volume is None or volume <= 0:
        liquidity = "unavailable"
    elif volume >= 1_000_000:
        liquidity = "high"
    elif volume >= 100_000:
        liquidity = "medium"
    else:
        liquidity = "low"
    return {
        "mark": reference,
        "price_field": "markPx" if mark is not None else "oraclePx_fallback",
        "prev_day": previous,
        "change_24h_percent": round(change_24h, 4) if change_24h is not None else None,
        "day_volume_usd_notional": volume,
        "liquidity_status": liquidity,
        "funding_hourly_rate": _number(context.get("funding")),
        "as_of": snapshot.get("as_of") or snapshot.get("fetched_at"),
        "stale": bool(snapshot.get("stale")),
        "source_url": f"https://app.hyperliquid.xyz/trade/{quote(symbol, safe=':')}",
    }


def _card(
    target: OvernightTarget,
    market: dict[str, Any] | None,
    snapshot: dict[str, Any],
    fx: dict[str, Any],
    fsc_ok: bool,
) -> dict[str, Any]:
    perp = _perp_block(market, snapshot, target.symbol)
    official = _official_close(target, fsc_ok)

    implied: dict[str, Any] = {
        "status": "unavailable",
        "value": None,
        "unit": "pt" if target.kind == "index" else "KRW",
        "fx_applied": target.kind != "index",
        "vs_official_percent": None,
    }
    if perp is not None:
        if target.kind in ("equity", "adr"):
            if fx["status"] == "ok":
                ratio = target.adr_per_ordinary or 1
                implied["value"] = perp["mark"] * ratio * fx["rate"]
                implied["status"] = "ok"
            else:
                implied["status"] = "no_fx"
        else:
            # Index points need no conversion; the perp mark is the implied level.
            implied["value"] = perp["mark"]
            implied["status"] = "ok"
        if implied["value"] is not None and official["status"] == "ok":
            implied["vs_official_percent"] = round(
                (implied["value"] / official["close"] - 1.0) * 100.0, 4
            )

    if perp is None:
        status = "market_unavailable"
    elif implied["vs_official_percent"] is not None:
        status = "ok"
    elif implied["status"] == "no_fx":
        status = "no_fx"
    else:
        status = "no_official_close"

    return {
        "id": target.id,
        "symbol": target.symbol,
        "code": target.code,
        "kind": target.kind,
        "label": {"ko": target.label_ko, "en": target.label_en},
        "adr": (
            {
                "per_ordinary": target.adr_per_ordinary,
                "note_ko": f"{target.adr_per_ordinary} ADR = 원주 1주 (발행사 공시, 2026-08-19 확인)",
                "note_en": f"{target.adr_per_ordinary} ADRs = 1 ordinary share (issuer filings, verified 2026-08-19)",
            }
            if target.kind == "adr" and target.adr_per_ordinary
            else None
        ),
        "status": status,
        "perp": perp,
        "official": official,
        "implied": implied,
        "basis": {
            "ko": (
                "지수 무기한선물 마크(포인트)를 코스피 200 공식 종가와 직접 비교"
                if target.kind == "index"
                else "ADR 퍼프 마크 × 비율 × H.10 공식환율을 원주 마지막 공식 종가와 비교"
                if target.kind == "adr"
                else "합성 무기한선물 마크가격 × H.10 공식환율을 마지막 공식 종가와 비교"
            ),
            "en": (
                "Index-perpetual mark (points) compared directly with the official KOSPI 200 close"
                if target.kind == "index"
                else "ADR-perpetual mark × ratio × official H.10 rate versus the ordinary share's last official close"
                if target.kind == "adr"
                else "Synthetic-perpetual mark × official H.10 rate versus the last official close"
            ),
        },
    }


def build_kr_overnight(
    provider: DexProvider | None = None,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    client = provider or _DEFAULT_PROVIDER
    moment = now or dt.datetime.now(dt.UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)

    error: str | None = None
    snapshot: dict[str, Any] = {}
    try:
        snapshot = client.fetch_dex(OVERNIGHT_DEX)
    except RateLimited:
        error = "rate_limited"
    except DataUnavailable:
        error = "unavailable"

    markets: dict[str, dict[str, Any]] = {}
    for market in snapshot.get("markets") or []:
        if isinstance(market, dict) and isinstance(market.get("symbol"), str):
            markets[market["symbol"].strip().casefold()] = market

    fx = _load_fx()
    fsc_ok = _fsc_servable()
    cards = [
        _card(target, markets.get(target.symbol.casefold()), snapshot, fx, fsc_ok)
        for target in TARGETS
    ]
    available = sum(1 for card in cards if card["status"] == "ok")

    return {
        "generated_at": _iso_utc(),
        "as_of": snapshot.get("as_of") or snapshot.get("fetched_at"),
        "session": _korea_weekend_session(moment),
        "fx": fx,
        "cards": cards,
        "coverage": {"available": available, "total": len(cards)},
        "methodology": {
            "ko": (
                "환산가 = 마크가격 × 원/달러(H.10 공식 고시, 날짜 표기). 기준가 대비 % = "
                "환산가 ÷ 마지막 공식 종가 − 1. 코스피 200은 포인트 단위가 같아 환산 없이 "
                "직접 비교합니다. ADR 카드는 마크 × 공시 비율(10 ADR = 원주 1주) × 환율을 원주 종가와 비교한 프리미엄 참고값입니다. 김치프리미엄 조정은 하지 않습니다."
            ),
            "en": (
                "Implied price = mark × won/dollar (official H.10 quotation, date shown). "
                "Percent versus close = implied ÷ last official close − 1. KOSPI 200 shares "
                "the official point scale and is compared without conversion. The ADR card is a "
                "premium reference: mark × disclosed ratio (10 ADRs = 1 ordinary) × FX versus "
                "the ordinary close. No kimchi-premium adjustment is applied."
            ),
        },
        "disclaimer": {
            "ko": (
                "표시값은 trade.xyz가 Hyperliquid HIP-3에 상장한 합성 무기한선물을 공식 "
                "환율로 환산한 참고값입니다. 현물 호가, 다음 정규장 시초가 예측, 투자 권유가 "
                "아니며 유동성이 얕은 시장은 왜곡될 수 있습니다."
            ),
            "en": (
                "Values are synthetic trade.xyz perpetuals listed through Hyperliquid HIP-3, "
                "converted at an official exchange rate, for reference only. They are not spot "
                "quotes, next-open forecasts, or investment advice; thin markets can distort them."
            ),
        },
        "source": {
            "perp": {
                "provider": "Hyperliquid HIP-3",
                "publisher": "trade.xyz",
                "dex": OVERNIGHT_DEX,
                "api_url": API_URL,
                "request_type": REQUEST_TYPE,
                "documentation_url": HYPERLIQUID_INFO_DOCS,
                "error": error or snapshot.get("error"),
                "cached": bool(snapshot.get("cached")),
                "stale": bool(snapshot.get("stale")),
                "age_seconds": _number(snapshot.get("age_seconds")),
                "ttl_seconds": OVERNIGHT_CACHE_TTL_SECONDS,
            },
            "official_close": {
                "provider": FSC_PROVIDER_ID,
                "publisher": FSC_PUBLISHER,
                "status": "ok" if fsc_ok else "lane_disabled",
                "stock_dataset_url": FSC_STOCK_DATASET_URL,
                "index_dataset_url": FSC_INDEX_DATASET_URL,
                "publication_note_ko": "기준일 다음 영업일 13시 이후 공개되는 장 마감 확정값",
                "publication_note_en": (
                    "Confirmed closes published after 13:00 KST on the next business day"
                ),
            },
            "fx": {
                "provider": FEDBOARD_PROVIDER_ID,
                "publisher": FEDBOARD_PUBLISHER,
                "series_key": FX_SERIES_KEY,
                "status": fx["status"],
            },
        },
    }
