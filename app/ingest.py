"""가격 수집 배치.

요청 경로에서 분리된 유일한 야후 호출 지점이다. 여기서 느리게, 천천히,
실패해도 되게 받아 온다. 사용자는 store만 보므로 이 배치가 몇 번 실패해도
서비스 응답은 변하지 않는다.

실행:
    python -m app.ingest              # 1회 실행하고 종료
    python -m app.ingest --loop       # 상주하며 INGEST_INTERVAL마다 반복
    python -m app.ingest AAPL MSFT    # 특정 티커만

배포에서는 docker compose의 별도 서비스로 --loop을 띄우고, 웹 컨테이너는
INGEST_ENABLED=false로 둔다. **수집 프로세스는 하나여야 한다** — 여럿이면
같은 티커를 중복으로 받아 레이트리밋을 자초한다.
"""

from __future__ import annotations

import argparse
import logging
import threading
import time

from . import config, data, store
from .market_assets import ASSET_TICKERS, CORRELATION_TICKERS
from .providers import DataUnavailable, RateLimited, get_provider
from .providers.fred import FRED_SERIES, FredProvider
from .providers.sec_edgar import SecEdgarProvider

log = logging.getLogger(__name__)


def _backoff_remaining() -> float:
    """레이트리밋 후 남은 대기 시간(초)."""
    until = store.load_macro("ingest_backoff_until")
    return max(0.0, (until or 0.0) - time.time())


def _apply_backoff() -> float:
    """레이트리밋을 맞았다. 다음 시도까지 간격을 배로 늘린다.

    막힌 상태에서 매 주기 계속 노크하면 밴이 풀리지 않고 연장된다.
    실패가 이어질수록 물러섰다가, 한 번 성공하면 즉시 원상복구한다.
    """
    level = (store.load_macro("ingest_backoff_level") or 0.0) + 1
    level = min(level, 6)  # 2^6 = 64배에서 상한
    wait = min(config.INGEST_INTERVAL * (2**level), config.INGEST_BACKOFF_MAX)
    store.save_macro("ingest_backoff_level", level)
    store.save_macro("ingest_backoff_until", time.time() + wait)
    log.warning("레이트리밋 %d회째 — %.0f분 쉬었다가 재시도", level, wait / 60)
    return wait


def _clear_backoff() -> None:
    if store.load_macro("ingest_backoff_level"):
        log.info("수집 정상화 — 백오프 해제")
    store.save_macro("ingest_backoff_level", 0)
    store.save_macro("ingest_backoff_until", 0)


def _refresh_macro() -> None:
    if not config.LEGACY_PRICE_DATA_ENABLED:
        return
    if store.load_macro("riskfree", config.MACRO_MAX_AGE) is not None:
        return
    try:
        store.save_macro("riskfree", get_provider().fetch_risk_free_rate())
        log.info("무위험 수익률 갱신 완료")
    except Exception as exc:
        log.warning("무위험 수익률 갱신 실패: %s", exc)


