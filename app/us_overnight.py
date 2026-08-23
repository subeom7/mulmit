"""미국 대형주, 장 밖에서는 — HIP-3 합성 무기한선물 참고가.

`/kr`의 "한국 주식, 장 밖에서는"과 같은 생각이다. 다만 두 가지가 다르다.

  통화    원래 USD다. 원화로 되돌릴 이유가 없고, 환산하면 환율 변동이 종목
          움직임인 것처럼 섞여 들어간다.
  노출    **미국 현물장이 닫혀 있을 때만 보여 준다.** 장이 열려 있는 동안에는
          진짜 나스닥 호가가 있고, 그때 이 합성 퍼프를 나란히 두면 나은 게
          없으면서 "실시간 주가"로 오해만 부른다. 이 값이 유일한 정보가 되는
          시간에만 선다.

기준선은 마지막 정규장 마감(16:00 America/New_York)이다. 주말은 시계로,
휴장일은 `market_calendar.nyse_closed`로 건너뛴다 — 휴일 다음 날 아침에
"퍼프만 움직인 마감"을 기준으로 삼지 않기 위해서다.
"""

from __future__ import annotations

import datetime as dt
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from . import config, market_calendar
from .providers.base import DataUnavailable, RateLimited
from .providers.hyperliquid import HyperliquidProvider

NEW_YORK = ZoneInfo("America/New_York")
OVERNIGHT_DEX = "xyz"

# 정규장 마감. 시간외는 기준으로 쓰지 않는다 — 공표되는 종가가 이 시각이다.
SESSION_CLOSE_HOUR = 16
SESSION_CLOSE_MINUTE = 0
# 정규장 개장. 이 사이에는 이 섹션을 내린다.
SESSION_OPEN_HOUR = 9
SESSION_OPEN_MINUTE = 30

SESSION_BOUNDARY_SLACK = dt.timedelta(seconds=30)
SESSION_REF_RETRY_SECONDS = 120.0
# 24h 거래대금이 이보다 얕으면 카드에 경고를 붙인다. 한국 카드와 같은 뜻의
# 문턱이며, 값은 이 dex의 미국 종목 실측 분포에서 잡았다(2026-08-23: 상위
# NVDA $12M, 하위 ORCL $0.46M).
LOW_LIQUIDITY_USD = 1_000_000.0


class DexProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class UsOvernightTarget:
    id: str
    symbol: str
    ticker: str
    label_ko: str
    label_en: str


# 두꺼운 것만 고른다. 얇은 마켓은 주말에 한 번의 체결로 몇 퍼센트가 튀고,
# 그걸 카드로 세우면 신호가 아니라 잡음을 크게 보여 주는 셈이 된다.
TARGETS = (
    UsOvernightTarget("nvda", "xyz:NVDA", "NVDA", "엔비디아", "NVIDIA"),
    UsOvernightTarget("googl", "xyz:GOOGL", "GOOGL", "알파벳", "Alphabet"),
    UsOvernightTarget("meta", "xyz:META", "META", "메타", "Meta"),
    UsOvernightTarget("tsla", "xyz:TSLA", "TSLA", "테슬라", "Tesla"),
    UsOvernightTarget("aapl", "xyz:AAPL", "AAPL", "애플", "Apple"),
    UsOvernightTarget("msft", "xyz:MSFT", "MSFT", "마이크로소프트", "Microsoft"),
)

_DEFAULT_PROVIDER = HyperliquidProvider(
    timeout=2.5, retries=0, max_request_seconds=3.0, ttl=5, stale_ttl=120
)
_BASELINE_PROVIDER = HyperliquidProvider(
    timeout=4.0, retries=1, max_request_seconds=6.0, ttl=6 * 3600, stale_ttl=24 * 3600
)

_session_refs_memo: dict[str, Any] = {"boundary": None, "refs": {}, "failed_at": {}}


