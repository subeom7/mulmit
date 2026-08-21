"""Weekend price-discovery references from Hyperliquid HIP-3 perpetuals.

The result distinguishes the rolling ``prevDayPx`` comparison from a true
internal-session move.  Session changes use the last official 5-minute candle
close strictly before the documented internal-pricing boundary when available.
"""

from __future__ import annotations

import copy
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import (
    API_URL,
    CANDLE_REQUEST_TYPE,
    HYPERLIQUID_INFO_DOCS,
    HYPERLIQUID_PERP_DOCS,
    HYPERLIQUID_RATE_LIMIT_DOCS,
    REQUEST_TYPE,
    HyperliquidProvider,
)

SEOUL = ZoneInfo("Asia/Seoul")
NEW_YORK = ZoneInfo("America/New_York")
COMPOSITE_BOUND_PERCENT = 8.0
WEEKEND_PROVIDER_TTL_SECONDS = 300.0
WEEKEND_PROVIDER_STALE_TTL_SECONDS = 1800.0

# Hyperliquid documents a 1,200 weight/minute IP allowance.  Other info calls
# cost 20; candleSnapshot adds 1 per 60 returned items.  Our 24h/5m window has
# at most 288 candles, so a candle costs at most 20 + floor(288/60) = 24.
# A fully populated session needs 2 DEX snapshots and 5 eligible baselines:
# (2 * 20) + (5 * 24) = 160 burst weight, or 32 weight/minute per process over
# this five-minute TTL.  EWY, KORU and USTECH are 24h auxiliaries and therefore
# deliberately consume no candleSnapshot weight.
_DEFAULT_PROVIDER = HyperliquidProvider(
    timeout=2.0,
    retries=0,
    max_request_seconds=2.5,
    ttl=WEEKEND_PROVIDER_TTL_SECONDS,
    stale_ttl=WEEKEND_PROVIDER_STALE_TTL_SECONDS,
)

TRADE_XYZ_KOREA_SESSION_DOCS = "https://docs.trade.xyz/asset-directory/korea"
TRADE_XYZ_EQUITY_INDEX_DOCS = (
    "https://docs.trade.xyz/xyz-perps-specification/equity-perpetuals/"
    "xyz100-and-index-perpetuals"
)
TRADE_XYZ_EXTERNAL_PRICE_DOCS = "https://docs.trade.xyz/perp-mechanics/external-price"


@dataclass(frozen=True)
class Target:
    id: str
    symbol: str
    label_ko: str
    label_en: str
    kind: str
    session_group: str
    session_baseline_supported: bool = True


TARGETS = (
    Target("sk_hynix", "xyz:SKHX", "SK하이닉스", "SK hynix", "korea_equity_perp", "korea"),
    Target(
        "samsung_electronics",
        "xyz:SMSN",
        "삼성전자",
        "Samsung Electronics",
        "korea_equity_perp",
        "korea",
    ),
    Target("kospi_200", "xyz:KR200", "코스피 200", "KOSPI 200", "korea_index_perp", "korea"),
    Target(
        "hyundai_motor",
        "xyz:HYUNDAI",
        "현대자동차",
        "Hyundai Motor",
        "korea_equity_perp",
        "korea",
    ),
    Target(
        "korea_ewy",
        "xyz:EWY",
        "한국 ETF (EWY)",
        "South Korea ETF (EWY)",
        "korea_etf_perp",
        "korea",
        False,
    ),
    Target(
        "korea_koru",
        "xyz:KORU",
        "한국 3배 ETF (KORU)",
        "Daily 3x South Korea ETF (KORU)",
        "leveraged_korea_etf_perp",
        "korea",
        False,
    ),
    Target(
        "xyz_100",
        "xyz:XYZ100",
        "XYZ100 기술주 지수",
        "XYZ100 technology index",
        "technology_index_perp",
        "nasdaq",
    ),
    Target(
        "us_tech",
        "mkts:USTECH",
        "미국 기술주 지수",
        "US technology index",
        "nasdaq_proxy_perp",
        "nasdaq",
        False,
    ),
)