def refresh_fred(*, force: bool = False) -> dict:
    """Refresh configured FRED series independently from the price provider.

    A missing key disables only this lane. The legacy price lane is independently
    configurable and disabled by default. API responses later read only the database.
    """
    if not config.FRED_ENABLED:
        return {"skipped": "disabled", "attempted": 0, "updated": 0, "failed": 0}
    if not config.FRED_API_KEY:
        return {"skipped": "not_configured", "attempted": 0, "updated": 0, "failed": 0}

    # FRED carries some third-party series whose owners prohibit public
    # redistribution. Keep them in the UI catalog as license-required cards,
    # but never download them for the public dashboard without a separate
    # licensed feed.
    ids = [spec.series_id for spec in FRED_SERIES if spec.public_web]
    targets = ids if force else store.stale_fred_series(ids, config.FRED_MAX_AGE)
    if not targets:
        return {"skipped": "fresh", "attempted": 0, "updated": 0, "failed": 0}

    provider = FredProvider(
        config.FRED_API_KEY,
        timeout=config.FRED_TIMEOUT,
        retries=config.FRED_RETRIES,
    )
    specs = {spec.series_id: spec for spec in FRED_SERIES}
    result = {
        "attempted": 0,
        "updated": 0,
        "failed": 0,
        "rate_limited": 0,
        "observations": 0,
    }

    for series_id in targets:
        if result["attempted"] and config.FRED_INGEST_DELAY > 0:
            time.sleep(config.FRED_INGEST_DELAY)
        result["attempted"] += 1
        spec = specs[series_id]
        try:
            fetched = provider.fetch_series(series_id)
            count = store.save_fred_series(
                series_id,
                fetched.metadata,
                fetched.observations,
                publisher=spec.publisher,
                publisher_url=spec.publisher_url,
                series_url=spec.series_url,
            )
            result["updated"] += 1
            result["observations"] += count
            log.info("FRED 갱신 %s (%d행)", series_id, count)
        except RateLimited:
            result["rate_limited"] += 1
            log.warning("FRED 레이트리밋 — 남은 시리즈는 다음 주기에 재시도")
            break
        except Exception as exc:  # 한 시리즈 오류가 나머지 수집을 막지 않는다
            result["failed"] += 1
            store.mark_fred_error(series_id, str(exc))
            log.warning("FRED 갱신 실패 %s: %s", series_id, exc)
    return result


def refresh_insider_filings(*, force: bool = False) -> dict:
    """Refresh SEC EDGAR ownership filings for the watchlist and searched tickers.

    Independent of every price lane: EDGAR is a public federal disclosure system
    and needs no vendor key, only a declared contact and a request budget.
    """
    if not config.SEC_EDGAR_ENABLED:
        return {"skipped": "disabled", "attempted": 0, "updated": 0, "failed": 0}
    if not config.SEC_EDGAR_USER_AGENT:
        return {"skipped": "not_configured", "attempted": 0, "updated": 0, "failed": 0}

    max_age = 0 if force else config.SEC_EDGAR_MAX_AGE
    targets = store.stale_insider_tickers(
        config.SEC_EDGAR_TICKERS, max_age, config.SEC_EDGAR_BATCH_SIZE
    )
    if not targets:
        return {"skipped": "fresh", "attempted": 0, "updated": 0, "failed": 0}

    provider = SecEdgarProvider(
        config.SEC_EDGAR_USER_AGENT,
        timeout=config.SEC_EDGAR_TIMEOUT,
        retries=config.SEC_EDGAR_RETRIES,
        request_interval=config.SEC_EDGAR_REQUEST_INTERVAL,
    )
    result = {
        "attempted": 0,
        "updated": 0,
        "failed": 0,
        "unknown": 0,
        "rate_limited": 0,
        "transactions": 0,
    }

    try:
        ticker_map = provider.fetch_ticker_map()
    except RateLimited:
        return {"skipped": "rate_limited", "attempted": 0, "updated": 0, "failed": 0}
    except Exception as exc:  # noqa: BLE001 - one outage must not crash the batch
        log.warning("EDGAR 티커 매핑 실패: %s", exc)
        return {"skipped": "ticker_map_unavailable", "attempted": 0, "updated": 0, "failed": 0}

    for ticker in targets:
        result["attempted"] += 1
        entry = ticker_map.get(ticker)
        if entry is None:
            # Not an EDGAR filer: a foreign listing, an ETF or a typo. Remember it
            # so the batch stops retrying, and let the API say so.
            result["unknown"] += 1
            store.mark_insider_error(ticker, "not listed in EDGAR company tickers", status="unavailable")
            continue
        cik, name = entry
        try:
            company = provider.fetch_company(cik, form_limit=config.SEC_EDGAR_FILING_LIMIT)
            saved = store.save_insider_filings(
                ticker,
                cik=company.cik,
                name=company.name or name,
                exchange=company.exchanges[0] if company.exchanges else None,
                filings_seen=company.filings_seen,
                transactions=[
                    {
                        "accession_number": item.accession_number,
                        "sequence": item.sequence,
                        "form_type": item.form_type,
                        "filing_date": item.filing_date,
                        "transaction_date": item.transaction_date,
                        "owner_name": item.owner_name,
                        "owner_cik": item.owner_cik,
                        "owner_title": item.owner_title,
                        "is_director": item.is_director,
                        "is_officer": item.is_officer,
                        "is_ten_percent_owner": item.is_ten_percent_owner,
                        "security_title": item.security_title,
                        "transaction_code": item.transaction_code,
                        "acquired_disposed": item.acquired_disposed,
                        "is_derivative": item.is_derivative,
                        "shares": item.shares,
                        "price_per_share": item.price_per_share,
                        "shares_owned_after": item.shares_owned_after,
                        "direct_or_indirect": item.direct_or_indirect,
                        "filing_url": item.filing_url,
                    }
                    for item in company.transactions
                ],
            )
            result["updated"] += 1
            result["transactions"] += saved
            log.info("EDGAR 갱신 %s (%d행 / 공시 %d건)", ticker, saved, company.filings_seen)
        except RateLimited:
            result["rate_limited"] += 1
            log.warning("EDGAR 요청 제한 — 남은 티커는 다음 주기에 재시도")
            break
        except Exception as exc:  # noqa: BLE001 - 한 티커 실패가 나머지를 막지 않는다
            result["failed"] += 1
            store.mark_insider_error(ticker, str(exc))
            log.warning("EDGAR 갱신 실패 %s: %s", ticker, exc)
    return result


