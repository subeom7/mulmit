"""Korean around-the-clock reference prices against the last official close.

The one number this section exists for: how far the HIP-3 synthetic perpetual
has moved since the last confirmed Korea Exchange close.  Equity marks are
quoted in USD, so they are converted through the latest official won/dollar
rate before the comparison; the KR200 index perpetual trades on the same point
scale as the official KOSPI 200 close and is compared directly, no FX involved.

Three lanes meet here and each keeps its own gate: the route refuses entirely
while HIP-3 public display is off, official closes disappear when the FSC lane
closes, and the conversion disappears when the FX series may not be served.
A missing input nulls the fields that depend on it — nothing is estimated.
The rate is the daily official quotation (BOK ECOS trading-reference rate), not a live
rate, so both the FX date and the close date travel with every derived value.
"""

from __future__ import annotations

import datetime as dt
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from . import data_rights, market_calendar, store
from .macro_dashboard import PROVIDER_NAMES
from .providers.base import DataUnavailable, RateLimited
from .providers.ecos import ECOS_PROVIDER_ID
from .providers.fedboard import FEDBOARD_PROVIDER_ID
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
# 짧게 잡아 홈 카드가 체감 실시간으로 움직이게 한다. 상류 호출은 이 TTL이
# 프로세스당 분당 12회로 캡을 씌우므로 방문자 수와 무관하다(공식 한도 대비 미미).
OVERNIGHT_CACHE_TTL_SECONDS = 5.0
OVERNIGHT_STALE_TTL_SECONDS = 300.0
FX_SERIES_KEY = "fx_usdkrw"
# Official daily quotations (with holiday gaps); beyond this window the stored
# tail is a data problem worth surfacing as "unavailable", not a usable rate.
FX_LOOKBACK_DAYS = 45
KR_INDEX_CLASS = "KOSPI시리즈"
KR200_INDEX_NAME = "코스피 200"
KST = dt.timezone(dt.timedelta(hours=9), "KST")
# 정규장 마감 시각. 공식 종가는 다음 영업일 13시에나 나오므로, 그 공백 동안
# "직전 15:30 시점의 퍼프 5분봉 종가"를 참고 기준선으로 쓴다. 시계 기준
# 평일 판정이라 휴장일은 반영하지 못한다 — 그 한계는 문구로 동봉한다.
SESSION_CLOSE_HOUR = 15
SESSION_CLOSE_MINUTE = 30
# 경계에 정확히 걸린 캔들(T=15:30:00.000)이 벤더의 종료시각 표기 방식과 무관하게
# 포함되도록 30초 여유를 두고 조회한다. 다음 5분봉은 15:35에나 닫히므로 안전하다.
SESSION_BOUNDARY_SLACK = dt.timedelta(seconds=30)
SESSION_REF_RETRY_SECONDS = 120.0

_DEFAULT_PROVIDER = HyperliquidProvider(
    timeout=2.5,
    retries=0,
    max_request_seconds=3.0,
    ttl=OVERNIGHT_CACHE_TTL_SECONDS,
    stale_ttl=OVERNIGHT_STALE_TTL_SECONDS,
)

# 기준선 캔들은 경계가 하루 한 번 바뀌므로 시세와 TTL을 분리한다. 캐시 키에
# 캔들 창(start/end)이 포함되어 경계가 넘어가면 자연히 새로 받는다.
_BASELINE_PROVIDER = HyperliquidProvider(
    timeout=2.5,
    retries=0,
    max_request_seconds=3.0,
    ttl=6 * 3600.0,
    stale_ttl=24 * 3600.0,
)


class DexProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class OvernightTarget:
    id: str
    symbol: str
    kind: str  # "equity" | "index" | "adr" | "us_etf"
    code: str | None
    label_ko: str
    label_en: str
    # ADR 전용: 원주 1주가 몇 ADR인지. 발행사 공시로 검증된 값만 넣는다.
    adr_per_ordinary: int | None = None
    # us_etf 전용: 레버리지 배수. 1이 아닌 값은 카드에 경고 배지로 나간다.
    leverage: int | None = None


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
    # 미국 상장 한국 노출 ETF 퍼프 (2026-08-18 xyz 신규 상장 확인). USD 자산이라
    # 원화 환산·공식 종가 비교가 없다 — 15:30 세션 참고선(퍼프 자기 비교)만 성립.
    OvernightTarget("ewy", "xyz:EWY", "us_etf", None, "EWY (한국 ETF)", "EWY (Korea ETF)"),
    OvernightTarget(
        "koru", "xyz:KORU", "us_etf", None, "KORU (3×)", "KORU (3×)", leverage=3,
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


def _last_session_boundary(moment: dt.datetime) -> dt.datetime:
    """The most recent KRX trading day's 15:30 KST strictly before ``moment``.

    Weekends by clock, holidays by the curated calendar — so on the morning
    after a holiday the baseline points at the last day KRX actually traded,
    not at a 15:30 when only the perp moved.
    """
    local = moment.astimezone(KST)
    boundary = local.replace(
        hour=SESSION_CLOSE_HOUR, minute=SESSION_CLOSE_MINUTE, second=0, microsecond=0
    )
    if boundary >= local:
        boundary -= dt.timedelta(days=1)
    while boundary.weekday() >= 5 or market_calendar.krx_closed(boundary.date()):
        boundary -= dt.timedelta(days=1)
    return boundary


# 프로세스 수명 동안 경계당 한 번만 캔들을 받도록 하는 메모. 실패한 심볼은
# 백오프 후에만 재시도해, 상류 장애가 5초 폴링 경로의 지연으로 번지지 않게 한다.
# 단일 uvicorn 프로세스 전제의 관대한 동시성(중복 조회 허용, GIL 원자성 의존)이다.
_session_refs_memo: dict[str, Any] = {"boundary": None, "refs": {}, "failed_at": {}}


def _session_refs(
    client: Any, boundary: dt.datetime, *, use_memo: bool
) -> dict[str, dict[str, Any]]:
    fetch_baseline = getattr(client, "fetch_session_baseline", None)
    if not callable(fetch_baseline):
        return {}
    memo = _session_refs_memo if use_memo else {"boundary": None, "refs": {}, "failed_at": {}}
    key = boundary.isoformat()
    if memo["boundary"] != key:
        memo["boundary"] = key
        memo["refs"] = {}
        memo["failed_at"] = {}
    now_mono = time.monotonic()
    pending = [
        target
        for target in TARGETS
        if target.symbol not in memo["refs"]
        and (
            memo["failed_at"].get(target.symbol) is None
            or now_mono - memo["failed_at"][target.symbol] >= SESSION_REF_RETRY_SECONDS
        )
    ]
    if pending:
        slack_boundary = boundary + SESSION_BOUNDARY_SLACK
        with ThreadPoolExecutor(
            max_workers=min(8, len(pending)), thread_name_prefix="kro-session-ref"
        ) as pool:
            futures = {
                target.symbol: pool.submit(
                    fetch_baseline, target.symbol, slack_boundary, interval="5m"
                )
                for target in pending
            }
            for target in pending:
                try:
                    baseline = futures[target.symbol].result()
                except (RateLimited, DataUnavailable):
                    memo["failed_at"][target.symbol] = now_mono
                    continue
                if baseline is None:
                    memo["failed_at"][target.symbol] = now_mono
                else:
                    memo["refs"][target.symbol] = baseline
                    memo["failed_at"].pop(target.symbol, None)
    return memo["refs"]


def _session_reference_block(
    target: OvernightTarget,
    perp: dict[str, Any] | None,
    ref: dict[str, Any] | None,
    fx: dict[str, Any],
    boundary: dt.datetime,
) -> dict[str, Any] | None:
    """Perp-versus-its-own-15:30-candle move; FX cancels out of the percent."""
    if perp is None:
        return None
    basis_ko = (
        "가장 최근 거래일 15:30(KST) 직전 퍼프 5분봉 종가 대비 변동률 — 공식 종가가 "
        f"아닌 참고값입니다. 휴장일은 큐레이션 달력(확인 {market_calendar.CURATED_VERIFIED_AT}) 기준."
    )
    basis_en = (
        "Move versus the perp's own 5-minute candle close just before the most recent "
        "trading day's 15:30 KST — a reference, not an official close. Holidays follow "
        f"a curated calendar (verified {market_calendar.CURATED_VERIFIED_AT})."
    )
    block: dict[str, Any] = {
        "status": "unavailable",
        "boundary_kst": boundary.isoformat(),
        "mark": None,
        "implied_value": None,
        "unit": "pt" if target.kind == "index" else "KRW",
        "vs_percent": None,
        "proximity_quality": None,
        "candle_close_at": None,
        "interval": "5m",
        "basis_ko": basis_ko,
        "basis_en": basis_en,
    }
    ref_price = _number(ref.get("price")) if ref else None
    if ref is None or ref_price is None or ref_price <= 0:
        return block
    block["mark"] = ref_price
    block["proximity_quality"] = ref.get("proximity_quality")
    block["candle_close_at"] = ref.get("candle_close_at")
    # 현재 마크 ÷ 경계 시점 마크 − 1: 양쪽에 같은 환율이 곱해지므로 환산 없이
    # 성립하는 순수 퍼프 변동률이다. FX·FSC lane이 닫혀도 이 수치는 산다.
    block["vs_percent"] = round((perp["mark"] / ref_price - 1.0) * 100.0, 4)
    if target.kind == "index":
        block["implied_value"] = ref_price
    elif fx["status"] == "ok":
        block["implied_value"] = ref_price * (target.adr_per_ordinary or 1) * fx["rate"]
    # 경계에서 2시간 넘게 떨어진 캔들이 마지막이라면 그 시장은 그때 이미 얇았다는
    # 뜻이라, 값은 주되 상태로 구분해 UI가 숨길 수 있게 한다.
    block["status"] = "low_proximity" if ref.get("proximity_quality") == "low" else "ok"
    return block


def _fsc_servable() -> bool:
    return data_rights.series_values_servable(
        FSC_PROVIDER_ID, data_rights.SERVABLE_ROW_RIGHTS
    )


# What the rate is depends on which lane stored it, so the description follows
# the row instead of being asserted here. This block used to name the Federal
# Reserve as publisher while the text described the Bank of Korea — the lane had
# moved to ECOS and the constant had not, and nothing checked.
_FX_BASIS: dict[str, dict[str, str]] = {
    ECOS_PROVIDER_ID: {
        "ko": (
            "한국은행 ECOS 원/달러 매매기준율(일별 공식 고시) — 실시간 환율이 아닙니다. "
            "매매기준율은 정의상 직전 영업일 거래의 거래량가중평균이라, 표기된 날짜의 "
            "시장 환율보다 하루 늦게 움직입니다."
        ),
        "en": (
            "Daily official won/dollar trading-reference rate from the Bank of Korea's "
            "ECOS; not a live exchange rate. By definition it is the volume-weighted "
            "average of the previous business day's trades, so it trails the market rate "
            "of the date shown by about a day."
        ),
    },
    FEDBOARD_PROVIDER_ID: {
        "ko": (
            "미 연방준비제도 H.10 원/달러 환율(일별) — 실시간 환율이 아니며, "
            "뉴욕 시각 정오 매수호가 기준으로 주간 단위로 공표됩니다."
        ),
        "en": (
            "Daily won/dollar rate from the Federal Reserve's H.10 release; not a live "
            "exchange rate. It is a noon buying rate in New York, published weekly."
        ),
    },
}
_FX_BASIS_UNKNOWN = {
    "ko": "일별 공식 고시 환율 — 실시간 환율이 아닙니다.",
    "en": "An official daily quotation, not a live exchange rate.",
}


def _fx_source(record: dict[str, Any] | None) -> tuple[str, str, str, str]:
    """Provider id, publisher name and the basis text that belongs to that lane."""
    provider = str((record or {}).get("provider_id") or "") or ECOS_PROVIDER_ID
    basis = _FX_BASIS.get(provider, _FX_BASIS_UNKNOWN)
    return provider, PROVIDER_NAMES.get(provider) or provider, basis["ko"], basis["en"]


def _load_fx() -> dict[str, Any]:
    """Latest stored official won/dollar rate, or an honest unavailable block.

    Same double gate as the stress composite: the stored series row names its
    provider and rights status, and both must pass before the value ships.
    """
    record = store.get_economic_series(FX_SERIES_KEY)
    provider_id, publisher, basis_ko, basis_en = _fx_source(record)
    unavailable = {
        "status": "unavailable",
        "rate": None,
        "date": None,
        "series_key": FX_SERIES_KEY,
        "provider": provider_id,
        "publisher": publisher,
        "basis_ko": basis_ko,
        "basis_en": basis_en,
    }
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
        "provider": provider_id,
        "publisher": publisher,
        "basis_ko": basis_ko,
        "basis_en": basis_en,
    }


