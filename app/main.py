"""FastAPI 엔트리포인트.

엔드포인트를 async가 아닌 def로 선언한 건 의도적이다. statsmodels/numpy는
동기 블로킹 코드라서 async def 안에서 돌리면 이벤트 루프를 멈춰 세운다.
일반 def로 두면 FastAPI가 알아서 스레드풀로 넘긴다.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import __version__, config, data_rights, ingest, kr_insider, kr_stocks, service, store
from .data import DataUnavailable, RateLimited
from .insider_filings import (
    DEFAULT_TRANSACTIONS,
    MAX_PUBLIC_TRANSACTIONS,
    InsiderDataDisabled,
    build_insider_report,
)
from .macro_dashboard import MacroDataDisabled, build_macro_series, build_macro_snapshot
from .market_assets import build_asset_snapshot
from .market_sectors import build_sector_snapshot
from .metrics.correlation import correlation_matrix
from .stress_index import StressIndexUnavailable, build_stress_index
from .weekend_signals import build_weekend_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def client_key(request: Request) -> str:
    """Use the client address sanitized by the reverse proxy.

    Caddy overwrites ``X-Forwarded-For`` with its immediate peer, preventing a
    public client from creating arbitrary rate-limit buckets with spoofed
    forwarding headers. Cloudflare mode requires explicit proxy trust in Caddy.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_key, default_limits=[config.RATE_LIMIT])

_LEGACY_PRICE_DATA_DISABLED = {
    "code": "legacy_price_data_disabled",
    "message": (
        "Legacy Yahoo price data is disabled while Mulmit migrates to a "
        "licensed market-data provider."
    ),
}


def require_legacy_price_data() -> None:
    if not config.LEGACY_PRICE_DATA_ENABLED:
        raise HTTPException(status_code=503, detail=_LEGACY_PRICE_DATA_DISABLED)


def require_hip3_public_display() -> None:
    """Withhold Hyperliquid HIP-3 values until redistribution rights are confirmed."""
    if not data_rights.hip3_public_display_enabled():
        raise HTTPException(
            status_code=503,
            detail=data_rights.HIP3_PENDING_RIGHTS,
            headers=dict(data_rights.NO_STORE_HEADERS),
        )


def _macro_data_source() -> str:
    """Name the lanes that actually produced the response, not a fixed provider."""
    return ",".join(lane.upper() for lane in data_rights.enabled_macro_lanes())


def macro_disabled_response() -> HTTPException:
    """A disabled lane must never be cached by a proxy as if it were content."""
    return HTTPException(
        status_code=503,
        detail=data_rights.MACRO_DATA_DISABLED,
        headers=dict(data_rights.NO_STORE_HEADERS),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.init_db()
    log.info("저장소 준비 완료: %s", store.stats())
    stop = ingest.start_background()
    try:
        yield
    finally:
        if stop is not None:
            stop.set()


app = FastAPI(
    title="Mulmit Market Intelligence",
    version=__version__,
    description=(
        "S&P 500 섹터 흐름과 개별 종목의 CAPM·낙폭·미래 MDD 확률분포를 "
        "제공합니다. / S&P 500 sector trends and stock risk analytics."
    ),
    lifespan=lifespan,
)
app.state.limiter = limiter
# 가격 시계열이 수천 포인트라 압축이 체감된다
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요. ({exc.detail})"},
    )


if config.STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "monitor.html")


@app.get("/monitor", include_in_schema=False)
def market_monitor() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "monitor.html")


@app.get("/analytics", include_in_schema=False)
def stock_analytics() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/privacy", include_in_schema=False)
def privacy_policy() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "privacy.html")


@app.get("/terms", include_in_schema=False)
def terms_of_use() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "terms.html")


@app.get("/disclaimer", include_in_schema=False)
def disclaimer() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "disclaimer.html")


@app.get("/api/health")
def health() -> dict:
    """로드밸런서·배포 스크립트용. DB까지 확인해야 의미가 있다."""
    try:
        store.load_macro("riskfree")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"저장소 연결 실패: {exc}") from exc
    return {"status": "ok", "version": __version__}


@app.get("/api/status")
def status() -> dict:
    """운영용 요약. 수집이 돌고 있는지 여기서 본다."""
    legacy_enabled = config.LEGACY_PRICE_DATA_ENABLED
    return {
        "version": __version__,
        "provider": config.PROVIDER if legacy_enabled else "disabled",
        "legacy_provider": config.PROVIDER,
        "legacy_price_data_enabled": legacy_enabled,
        # Row counts alone hide the important fact: stored rows from a closed
        # lane are never served, so operators need both numbers side by side.
        "data_lanes": data_rights.lane_report(),
        **store.stats(),
    }


@app.get("/api/market/sectors")
@limiter.limit(config.RATE_LIMIT)
def market_sectors(request: Request) -> dict:
    """저장된 11개 섹터 ETF로 일·주·월·연 히트맵 스냅샷을 만든다."""
    require_legacy_price_data()
    return build_sector_snapshot()