def _targets(explicit: list[str] | None) -> list[str]:
    if not config.LEGACY_PRICE_DATA_ENABLED:
        return []
    if explicit:
        return [t.strip().upper() for t in explicit if t.strip()]

    # 시장지수와 시드는 조회 여부와 무관하게 항상 최신이어야 한다.
    # CAPM이 시장지수 없이는 아예 계산되지 않기 때문이다.
    pinned = [
        config.MARKET_TICKER,
        *config.SECTOR_ETF_TICKERS,
        *ASSET_TICKERS,
        *CORRELATION_TICKERS,
        *config.SEED_TICKERS,
    ]
    stale = store.stale_tickers(config.PRICE_MAX_AGE, config.INGEST_BATCH_SIZE)

    ordered: list[str] = []
    for ticker in [*pinned, *stale]:
        if ticker not in ordered:
            ordered.append(ticker)
    # 여기서 자르면 고정 대상 수가 INGEST_BATCH_SIZE보다 클 때 뒤쪽 ETF가
    # 영원히 선택되지 않는다. run_once가 이미 최신인 앞쪽 대상을 건너뛴 뒤
    # 실제 시도 횟수만 제한해야 여러 배치에 걸쳐 전부 순환한다.
    return ordered


def run_once(tickers: list[str] | None = None) -> dict:
    """한 바퀴 돈다. 개별 티커 실패는 삼키고 계속 진행한다."""
    store.init_db()
    started = time.time()
    automatic = not tickers
    fred_result = {"skipped": "explicit_price_refresh"}

    # FRED is an independent licensed lane. Public deployments can therefore
    # keep macro data fresh without constructing or calling the legacy Yahoo
    # provider at all.
    if not config.LEGACY_PRICE_DATA_ENABLED:
        insider_result = {"skipped": "explicit_price_refresh"}
        if automatic:
            fred_result = refresh_fred()
            insider_result = refresh_insider_filings()
        purged = store.purge_reports(config.REPORT_TTL * 2)
        result = {
            "skipped": "legacy_price_data_disabled",
            "attempted": 0,
            "updated": 0,
            "missing": 0,
            "failed": 0,
            "rate_limited": 0,
            "purged_reports": purged,
            "fred": fred_result,
            "insider": insider_result,
            "elapsed": round(time.time() - started, 2),
        }
        log.info("레거시 가격 수집 비활성화: %s", result)
        return result

    # 티커를 명시했으면(수동 실행) 백오프를 무시한다
    if not tickers:
        waiting = _backoff_remaining()
        if waiting > 0:
            # Price-provider backoff must not disable the independent FRED lane.
            fred_result = refresh_fred()
            insider_result = refresh_insider_filings()
            log.info("백오프 중 — %.0f분 후 재개", waiting / 60)
            return {
                "skipped": "backoff",
                "resume_in": round(waiting),
                "fred": fred_result,
                "insider": insider_result,
            }

    _refresh_macro()

    targets = _targets(tickers)
    result = {"attempted": 0, "updated": 0, "missing": 0, "failed": 0, "rate_limited": 0}

    for ticker in targets:
        # 필요 없는 갱신은 건너뛴다(핀 티커가 방금 갱신된 경우 등)
        record = store.get_instrument(ticker)
        if (
            automatic
            and record
            and record.get("prices_updated_at")
            and time.time() - record["prices_updated_at"] < config.PRICE_MAX_AGE
        ):
            continue

        if automatic and result["attempted"] >= config.INGEST_BATCH_SIZE:
            break

        if result["attempted"] and config.INGEST_DELAY > 0:
            time.sleep(config.INGEST_DELAY)

        result["attempted"] += 1
        try:
            rows = data.refresh_ticker(ticker)
            result["updated"] += 1
            log.info("갱신 %s (%d행)", ticker, rows)
        except DataUnavailable as exc:
            result["missing"] += 1
            log.info("없는 티커 %s: %s", ticker, exc)
        except RateLimited:
            # 지금 막혔으면 이번 바퀴는 접는다. 계속 두드려 봐야 더 막힌다.
            result["rate_limited"] += 1
            result["backoff_seconds"] = round(_apply_backoff())
            break
        except Exception:
            result["failed"] += 1
            log.exception("갱신 실패 %s", ticker)

    if result["updated"]:
        _clear_backoff()

    # Price data is the latency-sensitive lane. Refresh FRED afterwards so a
    # slow macro-provider outage cannot postpone all ticker updates.
    insider_result = {"skipped": "explicit_price_refresh"}
    if automatic:
        fred_result = refresh_fred()
        insider_result = refresh_insider_filings()

    purged = store.purge_reports(config.REPORT_TTL * 2)
    result["purged_reports"] = purged
    result["fred"] = fred_result
    result["insider"] = insider_result
    result["elapsed"] = round(time.time() - started, 2)
    log.info("수집 완료: %s", result)
    return result


def run_forever(stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            run_once()
        except Exception:
            log.exception("수집 루프에서 예외 발생, 다음 주기에 재시도")
        stop.wait(config.INGEST_INTERVAL)


def start_background() -> threading.Event | None:
    """앱과 함께 도는 수집 스레드. 단일 프로세스일 때만 쓴다."""
    if not config.INGEST_ENABLED:
        log.info("INGEST_ENABLED=false — 내장 수집 스레드를 띄우지 않는다")
        return None

    stop = threading.Event()
    thread = threading.Thread(
        target=run_forever, args=(stop,), name="ingest", daemon=True
    )
    thread.start()
    log.info("내장 수집 스레드 시작 (%d초 주기)", config.INGEST_INTERVAL)
    return stop


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="가격 데이터 수집 배치")
    parser.add_argument("tickers", nargs="*", help="지정하면 이 티커만 갱신")
    parser.add_argument("--loop", action="store_true", help="상주하며 반복 실행")
    args = parser.parse_args()

    if args.loop:
        run_forever()
        return 0

    result = run_once(args.tickers or None)
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
