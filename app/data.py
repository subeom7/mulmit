"""서비스가 데이터를 얻는 유일한 창구.

**저장소 우선.** store에 있으면 그걸 쓰고, 없을 때만 공급자를 부른다.
조금 오래된 데이터는 그냥 내보낸다 — 갱신은 배치(ingest.py)의 일이다.
일봉은 하루 한 번 바뀌는데 그것 때문에 사용자를 7초씩 세워 둘 이유가 없고,
야후가 막혀 있는 동안에도 서비스는 멀쩡히 돌아야 한다.

공급자를 직접 부르는 경우는 딱 하나, **처음 보는 티커**뿐이다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

import pandas as pd

from . import config, store
from .providers import DataError, DataUnavailable, RateLimited, get_provider

log = logging.getLogger(__name__)

__all__ = [
    "DataError",
    "DataUnavailable",
    "RateLimited",
    "get_close",
    "get_info",
    "get_market_close",
    "get_risk_free_rate",
    "refresh_ticker",
]

# 같은 티커에 동시 요청이 몰려도 공급자는 한 번만 부른다. 대시보드를
# 여러 탭에서 열거나 새로고침을 연타할 때 실제로 발생한다.
_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(ticker: str) -> threading.Lock:
    with _locks_guard:
        return _locks[ticker]


def normalize(ticker: str) -> str:
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise DataUnavailable("티커가 비어 있습니다.")
    return ticker


def _fetch_and_store(ticker: str, record: dict | None) -> pd.Series:
    """공급자에서 받아 저장하고 돌려준다. 락 안에서만 호출한다."""
    provider = get_provider()
    start = None
    if record and record.get("last_date"):
        start = record["last_date"]

    try:
        close = provider.fetch_prices(ticker, start=start)
    except DataUnavailable as exc:
        # 증분 갱신에서 빈 응답은 "새 거래일이 없다"는 뜻이다(주말·휴장·장중).
        # 이걸 없는 티커로 오해하면 멀쩡한 종목이 네거티브 캐시에 갇혀서
        # 배치가 일요일에 도는 것만으로 서비스가 404를 뱉는다.
        if start is not None:
            existing = store.load_close(ticker)
            if existing is not None:
                store.mark_checked(ticker)
                return existing
        store.mark_unavailable(ticker, str(exc))
        raise
    except RateLimited as exc:
        # 저장된 게 있으면 그거라도 내보낸다.
        existing = store.load_close(ticker)
        if existing is not None:
            log.warning("레이트리밋, 저장된 가격으로 대체: %s", ticker)
            return existing
        # 없으면 429다. 다만 "야후가 제한 중"이라는 원문은 이 상황을 설명하지
        # 못한다 — 사용자 입장에선 방금 처음 입력한 종목이 안 나오는 것이다.
        raise RateLimited(
            f"'{ticker}'는 아직 수집되지 않은 종목인데 지금 데이터 공급자가 "
            "요청을 제한하고 있습니다. 잠시 후 다시 시도해 주세요."
        ) from exc

    store.save_prices(ticker, close)

    # 증분 갱신이었다면 방금 받은 꼬리만 저장했으므로 전체를 다시 읽는다
    if start is not None:
        merged = store.load_close(ticker)
        if merged is not None:
            return merged
    return close


def get_close(ticker: str) -> pd.Series:
    """조정 종가 전체 이력. 저장소 우선, 없으면 1회 수집."""
    ticker = normalize(ticker)
    record = store.get_instrument(ticker)

    # 없는 티커로 판명난 지 얼마 안 됐으면 공급자를 두드리지 않는다
    if record and record.get("status") == "unavailable":
        age = time.time() - (record.get("prices_updated_at") or 0)
        if age < config.NEGATIVE_TTL:
            raise DataUnavailable(record.get("error") or f"'{ticker}'를 찾을 수 없습니다.")

    close = store.load_close(ticker)
    if close is not None:
        store.touch_request(ticker)
        return close

    with _lock_for(ticker):
        # 락을 기다리는 동안 다른 스레드가 채웠을 수 있다
        close = store.load_close(ticker)
        if close is None:
            log.info("최초 수집: %s", ticker)
            close = _fetch_and_store(ticker, store.get_instrument(ticker))

    store.touch_request(ticker)
    return close


def get_info(ticker: str) -> dict:
    """회사 정보. 저장소에만 의존한다 — 없으면 빈 dict로도 서비스는 돈다."""
    ticker = normalize(ticker)
    record = store.get_instrument(ticker)
    if record and record.get("info_updated_at"):
        return store.info_dict(record)

    # 가격은 있는데 info가 비어 있는 상태(최초 수집 직후)만 여기 온다
    with _lock_for(ticker):
        record = store.get_instrument(ticker)
        if record and record.get("info_updated_at"):
            return store.info_dict(record)
        try:
            info = get_provider().fetch_info(ticker)
        except Exception:
            log.warning("info 수집 실패: %s", ticker, exc_info=True)
            return store.info_dict(record)
        if info:
            store.save_info(ticker, info)
    return store.info_dict(store.get_instrument(ticker))


def get_risk_free_rate() -> float:
    """무위험 수익률 = 미 10년물 금리. 저장소 → 공급자 → 설정값 순."""
    value = store.load_macro("riskfree")
    if value is not None:
        return value
    try:
        value = get_provider().fetch_risk_free_rate()
        store.save_macro("riskfree", value)
        return value
    except Exception:
        log.warning("무위험 수익률 폴백 사용: %.4f", config.FALLBACK_RISKFREE)
        return config.FALLBACK_RISKFREE


def get_market_close() -> pd.Series:
    """시장 지수(기본 S&P 500) 종가."""
    return get_close(config.MARKET_TICKER)


def refresh_ticker(ticker: str) -> int:
    """배치용 강제 갱신. 저장된 행 수를 돌려준다."""
    ticker = normalize(ticker)
    with _lock_for(ticker):
        record = store.get_instrument(ticker)
        close = _fetch_and_store(ticker, record)
        if not record or not record.get("info_updated_at"):
            try:
                info = get_provider().fetch_info(ticker)
                if info:
                    store.save_info(ticker, info)
            except Exception:
                log.warning("info 갱신 실패: %s", ticker, exc_info=True)
    return len(close)