def _next_trading_day(day: dt.date) -> dt.date:
    following = day + dt.timedelta(days=1)
    while following.weekday() >= 5 or market_calendar.krx_closed(following):
        following += dt.timedelta(days=1)
    return following


def _mark_close_lag(official: dict[str, Any], boundary: dt.datetime) -> None:
    """Say so when the close on the card is older than the last session that traded.

    The public dataset publishes a session's close after 13:00 KST on the next
    business day, so from Friday's close until Monday lunchtime the newest close
    we may serve is Thursday's — while every other quote screen is already
    comparing against Friday. The card already carries dates, but a reader
    comparing platforms needs to know the gap is a publication schedule and not
    a disagreement about the price.
    """
    if official.get("status") != "ok" or not official.get("date"):
        return
    try:
        stored = dt.date.fromisoformat(str(official["date"]))
    except ValueError:
        return
    last_session = boundary.date()
    official["last_session_date"] = last_session.isoformat()
    official["behind_last_session"] = stored < last_session
    if stored >= last_session:
        return
    publish = _next_trading_day(last_session)
    official["publication_note_ko"] = (
        f"{last_session.month}/{last_session.day} 종가는 "
        f"{publish.month}/{publish.day} 13시(KST) 이후 공개됩니다"
    )
    official["publication_note_en"] = (
        f"The {last_session.isoformat()} close is published after 13:00 KST on "
        f"{publish.isoformat()}"
    )


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
    if target.kind == "us_etf":
        # 미국 상장 자산 — 이 섹션의 기준가 체계(FSC 종가) 밖이다.
        base["status"] = "not_applicable"
        return base
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
    session_ref: dict[str, Any] | None,
    boundary: dt.datetime,
) -> dict[str, Any]:
    perp = _perp_block(market, snapshot, target.symbol)
    official = _official_close(target, fsc_ok)
    _mark_close_lag(official, boundary)

    implied: dict[str, Any] = {
        "status": "unavailable",
        "value": None,
        "unit": "pt" if target.kind == "index" else "KRW",
        "fx_applied": target.kind != "index",
        "vs_official_percent": None,
    }
    if perp is not None:
        if target.kind == "us_etf":
            # USD 표시 그대로 — 원화 환산이 의미를 갖지 않는 자산이다.
            implied["fx_applied"] = False
        elif target.kind in ("equity", "adr"):
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
    elif target.kind == "us_etf":
        status = "reference_only"
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
        "leverage": target.leverage,
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
        "session_reference": _session_reference_block(target, perp, session_ref, fx, boundary),
        "basis": {
            "ko": (
                "미국 상장 한국 노출 ETF 퍼프 — 원화 환산·공식 종가 비교 없음, 직전 거래일 15:30 대비만 참고"
                if target.kind == "us_etf"
                else "지수 무기한선물 마크(포인트)를 코스피 200 공식 종가와 직접 비교"
                if target.kind == "index"
                else "ADR 퍼프 마크 × 비율 × 공식 고시환율을 원주 마지막 공식 종가와 비교"
                if target.kind == "adr"
                else "합성 무기한선물 마크가격 × 공식 고시환율을 마지막 공식 종가와 비교"
            ),
            "en": (
                "US-listed Korea-exposure ETF perp — no KRW conversion or official-close comparison; only the 15:30 session reference applies"
                if target.kind == "us_etf"
                else "Index-perpetual mark (points) compared directly with the official KOSPI 200 close"
                if target.kind == "index"
                else "ADR-perpetual mark × ratio × the official published rate versus the ordinary share's last official close"
                if target.kind == "adr"
                else "Synthetic-perpetual mark × the official published rate versus the last official close"
            ),
        },
    }