DEXES = tuple(dict.fromkeys(target.symbol.split(":", 1)[0] for target in TARGETS))

_KOREA_COMPONENTS = {
    "kospi_200": (1.00, 1.0),
    "samsung_electronics": (0.40, 1.0),
    "sk_hynix": (0.35, 1.0),
    "hyundai_motor": (0.25, 1.0),
}
_NASDAQ_COMPONENTS = {
    # XYZ100 is the component with a documented external/internal session.
    # USTECH remains visible as a corroborating 24-hour signal, but is not
    # assigned XYZ100's session schedule inside the composite.
    "xyz_100": (1.00, 1.0),
}
_LIQUIDITY_MULTIPLIER = {"high": 1.0, "medium": 0.6, "low": 0.25, "unavailable": 0.0}
_REFERENCE_MULTIPLIER = {"high": 1.0, "medium": 0.75, "low": 0.35, "unavailable": 0.0}


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _iso_utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _local_iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _time_at(moment: datetime, local_time: time) -> datetime:
    return datetime.combine(moment.date(), local_time, tzinfo=moment.tzinfo)


def _next_internal_start(local: datetime, local_time: time, weekdays: set[int]) -> datetime:
    """First internal-session start strictly after ``local`` on an allowed weekday.

    Surfaced so the UI can say *when* the next window opens instead of showing
    an outside-session composite as if its data had failed.
    """
    for offset in range(8):
        candidate = _time_at(local + timedelta(days=offset), local_time)
        if candidate > local and candidate.weekday() in weekdays:
            return candidate
    raise RuntimeError("no internal-session start within a week")  # pragma: no cover


def _korea_weekend_session(moment: datetime) -> dict[str, Any]:
    local = moment.astimezone(SEOUL)
    weekday = local.weekday()
    active = (
        (weekday == 4 and local.time() >= time(20, 0))
        or weekday in {5, 6}
        or (weekday == 0 and local.time() < time(8, 0))
    )
    start: datetime | None = None
    end: datetime | None = None
    if active:
        days_since_friday = {4: 0, 5: 1, 6: 2, 0: 3}[weekday]
        friday = local - timedelta(days=days_since_friday)
        start = _time_at(friday, time(20, 0))
        monday = start + timedelta(days=3)
        end = _time_at(monday, time(8, 0))
    next_start = None if active else _next_internal_start(local, time(20, 0), {4})

    return {
        "id": "korea_weekend_internal",
        "active": active,
        "state": "internal_price_discovery" if active else "outside_weekend_internal_session",
        "timezone": "Asia/Seoul",
        "schedule": "Friday 20:00 through Monday 08:00 KST",
        "start_at": _iso_utc(start) if start is not None else None,
        "end_at": _iso_utc(end) if end is not None else None,
        "local_start": _local_iso(start) if start is not None else None,
        "local_end": _local_iso(end) if end is not None else None,
        "next_start_at": _iso_utc(next_start) if next_start is not None else None,
        "next_local_start": _local_iso(next_start) if next_start is not None else None,
        "baseline_boundary_at": _iso_utc(start) if start is not None else None,
        "official_spec_url": TRADE_XYZ_KOREA_SESSION_DOCS,
    }