@app.get("/api/market/assets")
@limiter.limit(config.RATE_LIMIT)
def market_assets(
    request: Request,
    response: Response,
    history: str = Query("3y", pattern="^(1y|2y|3y|5y|max)$"),
) -> dict:
    """Live global and Korean synthetic-perpetual proxies from Hyperliquid HIP-3."""
    require_hip3_public_display()
    response.headers["Cache-Control"] = "private, max-age=30, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid HIP-3"
    return build_asset_snapshot(history)


@app.get("/api/market/weekend")
@limiter.limit(config.RATE_LIMIT)
def market_weekend(request: Request, response: Response) -> dict:
    """Hyperliquid HIP-3 synthetic-perpetual weekend price-discovery signals."""
    require_hip3_public_display()
    response.headers["Cache-Control"] = "private, max-age=15, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid HIP-3"
    return build_weekend_signals()


@app.get("/api/market/macro")
@limiter.limit(config.RATE_LIMIT)
def market_macro(
    request: Request,
    response: Response,
    history: str = Query("3y", pattern="^(1y|2y|3y|5y|10y|max)$"),
) -> dict:
    """거시·유동성·스트레스 카드와 차트. 승인된 lane의 저장소만 읽는다."""
    try:
        payload = build_macro_snapshot(history)
    except MacroDataDisabled as exc:
        raise macro_disabled_response() from exc
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = _macro_data_source()
    return payload


@app.get("/api/market/macro/{series_id}")
@limiter.limit(config.RATE_LIMIT)
def market_macro_series(
    series_id: str,
    request: Request,
    response: Response,
    history: str = Query("3y", pattern="^(1y|2y|3y|5y|10y|max)$"),
) -> dict:
    """단일 거시 시계열 상세. 공급자 네트워크 호출은 하지 않는다."""
    try:
        payload = build_macro_series(series_id, history)
    except MacroDataDisabled as exc:
        raise macro_disabled_response() from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="지원하지 않는 거시 시계열입니다.") from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="아직 수집된 거시 데이터가 없습니다.")
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = _macro_data_source()
    return payload


@app.get("/api/market/stress")
@limiter.limit(config.RATE_LIMIT)
def market_stress(request: Request, response: Response) -> dict:
    """Mulmit 자체 유동성·스트레스 지수. 저장소만 읽는다."""
    try:
        payload = build_stress_index()
    except StressIndexUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stress_index_unavailable",
                "status": "insufficient_inputs",
                "message": (
                    f"Only {exc.available} of {exc.required} licensed inputs are "
                    "available, so no index is published."
                ),
            },
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "Mulmit composite"
    return payload