def build_kr_overnight(
    provider: DexProvider | None = None,
    *,
    baseline_provider: Any | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    client = provider or _DEFAULT_PROVIDER
    # 시세(5초 TTL)와 기준선 캔들(6시간 TTL)은 캐시 수명이 달라 프로바이더를
    # 나눈다. 테스트가 provider 하나만 주입하면 그걸로 둘 다 처리하고 메모는 끈다.
    if baseline_provider is not None:
        baseline_client = baseline_provider
    elif provider is not None:
        baseline_client = provider
    else:
        baseline_client = _BASELINE_PROVIDER
    use_memo = baseline_client is _BASELINE_PROVIDER
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
    boundary = _last_session_boundary(moment)
    session_refs = (
        _session_refs(baseline_client, boundary, use_memo=use_memo) if error is None else {}
    )
    cards = [
        _card(
            target,
            markets.get(target.symbol.casefold()),
            snapshot,
            fx,
            fsc_ok,
            session_refs.get(target.symbol),
            boundary,
        )
        for target in TARGETS
    ]
    available = sum(1 for card in cards if card["status"] in ("ok", "reference_only"))

    # 오늘의 휴장 여부를 프런트가 세션 문구·배지에 쓴다. 시계는 각 거래소의
    # 타임존 기준이고, 휴장일 판정은 큐레이션 달력이 맡는다.
    kst_today = moment.astimezone(KST).date()
    ny_today = moment.astimezone(dt.timezone(dt.timedelta(hours=-5))).date()
    try:
        from zoneinfo import ZoneInfo

        ny_today = moment.astimezone(ZoneInfo("America/New_York")).date()
    except Exception:  # noqa: BLE001 - tz 데이터 없는 환경은 고정 오프셋 근사로
        pass

    return {
        "generated_at": _iso_utc(),
        "as_of": snapshot.get("as_of") or snapshot.get("fetched_at"),
        "session": _korea_weekend_session(moment),
        "market_days": {
            "date_kst": kst_today.isoformat(),
            "krx_closed_today": market_calendar.krx_closed(kst_today),
            "nyse_closed_today": market_calendar.nyse_closed(ny_today),
            "calendar_verified_at": market_calendar.CURATED_VERIFIED_AT,
        },
        "fx": fx,
        "cards": cards,
        "coverage": {"available": available, "total": len(cards)},
        "methodology": {
            "ko": (
                "환산가 = 마크가격 × 원/달러(공식 고시 환율, 날짜 표기). 기준가 대비 % = "
                "환산가 ÷ 마지막 공식 종가 − 1. 코스피 200은 포인트 단위가 같아 환산 없이 "
                "직접 비교합니다. ADR 카드는 마크 × 공시 비율(10 ADR = 원주 1주) × 환율을 원주 종가와 비교한 프리미엄 참고값입니다. 김치프리미엄 조정은 하지 않습니다. "
                "공식 종가가 아직 전전일이면 직전 거래일 15:30 시점 퍼프 5분봉 종가 대비 변동률을 "
                "참고로 함께 표시합니다(공식 종가 아님, 휴장일은 큐레이션 달력 기준)."
            ),
            "en": (
                "Implied price = mark × won/dollar (official quotation, date shown). "
                "Percent versus close = implied ÷ last official close − 1. KOSPI 200 shares "
                "the official point scale and is compared without conversion. The ADR card is a "
                "premium reference: mark × disclosed ratio (10 ADRs = 1 ordinary) × FX versus "
                "the ordinary close. No kimchi-premium adjustment is applied. While the official "
                "close lags, the move versus the perp's own 5-minute candle close at the most "
                "recent trading day's 15:30 KST is shown as a reference (not an official close; "
                "holidays follow a curated calendar)."
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
                "provider": fx.get("provider") or ECOS_PROVIDER_ID,
                "publisher": fx.get("publisher"),
                "series_key": FX_SERIES_KEY,
                "status": fx["status"],
            },
        },
    }