def _nasdaq_internal_session(moment: datetime) -> dict[str, Any]:
    """Return the XYZ100 internal window, including its documented daily gap."""
    local = moment.astimezone(NEW_YORK)
    weekday = local.weekday()
    weekend_active = (
        (weekday == 4 and local.time() >= time(17, 0))
        or weekday == 5
        or (weekday == 6 and local.time() < time(18, 0))
    )
    daily_gap_active = weekday in {0, 1, 2, 3} and time(17, 0) <= local.time() < time(18, 0)
    active = weekend_active or daily_gap_active
    start: datetime | None = None
    end: datetime | None = None
    window = "external_reference"
    if weekend_active:
        days_since_friday = {4: 0, 5: 1, 6: 2}[weekday]
        friday = local - timedelta(days=days_since_friday)
        start = _time_at(friday, time(17, 0))
        sunday = start + timedelta(days=2)
        end = _time_at(sunday, time(18, 0))
        window = "weekend_internal"
    elif daily_gap_active:
        start = _time_at(local, time(17, 0))
        end = _time_at(local, time(18, 0))
        window = "daily_internal_gap"
    next_start = None if active else _next_internal_start(local, time(17, 0), {0, 1, 2, 3, 4})
    next_window = (
        None if next_start is None
        else "weekend_internal" if next_start.weekday() == 4
        else "daily_internal_gap"
    )

    return {
        "id": "xyz100_internal",
        "active": active,
        "state": "internal_price_discovery" if active else "external_reference",
        "window": window,
        "timezone": "America/New_York",
        "schedule": (
            "Friday 17:00 through Sunday 18:00 ET; daily external-data gap "
            "17:00-18:00 ET Monday-Thursday"
        ),
        "start_at": _iso_utc(start) if start is not None else None,
        "end_at": _iso_utc(end) if end is not None else None,
        "local_start": _local_iso(start) if start is not None else None,
        "local_end": _local_iso(end) if end is not None else None,
        "next_start_at": _iso_utc(next_start) if next_start is not None else None,
        "next_local_start": _local_iso(next_start) if next_start is not None else None,
        "next_window": next_window,
        "baseline_boundary_at": _iso_utc(start) if start is not None else None,
        "schedule_basis_symbols": ["xyz:XYZ100"],
        "official_spec_url": TRADE_XYZ_EQUITY_INDEX_DOCS,
    }


def _liquidity_status(context: dict[str, Any], day_volume: float | None) -> str:
    if day_volume is None or day_volume <= 0:
        return "unavailable"

    impact = context.get("impactPxs")
    spread_percent: float | None = None
    if isinstance(impact, list) and len(impact) >= 2:
        bid, ask = _number(impact[0]), _number(impact[1])
        if bid is not None and ask is not None and bid > 0 and ask >= bid:
            spread_percent = (ask - bid) / ((ask + bid) / 2.0) * 100.0

    if day_volume >= 1_000_000 and (spread_percent is None or spread_percent <= 0.5):
        return "high"
    if day_volume >= 100_000 and (spread_percent is None or spread_percent <= 1.5):
        return "medium"
    return "low"


def _reference_quality(
    *,
    mark: float | None,
    liquidity: str,
    basis_percent: float | None,
    stale: bool,
    session_active: bool,
    baseline: dict[str, Any] | None,
) -> str:
    if mark is None or liquidity == "unavailable":
        return "unavailable"
    if stale or liquidity == "low" or (basis_percent is not None and abs(basis_percent) > 1.0):
        return "low"
    if session_active and baseline is None:
        return "low"
    if baseline is not None and (
        baseline.get("stale") or baseline.get("proximity_quality") == "low"
    ):
        return "low"
    if (
        liquidity == "medium"
        or (basis_percent is not None and abs(basis_percent) > 0.25)
        or (baseline is not None and baseline.get("proximity_quality") == "medium")
    ):
        return "medium"
    return "high"