def enabled() -> bool:
    """가격 표시 게이트를 그대로 따른다 — 같은 원천, 같은 권리 조건이다."""
    return bool(config.HIP3_PUBLIC_DISPLAY_ENABLED)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _iso_utc(moment: dt.datetime | None = None) -> str:
    return (moment or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def market_open(moment: dt.datetime) -> bool:
    """뉴욕 정규장이 열려 있나. 휴장일은 달력으로 본다."""
    local = moment.astimezone(NEW_YORK)
    if local.weekday() >= 5 or market_calendar.nyse_closed(local.date()):
        return False
    opens = local.replace(hour=SESSION_OPEN_HOUR, minute=SESSION_OPEN_MINUTE, second=0, microsecond=0)
    closes = local.replace(hour=SESSION_CLOSE_HOUR, minute=SESSION_CLOSE_MINUTE, second=0, microsecond=0)
    return opens <= local < closes


def session_boundary(moment: dt.datetime) -> dt.datetime:
    """``moment`` 직전의 마지막 정규장 마감(16:00 ET)."""
    local = moment.astimezone(NEW_YORK)
    boundary = local.replace(
        hour=SESSION_CLOSE_HOUR, minute=SESSION_CLOSE_MINUTE, second=0, microsecond=0
    )
    if boundary >= local:
        boundary -= dt.timedelta(days=1)
    while boundary.weekday() >= 5 or market_calendar.nyse_closed(boundary.date()):
        boundary -= dt.timedelta(days=1)
    return boundary


def _session_refs(client: Any, boundary: dt.datetime, *, use_memo: bool) -> dict[str, dict[str, Any]]:
    """경계 시각의 퍼프 가격. 경계당 한 번만 받고, 실패는 백오프한다.

    5초 폴링 경로에서 도는 코드라 상류 장애가 지연으로 번지면 안 된다.
    """
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
        target for target in TARGETS
        if target.symbol not in memo["refs"]
        and (
            memo["failed_at"].get(target.symbol) is None
            or now_mono - memo["failed_at"][target.symbol] >= SESSION_REF_RETRY_SECONDS
        )
    ]
    if pending:
        slack = boundary + SESSION_BOUNDARY_SLACK
        with ThreadPoolExecutor(
            max_workers=min(8, len(pending)), thread_name_prefix="uso-session-ref"
        ) as pool:
            futures = {
                target.symbol: pool.submit(fetch_baseline, target.symbol, slack, interval="5m")
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


def _card(
    target: UsOvernightTarget,
    market: dict[str, Any] | None,
    reference: dict[str, Any] | None,
    boundary: dt.datetime,
) -> dict[str, Any]:
    context = (market or {}).get("context") or {}
    mark = _number(context.get("markPx")) or _number(context.get("oraclePx"))
    previous = _number(context.get("prevDayPx"))
    volume = _number(context.get("dayNtlVlm"))
    open_interest = _number(context.get("openInterest"))
    change_24h = None if mark is None or not previous else round((mark / previous - 1.0) * 100.0, 4)

    # 프로바이더는 이 값을 `price`로 준다(캔들 종가). `close`가 아니다.
    ref_price = _number((reference or {}).get("price"))
    vs_percent = (
        None if mark is None or not ref_price else round((mark / ref_price - 1.0) * 100.0, 4)
    )
    return {
        "id": target.id,
        "symbol": target.symbol,
        "ticker": target.ticker,
        "label": {"ko": target.label_ko, "en": target.label_en},
        "status": "ok" if mark is not None else "unavailable",
        "price": {"value": mark, "currency": "USD", "field": "markPx"},
        "change_24h": {"percent": change_24h, "reference": previous},
        # 마지막 정규장 마감 이후 얼마나 움직였나. 이 섹션의 존재 이유다.
        "session_reference": {
            "status": "ok" if vs_percent is not None else "unavailable",
            "vs_percent": vs_percent,
            "close": ref_price,
            "quality": (reference or {}).get("proximity_quality"),
            "boundary_et": _iso_utc(boundary),
        },
        "volume_24h_usd": volume,
        "open_interest": open_interest,
        "liquidity_status": (
            "unavailable" if volume is None else "low" if volume < LOW_LIQUIDITY_USD else "ok"
        ),
    }


def build_us_overnight(
    provider: DexProvider | None = None,
    *,
    baseline_provider: Any | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    client = provider or _DEFAULT_PROVIDER
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
    boundary = session_boundary(moment)
    is_open = market_open(moment)

    payload: dict[str, Any] = {
        "generated_at": _iso_utc(moment),
        "session": {
            "market_open": is_open,
            "boundary_et": _iso_utc(boundary),
            "basis": (
                "미국 정규장(09:30–16:00 America/New_York) 시계 기준. 휴장일은 NYSE 달력을 따르며, "
                "조기 폐장은 반영하지 않습니다."
            ),
        },
        "cards": [],
        "source": {
            "provider": "Hyperliquid HIP-3",
            "publisher": "trade.xyz",
            "dex": OVERNIGHT_DEX,
            "api_url": "https://api.hyperliquid.xyz/info",
            "request_type": "metaAndAssetCtxs",
        },
        "methodology": {
            "ko": (
                "표시값은 trade.xyz가 Hyperliquid HIP-3에 상장한 합성 무기한선물의 마크가격입니다(USD, 환산 없음). "
                "마감 이후 % = 마크가격 ÷ 마지막 정규장 마감(16:00 ET) 시점의 마크가격 − 1. "
                "종가가 아니라 그 시각의 퍼프 가격과 견준 값입니다."
            ),
            "en": (
                "Values are mark prices of synthetic perpetuals listed by trade.xyz on Hyperliquid HIP-3 "
                "(USD, no conversion). Change since the close compares the mark now with the mark at the "
                "last regular-session close (16:00 ET) — against the perp at that moment, not the official close."
            ),
        },
        "disclaimer": {
            "ko": (
                "현물 호가가 아니며 다음 정규장 시초가를 예측하지 않습니다. 유동성이 얕은 시장은 "
                "한 번의 체결로 크게 튈 수 있습니다. 투자 권유가 아닙니다."
            ),
            "en": (
                "Not a spot quote and not a prediction of the next session's open. Thin markets can move "
                "sharply on a single fill. Not investment advice."
            ),
        },
    }
    # 장이 열려 있으면 값을 만들지 않는다. 이 섹션은 장 밖의 참고가이고,
    # 열려 있는 동안에는 진짜 호가가 있다.
    if is_open:
        payload["status"] = "market_open"
        return payload

    error: str | None = None
    snapshot: dict[str, Any] = {}
    try:
        snapshot = client.fetch_dex(OVERNIGHT_DEX)
    except RateLimited:
        error = "rate_limited"
    except DataUnavailable:
        error = "unavailable"

    markets = {
        market["symbol"]: market
        for market in (snapshot.get("markets") or [])
        if isinstance(market, dict) and isinstance(market.get("symbol"), str)
    }
    refs = {} if error else _session_refs(baseline_client, boundary, use_memo=use_memo)
    payload["status"] = error or "ok"
    payload["as_of"] = snapshot.get("as_of") or snapshot.get("fetched_at")
    payload["cards"] = [
        _card(target, markets.get(target.symbol), refs.get(target.symbol), boundary)
        for target in TARGETS
    ]
    return payload
