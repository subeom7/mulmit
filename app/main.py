"""FastAPI 엔트리포인트.

엔드포인트를 async가 아닌 def로 선언한 건 의도적이다. statsmodels/numpy는
동기 블로킹 코드라서 async def 안에서 돌리면 이벤트 루프를 멈춰 세운다.
일반 def로 두면 FastAPI가 알아서 스레드풀로 넘긴다.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import __version__, config, ingest, service, store
from .data import DataUnavailable, RateLimited
from .metrics.correlation import correlation_matrix

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def client_key(request: Request) -> str:
    """Cloudflare 뒤에서도 실제 클라이언트를 식별한다.

    프록시를 그대로 두면 request.client.host가 전부 Cloudflare IP라서
    모든 사용자가 하나의 버킷을 공유한다. CF-Connecting-IP가 먼저다.
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=client_key, default_limits=[config.RATE_LIMIT])


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
    title="Stock Metrics Calculator",
    version=__version__,
    description="티커 하나로 CAPM·낙폭·미래 MDD 확률분포를 계산합니다.",
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
    return FileResponse(config.STATIC_DIR / "index.html")


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
    return {"version": __version__, "provider": config.PROVIDER, **store.stats()}


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
    tickers: str = Query(..., description="쉼표로 구분, 예: AAPL,MSFT,GLD"),
    period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$"),
) -> dict:
    try:
        return service.sanitize(correlation_matrix(tickers.split(","), period=period))
    except RateLimited as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