def _signal(
    target: Target,
    market: dict[str, Any],
    snapshot: dict[str, Any] | None,
    session: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    context = market.get("context") if isinstance(market.get("context"), dict) else {}
    mark = _number(context.get("markPx"))
    oracle = _number(context.get("oraclePx"))
    previous_24h = _number(context.get("prevDayPx"))
    current_reference = mark if mark is not None else oracle
    change_24h = None
    if current_reference is not None and previous_24h is not None and previous_24h > 0:
        change_24h = (current_reference / previous_24h - 1.0) * 100.0
    day_volume = _number(context.get("dayNtlVlm"))
    liquidity = _liquidity_status(context, day_volume)
    basis_percent = None
    if mark is not None and oracle is not None and oracle > 0:
        basis_percent = (mark / oracle - 1.0) * 100.0

    session_eligible = target.session_baseline_supported
    session_change = None
    if session_eligible and session["active"] and baseline is not None:
        baseline_price = _number(baseline.get("price"))
        if current_reference is not None and baseline_price is not None and baseline_price > 0:
            session_change = (current_reference / baseline_price - 1.0) * 100.0

    snapshot = snapshot or {}
    stale = bool(snapshot.get("stale"))
    quality = _reference_quality(
        mark=current_reference,
        liquidity=liquidity,
        basis_percent=basis_percent,
        stale=stale,
        session_active=bool(session["active"] and session_eligible),
        baseline=baseline,
    )
    if not session_eligible:
        baseline_status = "not_applicable_24h_auxiliary"
    elif not session["active"]:
        baseline_status = "outside_internal_session"
    elif baseline is None:
        baseline_status = "unavailable"
    else:
        baseline_status = "available"

    funding = _number(context.get("funding"))
    return {
        "id": target.id,
        "symbol": target.symbol,
        "label": {"ko": target.label_ko, "en": target.label_en},
        "kind": target.kind,
        "session_role": (
            "internal_session_eligible" if session_eligible else "auxiliary_24h_only"
        ),
        "mark": mark,
        "oracle": oracle,
        "mark_oracle_basis_percent": (
            round(basis_percent, 6) if basis_percent is not None else None
        ),
        "previous_24h": previous_24h,
        "change_24h_percent": round(change_24h, 6) if change_24h is not None else None,
        "session_baseline": copy.deepcopy(baseline),
        "session_baseline_status": baseline_status,
        "session_change_percent": (
            round(session_change, 6) if session_change is not None else None
        ),
        "funding_hourly_rate": funding,
        "funding_hourly_percent": round(funding * 100.0, 8) if funding is not None else None,
        "open_interest_base_units": _number(context.get("openInterest")),
        "day_volume_usd_notional": day_volume,
        "liquidity_status": liquidity,
        "reference_quality": quality,
        "fetched_at": snapshot.get("fetched_at"),
        "as_of": snapshot.get("as_of"),
        "cached": bool(snapshot.get("cached")),
        "stale": stale,
        "age_seconds": _number(snapshot.get("age_seconds")),
        "source_url": f"https://app.hyperliquid.xyz/trade/{quote(target.symbol, safe=':')}",
        "units": {
            "mark": "USDC per contract reference unit",
            "oracle": "USDC per contract reference unit",
            "previous_24h": "USDC per contract reference unit",
            "funding_hourly_rate": "raw decimal rate per one-hour funding interval",
            "funding_hourly_percent": "percent per one-hour funding interval",
            "open_interest_base_units": "base contract units",
            "day_volume_usd_notional": "rolling-day USD/USDC notional reported by dayNtlVlm",
            "percent_fields": "percent",
        },
    }


def _composite(
    signals: list[dict[str, Any]],
    components: dict[str, tuple[float, float]],
    session: dict[str, Any],
) -> dict[str, Any]:
    by_id = {signal["id"]: signal for signal in signals}
    contributions: list[dict[str, Any]] = []

    if session["active"]:
        for signal_id, (base_weight, divisor) in components.items():
            signal = by_id.get(signal_id)
            if signal is None or signal["session_change_percent"] is None:
                continue
            raw_change = float(signal["session_change_percent"])
            normalized_change = raw_change / divisor
            bounded_change = max(
                -COMPOSITE_BOUND_PERCENT,
                min(COMPOSITE_BOUND_PERCENT, normalized_change),
            )
            liquidity_multiplier = _LIQUIDITY_MULTIPLIER.get(signal["liquidity_status"], 0.0)
            reference_multiplier = _REFERENCE_MULTIPLIER.get(signal["reference_quality"], 0.0)
            effective_weight = base_weight * liquidity_multiplier * reference_multiplier
            if effective_weight <= 0:
                continue
            contributions.append(
                {
                    "id": signal_id,
                    "symbol": signal["symbol"],
                    "raw_session_change_percent": round(raw_change, 6),
                    "normalized_session_change_percent": round(normalized_change, 6),
                    "bounded_session_change_percent": round(bounded_change, 6),
                    "leverage_divisor": divisor,
                    "base_weight": base_weight,
                    "liquidity_status": signal["liquidity_status"],
                    "liquidity_multiplier": liquidity_multiplier,
                    "reference_quality": signal["reference_quality"],
                    "reference_multiplier": reference_multiplier,
                    "mark_oracle_basis_percent": signal["mark_oracle_basis_percent"],
                    "stale": signal["stale"],
                    "effective_weight": round(effective_weight, 6),
                }
            )

    weight_sum = sum(item["effective_weight"] for item in contributions)
    value = None
    if weight_sum > 0:
        value = (
            sum(
                item["bounded_session_change_percent"] * item["effective_weight"]
                for item in contributions
            )
            / weight_sum
        )

    available = len(contributions)
    stale_used = any(item["stale"] for item in contributions)
    low_quality_used = any(item["reference_quality"] == "low" for item in contributions)
    if not session["active"]:
        status, evidence_quality = "outside_internal_session", "unavailable"
    elif available == 0:
        status, evidence_quality = "unavailable", "unavailable"
    elif stale_used or low_quality_used:
        status, evidence_quality = "limited", "low"
    elif available == 1 and len(components) == 1:
        status = "ok"
        evidence_quality = contributions[0]["reference_quality"]
    elif available == 1:
        status, evidence_quality = "limited", "low"
    elif available >= 2 and weight_sum >= 1.0:
        status, evidence_quality = "ok", "high"
    else:
        status, evidence_quality = "limited", "medium"

    component_signals = [by_id[item["id"]] for item in contributions]
    ages = [item["age_seconds"] for item in component_signals if item["age_seconds"] is not None]
    as_of_values = [item["as_of"] for item in component_signals if item["as_of"]]
    fetched_values = [item["fetched_at"] for item in component_signals if item["fetched_at"]]

    return {
        "change_percent": round(value, 4) if value is not None else None,
        "change_basis": "mark/oracle fallback versus pre-session official 5m candle close",
        "status": status,
        "evidence_quality": evidence_quality,
        "session": copy.deepcopy(session),
        "available_components": available,
        "expected_components": len(components),
        "stale": stale_used,
        "age_seconds": round(max(ages), 3) if ages else None,
        "as_of": max(as_of_values) if as_of_values else None,
        "fetched_at": max(fetched_values) if fetched_values else None,
        "components": contributions,
        "methodology": {
            "aggregation": "liquidity_and_reference_quality_adjusted_weighted_mean",
            "contribution_bound_percent": COMPOSITE_BOUND_PERCENT,
            "component_scope": "documented direct contracts with eligible session baselines",
            "liquidity_multipliers": dict(_LIQUIDITY_MULTIPLIER),
            "reference_quality_multipliers": dict(_REFERENCE_MULTIPLIER),
            "stale_policy": "stale inputs reduce evidence quality to low",
            "basis_policy": "large mark/oracle basis reduces component reference quality",
        },
    }


def _fetch_dexes_parallel(
    client: HyperliquidProvider,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, str]]:
    snapshots: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(DEXES), thread_name_prefix="hyperliquid-dex") as pool:
        futures = {dex: pool.submit(client.fetch_dex, dex) for dex in DEXES}
        for dex in DEXES:
            try:
                snapshots[dex] = futures[dex].result()
            except RateLimited:
                errors[dex] = "rate_limited"
            except DataUnavailable:
                errors[dex] = "unavailable"

    markets: list[dict[str, Any]] = []
    for dex in DEXES:
        markets.extend(snapshots.get(dex, {}).get("markets", []))
    return markets, snapshots, errors