@app.get("/api/kr/search")
@limiter.limit(config.RATE_LIMIT)
def kr_stock_search(
    request: Request,
    response: Response,
    q: str = Query(..., min_length=1, max_length=40),
    limit: int = Query(10, ge=1, le=25),
) -> dict:
    """국내 상장 종목 이름·코드 검색. 로컬 로스터만 읽는다.

    로스터는 금융위원회 주식시세정보의 하루치 스냅샷이며, 타이핑마다 외부
    API를 부르지 않는다. 최초 부팅 직후 로스터가 비어 있을 때만 한 번 채운다.
    """
    try:
        payload = kr_stocks.search(q, limit)
    except kr_stocks.KrStockDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail=data_rights.KR_STOCK_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except (DataUnavailable, RateLimited) as exc:
        # 최초 로스터 수집이 실패한 극히 드문 경우. 다음 요청이 다시 시도한다.
        raise HTTPException(status_code=503, detail="listing roster unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "Financial Services Commission (data.go.kr)"
    return payload


@app.get("/api/kr/indices")
@limiter.limit(config.RATE_LIMIT)
def kr_index_family(request: Request, response: Response) -> dict:
    """코스피 지수군 표. 하루치 지수 스냅샷만 읽는다.

    스냅샷 한 번이 전 지수의 종가·전일대비·연초대비·52주 범위·거래대금을
    담고 있어, 이 표를 위해 지수별 이력을 수집하지 않는다.
    """
    try:
        payload = kr_stocks.index_family()
    except kr_stocks.KrStockDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail=data_rights.KR_STOCK_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except (kr_stocks.KrIndexUnavailable, DataUnavailable, RateLimited) as exc:
        raise HTTPException(status_code=503, detail="index snapshot unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "Financial Services Commission (data.go.kr)"
    return payload


@app.get("/api/kr/stock/{code}")
@limiter.limit(config.RATE_LIMIT)
def kr_stock_analysis(code: str, request: Request, response: Response) -> dict:
    """국내 종목 하나의 종가 이력과 낙폭·변동성 통계.

    저장소를 먼저 읽고, 미수집 종목만 잠금 아래에서 한 번 즉시 수집한다 —
    시간당 배치를 기다리게 하면 검색이 죽은 기능이 되기 때문이다. 이후의
    모든 요청은 DB 읽기다.
    """
    code = code.strip().upper()
    if not (4 <= len(code) <= 12) or not code.isalnum():
        raise HTTPException(status_code=422, detail="code must be a KRX issue code")
    try:
        payload = kr_stocks.get_analysis(code)
    except kr_stocks.KrStockDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail=data_rights.KR_STOCK_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except kr_stocks.KrStockUnknown as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "kr_stock_unknown", "message": f"{code} is not a known KRX issue"},
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "Financial Services Commission (data.go.kr)"
    return payload


@app.get("/api/kr/insider/{code}")
@limiter.limit(config.RATE_LIMIT)
def kr_insider_reports(code: str, request: Request, response: Response) -> dict:
    """국내 임원·주요주주 소유상황 보고(DART). 캐시 우선, 미스에서만 단발 조회."""
    code = code.strip().upper()
    if not (4 <= len(code) <= 12) or not code.isalnum():
        raise HTTPException(status_code=422, detail="code must be a KRX issue code")
    try:
        payload = kr_insider.get_reports(code)
    except kr_insider.KrInsiderDisabled as exc:
        detail = (
            data_rights.KR_INSIDER_NOT_CONFIGURED
            if exc.reason == "not_configured"
            else data_rights.KR_INSIDER_DISABLED
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    except kr_insider.KrInsiderUnknown as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "kr_insider_unknown", "message": f"{code} is not a DART-listed issue"},
        ) from exc
    except (DataUnavailable, RateLimited) as exc:
        raise HTTPException(status_code=503, detail="DART reports unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "FSS DART"
    return payload


@app.get("/api/insider/{ticker}")
@limiter.limit(config.RATE_LIMIT)
def insider_filings(
    ticker: str,
    request: Request,
    response: Response,
    limit: int = Query(DEFAULT_TRANSACTIONS, ge=1, le=MAX_PUBLIC_TRANSACTIONS),
) -> dict:
    """SEC EDGAR Form 3/4/5 지분공시. 저장소만 읽는다.

    수집되지 않은 티커는 EDGAR를 즉석에서 부르지 않고 `queued` 상태로 답한 뒤
    다음 수집 주기가 가져간다.
    """
    if not ticker.strip():
        raise HTTPException(status_code=422, detail="ticker is required")
    try:
        payload = build_insider_report(ticker, limit)
    except InsiderDataDisabled as exc:
        detail = (
            data_rights.INSIDER_NOT_CONFIGURED
            if exc.reason == "not_configured"
            else data_rights.INSIDER_DATA_DISABLED
        )
        raise HTTPException(
            status_code=503,
            detail=detail,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    # Short cache only: a queued ticker becomes collected on the next cycle and
    # a stale answer would hide that.
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "SEC EDGAR"
    return payload


@app.get("/api/metrics")
@limiter.limit(config.RATE_LIMIT_HEAVY)
def metrics(
    request: Request,
    ticker: str = Query(..., min_length=1, max_length=20, description="예: AAPL, 005930.KS"),
    horizon: int = Query(
        config.DEFAULT_HORIZON_MONTHS, ge=1, le=60, description="예측 구간(개월)"
    ),
    sims: int = Query(config.DEFAULT_SIMS, ge=200, le=config.MAX_SIMS),
    drift: str = Query("historical", pattern="^(historical|zero|capm|custom)$"),
    drift_value: float | None = Query(None, ge=-0.9, le=2.0, description="drift=custom일 때 연 수익률"),
    lookback: int = Query(config.DEFAULT_LOOKBACK_YEARS, ge=1, le=50, description="분석 기간(년)"),
    series: bool = Query(True, description="차트용 시계열 포함 여부"),
) -> dict:
    require_legacy_price_data()
    try:
        return service.build_report(
            ticker,
            horizon_months=horizon,
            n_sims=sims,
            drift_mode=drift,
            custom_annual_drift=drift_value,
            lookback_years=lookback,
            include_series=series,
        )
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - 상세는 로그로, 사용자에겐 일반 메시지
        log.exception("metrics 실패: %s", ticker)
        raise HTTPException(status_code=500, detail=f"계산 중 오류가 발생했습니다: {exc}") from exc


@app.get("/api/correlation")
@limiter.limit(config.RATE_LIMIT_HEAVY)
def correlation(
    request: Request,
    tickers: str = Query(
        ...,
        min_length=3,
        max_length=263,
        pattern=r"^[A-Za-z0-9.^=_\-, ]+$",
        description="쉼표로 구분한 최대 12개 티커, 예: AAPL,MSFT,GLD",
    ),
    period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$"),
) -> dict:
    require_legacy_price_data()
    try:
        return service.sanitize(correlation_matrix(tickers.split(","), period=period))
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