def _fetch_baselines_parallel(
    client: HyperliquidProvider,
    targets: list[Target],
    sessions: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    eligible = [
        target
        for target in targets
        if sessions[target.session_group]["active"]
        and sessions[target.session_group]["baseline_boundary_at"] is not None
        and target.session_baseline_supported
    ]
    if not eligible:
        return {}, {}

    fetch_baseline = getattr(client, "fetch_session_baseline", None)
    if not callable(fetch_baseline):
        return {}, {target.symbol: "provider_unsupported" for target in eligible}

    def fetch(target: Target) -> dict[str, Any] | None:
        boundary = datetime.fromisoformat(
            sessions[target.session_group]["baseline_boundary_at"].replace("Z", "+00:00")
        )
        return fetch_baseline(target.symbol, boundary, interval="5m")

    baselines: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(
        max_workers=min(8, len(eligible)), thread_name_prefix="hyperliquid-baseline"
    ) as pool:
        futures = {target.symbol: pool.submit(fetch, target) for target in eligible}
        for target in eligible:
            try:
                baseline = futures[target.symbol].result()
                if baseline is None:
                    errors[target.symbol] = "no_pre_session_candle"
                else:
                    baselines[target.symbol] = baseline
            except RateLimited:
                errors[target.symbol] = "rate_limited"
            except DataUnavailable:
                errors[target.symbol] = "unavailable"
    return baselines, errors


def build_weekend_signals(
    provider: HyperliquidProvider | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    client = provider or _DEFAULT_PROVIDER
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)

    markets, dex_snapshots, errors = _fetch_dexes_parallel(client)
    by_symbol = {
        market["symbol"]: market
        for market in markets
        if isinstance(market, dict) and isinstance(market.get("symbol"), str)
        and not (
            isinstance(market.get("metadata"), dict)
            and market["metadata"].get("isDelisted") is True
        )
    }
    sessions = {
        "korea": _korea_weekend_session(moment),
        "nasdaq": _nasdaq_internal_session(moment),
    }
    available_targets = [target for target in TARGETS if target.symbol in by_symbol]
    baselines, baseline_errors = _fetch_baselines_parallel(client, available_targets, sessions)

    signals = []
    for target in TARGETS:
        dex = target.symbol.split(":", 1)[0]
        signals.append(
            _signal(
                target,
                by_symbol.get(target.symbol, {"context": {}}),
                dex_snapshots.get(dex),
                sessions[target.session_group],
                baselines.get(target.symbol),
            )
        )

    local = moment.astimezone(SEOUL)
    calendar_day_type = "weekend" if local.weekday() >= 5 else "weekday"
    korea_active = bool(sessions["korea"]["active"])
    nasdaq_active = bool(sessions["nasdaq"]["active"])
    if korea_active and nasdaq_active:
        market_session = "korea_and_nasdaq_internal_price_discovery"
    elif korea_active:
        market_session = "korea_internal_price_discovery"
    elif nasdaq_active:
        market_session = "nasdaq_internal_price_discovery"
    else:
        market_session = "external_reference"
    snapshot_values = list(dex_snapshots.values())
    source_ages = [
        value for item in snapshot_values if (value := _number(item.get("age_seconds"))) is not None
    ]
    source_as_of = [item["as_of"] for item in snapshot_values if item.get("as_of")]
    source_fetched = [item["fetched_at"] for item in snapshot_values if item.get("fetched_at")]

    return {
        "generated_at": _iso_utc(moment),
        # Preserve the former weekday/weekend signal under an accurate name.
        # ``market_session`` remains a string for consumer compatibility, but
        # now derives from the same detailed sessions returned in composites.
        "calendar_day_type": calendar_day_type,
        "market_session": market_session,
        "signals": signals,
        "composites": {
            "korea_weekend": _composite(signals, _KOREA_COMPONENTS, sessions["korea"]),
            "nasdaq_weekend": _composite(signals, _NASDAQ_COMPONENTS, sessions["nasdaq"]),
        },
        "disclaimer": {
            "ko": (
                "이 값은 현물가격이나 월요일 시초가 예측이 아니라 Hyperliquid HIP-3 합성 "
                "무기한선물의 내부 가격발견 참고 신호입니다. 얕은 유동성, 레버리지, "
                "마크-오라클 괴리와 가격발견 제한 때문에 크게 왜곡될 수 있습니다. EWY와 "
                "KORU는 한국 KST 세션 기준선이나 합성값에 넣지 않는 24시간 보조지표입니다."
            ),
            "en": (
                "These are internal price-discovery references from synthetic Hyperliquid HIP-3 "
                "perpetuals, not spot prices or Monday-open forecasts. Thin liquidity, leverage, "
                "mark-oracle basis, and discovery bounds can materially distort them. EWY and "
                "KORU are rolling-24h auxiliaries excluded from the Korea KST-session baseline "
                "and composite."
            ),
        },
        "source": {
            "provider": "Hyperliquid HIP-3",
            "api_url": API_URL,
            "request_types": [REQUEST_TYPE, CANDLE_REQUEST_TYPE],
            "dexes": list(DEXES),
            "errors": errors,
            "baseline_errors": baseline_errors,
            "cached_dexes": [item["dex"] for item in snapshot_values if item.get("cached")],
            "stale_dexes": [item["dex"] for item in snapshot_values if item.get("stale")],
            "fetched_at": max(source_fetched) if source_fetched else None,
            "as_of": max(source_as_of) if source_as_of else None,
            "stale": any(item.get("stale") for item in snapshot_values),
            "age_seconds": round(max(source_ages), 3) if source_ages else None,
            "rolling_24h_change_basis": (
                "markPx (oraclePx fallback) versus prevDayPx; explicitly separate from "
                "internal-session change"
            ),
            "session_change_basis": (
                "markPx (oraclePx fallback) versus the final official 5m candle close strictly "
                "before the active internal-session boundary; null when unavailable"
            ),
            "session_baseline_scope": {
                "korea_direct_contracts": [
                    "xyz:KR200",
                    "xyz:SMSN",
                    "xyz:SKHX",
                    "xyz:HYUNDAI",
                ],
                "rolling_24h_auxiliaries": ["xyz:EWY", "xyz:KORU", "mkts:USTECH"],
            },
            "upstream_cache": {
                "scope": "per process",
                "ttl_seconds": WEEKEND_PROVIDER_TTL_SECONDS,
                "stale_if_error_seconds": WEEKEND_PROVIDER_STALE_TTL_SECONDS,
                "maximum_active_session_requests": 7,
                "metadata_weight_each": 20,
                "candle_base_weight_each": 20,
                "candle_additional_weight_per_60_items": 1,
                "maximum_candle_items": 288,
                "maximum_candle_weight_each": 24,
                "maximum_burst_weight": 160,
                "steady_state_weight_per_minute_per_process": 32,
                "official_ip_limit_weight_per_minute": 1200,
            },
            "liquidity_methodology": {
                "high": "day volume >= $1m and impact spread <= 0.5% when available",
                "medium": "day volume >= $100k and impact spread <= 1.5% when available",
                "low": "positive volume below those thresholds or wider impact spread",
                "unavailable": "missing or non-positive day volume",
            },
            "official_docs": {
                "hyperliquid_info": HYPERLIQUID_INFO_DOCS,
                "hyperliquid_perpetuals": HYPERLIQUID_PERP_DOCS,
                "hyperliquid_rate_limits": HYPERLIQUID_RATE_LIMIT_DOCS,
                "trade_xyz_korea_sessions": TRADE_XYZ_KOREA_SESSION_DOCS,
                "trade_xyz_equity_index_sessions": TRADE_XYZ_EQUITY_INDEX_DOCS,
                "trade_xyz_external_price": TRADE_XYZ_EXTERNAL_PRICE_DOCS,
            },
        },
    }
