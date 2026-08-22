"""FastAPI 엔트리포인트.

엔드포인트를 async가 아닌 def로 선언한 건 의도적이다. statsmodels/numpy는
동기 블로킹 코드라서 async def 안에서 돌리면 이벤트 루프를 멈춰 세운다.
일반 def로 두면 FastAPI가 알아서 스레드풀로 넘긴다.
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.responses import Response as PlainResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from . import (
    __version__,
    bio,
    config,
    crypto_board,
    crypto_coin,
    crypto_gas,
    crypto_kimchi,
    crypto_market,
    crypto_regime,
    crypto_structure,
    data_rights,
    econ_calendar,
    ingest,
    kr_events,
    kr_fundamentals,
    kr_holdings,
    kr_insider,
    kr_pension,
    kr_press,
    kr_stocks,
    news_feed,
    service,
    signal_feed,
    store,
    us_events,
    us_fundamentals,
    us_ptr,
)
from .data import DataUnavailable, RateLimited
from .insider_filings import (
    DEFAULT_TRANSACTIONS,
    MAX_PUBLIC_TRANSACTIONS,
    InsiderDataDisabled,
    build_insider_report,
)
from .kr_overnight import build_kr_overnight
from .macro_dashboard import MacroDataDisabled, build_macro_series, build_macro_snapshot
from .market_assets import build_asset_snapshot
from .market_sectors import build_sector_snapshot
from .metrics.correlation import correlation_matrix
from .sentiment_index import SentimentIndexUnavailable, build_sentiment_index
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
    return FileResponse(config.STATIC_DIR / "landing.html")


@app.get("/kr", include_in_schema=False)
def korea_page() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "kr.html")


@app.get("/us", include_in_schema=False)
def us_page() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "us.html")


@app.get("/crypto", include_in_schema=False)
def crypto_page() -> FileResponse:
    """크립토 섹션(Phase 1). 페이지 자체는 항상 서빙하고, 값은 lane 게이트가 결정한다."""
    return FileResponse(config.STATIC_DIR / "crypto.html")


@app.get("/bio", include_in_schema=False)
def bio_page() -> FileResponse:
    """바이오 섹션(ROADMAP #8). 페이지는 항상 서빙하고, 값은 lane 게이트가 결정한다."""
    return FileResponse(config.STATIC_DIR / "bio.html")


@app.get("/crypto/{symbol}", include_in_schema=False)
def crypto_coin_hub(symbol: str) -> HTMLResponse:
    """코인 상세 — 서버가 심볼·이름·메타를 렌더한다(크롤러는 JS를 실행하지 않는다).

    Hyperliquid 자체 DEX에 상장돼 있지 않은 심볼은 404 — 쓰레기 URL이 색인되지
    않게 한다. 거래소가 닿지 않는 순간에는 큐레이션된 코인만 렌더한다.
    """
    import html as _html

    require_crypto_section()
    raw = symbol.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,23}", raw):
        raise HTTPException(status_code=404, detail="unrecognized symbol")
    try:
        resolved = crypto_coin.resolve_page_symbol(raw)
    except crypto_coin.CoinNotFound as exc:
        raise HTTPException(status_code=404, detail="unknown market") from exc
    except crypto_coin.CoinUnavailable as exc:
        raise HTTPException(status_code=503, detail="venue unavailable") from exc
    spec = crypto_coin.coin_spec(resolved)
    named = spec.label_ko != resolved
    display = f"{spec.label_ko} ({resolved})" if named else resolved
    title = f"{display} 무기한선물 시세·차트 · Hyperliquid | 물밑 Mulmit"
    description = (
        f"{display} Hyperliquid 무기한선물 마크가격과 캔들 차트, 펀딩비·미결제약정·거래소별 예상 펀딩을 "
        "한 페이지에서. 현물 거래소 가격이 아니며 투자 권유가 아닙니다."
    )
    page = _crypto_coin_template()
    for key, value in (
        ("{{SYMBOL}}", resolved), ("{{NAME}}", spec.label_ko),
        ("{{TITLE}}", title), ("{{DESCRIPTION}}", description),
    ):
        page = page.replace(key, _html.escape(value, quote=True))
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=300"})


@app.get("/monitor", include_in_schema=False)
def market_monitor() -> FileResponse:
    """분리 전의 통합 모니터. 페이지 레이어의 기준 구현으로 남겨 둔다."""
    return FileResponse(config.STATIC_DIR / "monitor.html")


@app.get("/analytics", include_in_schema=False)
def stock_analytics() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    # Browsers and search engines (Naver reads exactly this path; Google wants a
    # square raster) probe here on their own, so it must be a real ICO. The
    # pages also declare PNG/SVG/apple-touch variants with <link> tags.
    # Regenerate the set with scripts/make_favicons.py.
    return FileResponse(
        config.STATIC_DIR / "brand" / "favicon.ico",
        media_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/naverf28e6af919fa64efb88f2106778bbe7d.html", include_in_schema=False)
def naver_site_verification() -> FileResponse:
    """네이버 서치어드바이저 소유확인 파일. 루트 경로에서 서빙되어야 한다."""
    return FileResponse(
        config.STATIC_DIR / "naverf28e6af919fa64efb88f2106778bbe7d.html",
        media_type="text/html",
    )


@app.get("/robots.txt", include_in_schema=False)
def robots() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "robots.txt", media_type="text/plain")




_STOCK_TEMPLATE: str | None = None


_CRYPTO_COIN_TEMPLATE: str | None = None


def _crypto_coin_template() -> str:
    global _CRYPTO_COIN_TEMPLATE
    if _CRYPTO_COIN_TEMPLATE is None:
        _CRYPTO_COIN_TEMPLATE = (config.STATIC_DIR / "crypto-coin.html").read_text(encoding="utf-8")
    return _CRYPTO_COIN_TEMPLATE


def _stock_template() -> str:
    global _STOCK_TEMPLATE
    if _STOCK_TEMPLATE is None:
        _STOCK_TEMPLATE = (config.STATIC_DIR / "stock.html").read_text(encoding="utf-8")
    return _STOCK_TEMPLATE


@app.get("/stock/{symbol}", include_in_schema=False)
def stock_hub(symbol: str) -> HTMLResponse:
    """종목 허브 — 서버가 종목별 타이틀·메타를 렌더한다.

    네이버 크롤러는 자바스크립트를 실행하지 않으므로, 검색에 잡히는 제목과
    설명은 여기서 치환되어야 한다. 알 수 없는 심볼은 404 — 쓰레기 URL이
    무한히 색인되는 것을 막는다(미수집 미국 티커는 로스터에 있으면 허용).
    """
    import html as _html

    symbol = symbol.strip().upper()
    if re.fullmatch(r"\d{6}", symbol):
        listing = store.get_kr_listing(symbol)
        if listing is None:
            raise HTTPException(status_code=404, detail="unknown KRX code")
        name = str(listing.get("itms_nm") or symbol)
        market = str(listing.get("mrkt_ctg") or "KRX")
        title = f"{name} ({symbol}) 주가·재무·내부자 공시 | 물밑 Mulmit"
        description = (
            f"{name} 공식 종가와 낙폭·변동성, 연간 재무제표와 ROE·부채비율·후행 PER, "
            "임원·주요주주 소유보고, 주요사항보고 공시를 한 페이지에서."
        )
    elif re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", symbol):
        company = store.get_insider_company(symbol)
        if company is None or company.get("status") != "ok":
            raise HTTPException(status_code=404, detail="ticker not in covered roster")
        name = str(company.get("name") or symbol)
        market = str(company.get("exchange") or "US")
        title = f"{name} ({symbol}) financials, insiders & 8-K | 물밑 Mulmit"
        description = (
            f"{name} annual financials with ROE and revenue growth, insider Forms "
            "3/4/5, 8-K events and congressional trades, on one page."
        )
    else:
        raise HTTPException(status_code=404, detail="unrecognized symbol")

    page = _stock_template()
    for key, value in (
        ("{{SYMBOL}}", symbol), ("{{NAME}}", name), ("{{MARKET}}", market),
        ("{{TITLE}}", title), ("{{DESCRIPTION}}", description),
    ):
        page = page.replace(key, _html.escape(value, quote=True))
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=600"})


@app.get("/sitemap-pages.xml", include_in_schema=False)
def sitemap_pages() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "sitemap-pages.xml", media_type="application/xml")


@app.get("/sitemap-stocks.xml", include_in_schema=False)
def sitemap_stocks() -> PlainResponse:
    """전 종목 허브 URL의 동적 사이트맵 — 롱테일 검색 유입의 입구."""
    urls = [f"https://mulmit.com/stock/{code}" for code, _name in store.list_kr_codes()]
    urls += [
        f"https://mulmit.com/stock/{row['ticker']}"
        for row in store.list_insider_companies(status="ok")
    ]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    lines.extend(
        f"  <url><loc>{u}</loc><changefreq>daily</changefreq></url>" for u in urls
    )
    lines.append("</urlset>")
    body = "\n".join(lines) + "\n"
    return PlainResponse(
        content=body, media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "sitemap.xml", media_type="application/xml")


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


@app.post("/api/presence")
@limiter.limit(config.RATE_LIMIT)
def presence_heartbeat(request: Request, response: Response, payload: dict) -> dict:
    """접속자 하트비트: 익명 무작위 id를 창에 기록하고 현재 수를 돌려준다.

    개인정보 없음 — id는 브라우저가 만든 무작위 값이고 다른 무엇과도 연결되지
    않는다. 수치는 최근 90초 창의 열린 브라우저 수이며 사람 수가 아니다.
    """
    client_id = str(payload.get("id") or "") if isinstance(payload, dict) else ""
    if not re.fullmatch(r"[A-Za-z0-9-]{8,64}", client_id):
        raise HTTPException(status_code=422, detail="invalid presence id")
    response.headers["Cache-Control"] = "no-store"
    return {
        "count": store.touch_presence(client_id),
        "window_seconds": 90,
        "heartbeat_seconds": 30,
        "basis_ko": "최근 90초 하트비트 기준 열린 브라우저 수 — 사람 수가 아닙니다.",
        "basis_en": "Open browsers heard from in the last 90 seconds — not unique people.",
    }


_PAGEVIEW_PATHS = {"/", "/kr", "/us", "/crypto", "/bio", "/analytics", "/monitor", "/stock"}


@app.post("/api/pageview")
@limiter.limit(config.RATE_LIMIT)
def pageview_beacon(request: Request, response: Response, payload: dict) -> dict:
    """자체 방문 통계 비콘 — 개인정보 없음.

    경로는 닫힌 목록으로 버킷팅하고, 유입경로는 호스트명만 남기며(자기 자신
    제외), 방문자 구분은 presence와 같은 익명 무작위 id다. 쿠키를 쓰지 않는다.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid payload")
    raw_path = str(payload.get("path") or "")
    path = raw_path if raw_path in _PAGEVIEW_PATHS else "other"
    client_id = str(payload.get("id") or "")
    if client_id and not re.fullmatch(r"[A-Za-z0-9-]{8,64}", client_id):
        client_id = ""
    referrer_host = ""
    raw_ref = str(payload.get("ref") or "")[:512]
    if raw_ref:
        from urllib.parse import urlparse

        host = urlparse(raw_ref).hostname or ""
        if host and not host.endswith("mulmit.com"):
            referrer_host = host
    store.record_pageview(path, referrer_host, client_id)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@app.get("/api/stats/traffic")
@limiter.limit(config.RATE_LIMIT)
def stats_traffic(request: Request, response: Response) -> dict:
    """최근 14일 방문 요약. 집계값뿐이라 공개해도 개인정보가 없다."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        **store.traffic_stats(14),
        "basis_ko": (
            "자체 익명 집계 — 쿠키 없음, 경로 버킷·유입 호스트명·익명 무작위 id의 "
            "일 단위 합계만 저장합니다."
        ),
        "basis_en": (
            "First-party anonymous counts: no cookies; only daily sums of path "
            "buckets, referrer hostnames and random anonymous ids are stored."
        ),
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


@app.get("/api/market/sentiment")
@limiter.limit(config.RATE_LIMIT)
def market_sentiment(request: Request, response: Response) -> dict:
    """Mulmit 자체 시장 심리 게이지(실험). 저장소만 읽는다 — OFR 행과 HIP-3 일봉 블롭."""
    try:
        payload = build_sentiment_index()
    except SentimentIndexUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "sentiment_index_unavailable",
                "status": "insufficient_inputs",
                "message": (
                    f"Only {exc.available} of {exc.required} publishable inputs are "
                    "available, so no gauge is published."
                ),
            },
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "Mulmit composite (OFR + Hyperliquid HIP-3 derived)"
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


def require_crypto_section() -> None:
    """The crypto page and its lanes are a deliberate rollout behind one switch."""
    if not data_rights.crypto_section_enabled():
        raise HTTPException(
            status_code=503,
            detail=data_rights.CRYPTO_SECTION_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        )


@app.get("/api/crypto/overview")
@limiter.limit(config.RATE_LIMIT)
def crypto_overview(request: Request, response: Response) -> dict:
    """Hyperliquid 자체 무기한선물 — 가격·24h·펀딩(APR)·OI·예상 펀딩(거래소별)·ETH/BTC."""
    require_crypto_section()
    require_hip3_public_display()
    response.headers["Cache-Control"] = "private, max-age=15, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid"
    # The regime badge rides along: its cached half comes from a stored blob and its
    # funding half is scored against the very cards being served.
    return crypto_regime.attach_coin_signals(crypto_market.build_crypto_overview())


@app.get("/api/crypto/sentiment")
@limiter.limit(config.RATE_LIMIT)
def crypto_sentiment(request: Request, response: Response) -> dict:
    """alternative.me 크립토 공포·탐욕 — 저장된 일별 블롭만 읽는다(요청 경로 호출 없음)."""
    require_crypto_section()
    try:
        payload = crypto_market.build_crypto_sentiment()
    except crypto_market.CryptoSentimentUnavailable as exc:
        detail = (
            data_rights.CRYPTO_SENTIMENT_DISABLED
            if exc.reason == "disabled"
            else data_rights.CRYPTO_SENTIMENT_COLLECTING
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = "alternative.me"
    return payload


@app.get("/api/crypto/volatility")
@limiter.limit(config.RATE_LIMIT)
def crypto_volatility(request: Request, response: Response) -> dict:
    """저장된 일봉으로만 계산한 실현 변동성과 BTC 대 합성자산 상관 — 파생값, 공급자 호출 없음."""
    require_crypto_section()
    require_hip3_public_display()
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = "Hyperliquid (derived)"
    return crypto_market.build_crypto_volatility()


def require_bio_section() -> None:
    """The bio page and its lanes sit behind one switch, like the crypto section."""
    if not data_rights.bio_section_enabled():
        raise HTTPException(
            status_code=503,
            detail=data_rights.BIO_SECTION_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        )


@app.get("/api/bio/trials")
@limiter.limit(config.RATE_LIMIT)
def bio_trials_route(request: Request, response: Response) -> dict:
    """ClinicalTrials.gov 워치리스트 파이프라인 — ingest가 저장한 블롭만 읽는다(약관 4조건 동봉)."""
    require_bio_section()
    try:
        payload = bio.build_bio_trials()
    except bio.BioUnavailable as exc:
        detail = data_rights.BIO_TRIALS_DISABLED if exc.reason == "disabled" else data_rights.BIO_TRIALS_COLLECTING
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = "ClinicalTrials.gov"
    return payload


@app.get("/api/bio/fda")
@limiter.limit(config.RATE_LIMIT)
def bio_fda_route(request: Request, response: Response) -> dict:
    """openFDA 최근 원 신청 승인(NDA·BLA) — ingest가 저장한 블롭만 읽는다."""
    require_bio_section()
    try:
        payload = bio.build_bio_fda()
    except bio.BioUnavailable as exc:
        detail = data_rights.BIO_FDA_DISABLED if exc.reason == "disabled" else data_rights.BIO_FDA_COLLECTING
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = "openFDA"
    return payload


@app.get("/api/bio/adcomm")
@limiter.limit(config.RATE_LIMIT)
def bio_adcomm_route(request: Request, response: Response) -> dict:
    """FDA 자문위원회 회의 공고(Federal Register) — ingest가 저장한 블롭만 읽는다."""
    require_bio_section()
    try:
        payload = bio.build_bio_adcomm()
    except bio.BioUnavailable as exc:
        detail = data_rights.BIO_ADCOMM_DISABLED if exc.reason == "disabled" else data_rights.BIO_ADCOMM_COLLECTING
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = "Federal Register"
    return payload


@app.get("/api/bio/mfds")
@limiter.limit(config.RATE_LIMIT)
def bio_mfds_route(request: Request, response: Response) -> dict:
    """식약처 의약품 품목허가(공공데이터포털) — ingest가 저장한 블롭만 읽는다."""
    require_bio_section()
    try:
        payload = bio.build_bio_mfds()
    except bio.BioUnavailable as exc:
        detail = data_rights.BIO_MFDS_DISABLED if exc.reason == "disabled" else data_rights.BIO_MFDS_COLLECTING
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=3600"
    response.headers["X-Data-Source"] = "MFDS (data.go.kr)"
    return payload


@app.get("/api/crypto/structure")
@limiter.limit(config.RATE_LIMIT)
def crypto_structure_route(request: Request, response: Response) -> dict:
    """CoinMarketCap 글로벌 메트릭(도미넌스·총시총) — ingest가 저장한 블롭만 읽는다."""
    require_crypto_section()
    try:
        payload = crypto_structure.build_crypto_structure()
    except crypto_structure.CryptoStructureUnavailable as exc:
        detail = (
            data_rights.CRYPTO_STRUCTURE_DISABLED
            if exc.reason == "disabled"
            else data_rights.CRYPTO_STRUCTURE_COLLECTING
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=1800"
    response.headers["X-Data-Source"] = "CoinMarketCap"
    return payload


@app.get("/api/crypto/kimchi")
@limiter.limit(config.RATE_LIMIT)
def crypto_kimchi_route(request: Request, response: Response) -> dict:
    """업비트 원화 시세와 김치프리미엄(USDT 기준·공식환율 기준). 서버 relay, 15초 캐시."""
    require_crypto_section()
    if not data_rights.upbit_serving_enabled():
        raise HTTPException(
            status_code=503,
            detail=data_rights.UPBIT_PENDING_RIGHTS,
            headers=dict(data_rights.NO_STORE_HEADERS),
        )
    require_hip3_public_display()
    response.headers["Cache-Control"] = "private, max-age=15, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Upbit + Hyperliquid + BOK ECOS"
    return crypto_kimchi.build_crypto_kimchi()


@app.get("/api/crypto/gas")
@limiter.limit(config.RATE_LIMIT)
def crypto_gas_route(request: Request, response: Response) -> dict:
    """가스·수수료 스트립 — 운영자 RPC 계정으로 읽는 공개 체인 상태. 서버 30초 캐시, URL·키 비노출."""
    require_crypto_section()
    status = data_rights.chain_gas_status()
    if status != "enabled":
        detail = (
            data_rights.CHAIN_GAS_DISABLED if status == "disabled" else data_rights.CHAIN_GAS_NOT_CONFIGURED
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        )
    response.headers["Cache-Control"] = "private, max-age=30, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "EVM JSON-RPC (operator account)"
    return crypto_gas.build_crypto_gas()


@app.get("/api/crypto/regime")
@limiter.limit(config.RATE_LIMIT)
def crypto_regime_route(request: Request, response: Response) -> dict:
    """시장 전체 국면 — 쏠림 폭·상승 폭·기준 코인 과열도·공포탐욕. 같은 스냅샷·같은 게이트."""
    require_crypto_section()
    require_hip3_public_display()
    try:
        payload = crypto_regime.build_crypto_regime()
    except crypto_regime.RegimeUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "crypto_regime_unavailable", "status": "unavailable", "reason": exc.reason,
                    "message": "The market regime read could not be assembled."},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    response.headers["Cache-Control"] = "private, max-age=30, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid"
    return payload


@app.get("/api/crypto/board")
@limiter.limit(config.RATE_LIMIT)
def crypto_board_route(request: Request, response: Response) -> dict:
    """Hyperliquid 전체 퍼프 보드 — 급등·급락, OI·거래대금 상위, 펀딩 극단값, 합계. 같은 스냅샷·같은 게이트."""
    require_crypto_section()
    require_hip3_public_display()
    response.headers["Cache-Control"] = "private, max-age=15, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid"
    return crypto_board.build_crypto_board()


@app.get("/api/crypto/coin/{symbol}")
@limiter.limit(config.RATE_LIMIT)
def crypto_coin_route(
    request: Request,
    response: Response,
    symbol: str,
    interval: str = Query(crypto_coin.DEFAULT_INTERVAL),
    candles: bool = Query(True),
) -> dict:
    """한 코인의 시장 컨텍스트(카드와 같은 빌더)와 캔들 — 같은 스냅샷·같은 게이트."""
    require_crypto_section()
    require_hip3_public_display()
    if interval not in crypto_coin.INTERVALS:
        raise HTTPException(status_code=422, detail="unsupported interval")
    try:
        payload = crypto_coin.build_crypto_coin(symbol, interval=interval, include_candles=candles)
    except crypto_coin.CoinNotFound as exc:
        raise HTTPException(status_code=404, detail="unknown market") from exc
    except crypto_coin.CoinUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "crypto_venue_unavailable", "status": "unavailable", "reason": exc.reason,
                    "message": "Hyperliquid could not be reached for this market."},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    response.headers["Cache-Control"] = "private, max-age=15, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid"
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


@app.get("/api/kr/etf")
@limiter.limit(config.RATE_LIMIT)
def kr_etf_board(request: Request, response: Response) -> dict:
    """ETF 보드: 거래대금 상위와 NAV 괴리율. 하루치 스냅샷만 읽는다."""
    try:
        payload = kr_stocks.etf_board()
    except kr_stocks.KrStockDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail=data_rights.KR_STOCK_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except (kr_stocks.KrEtfUnavailable, DataUnavailable, RateLimited) as exc:
        raise HTTPException(status_code=503, detail="ETF snapshot unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "Financial Services Commission (data.go.kr)"
    return payload


@app.get("/api/kr/overnight")
@limiter.limit(config.RATE_LIMIT)
def kr_overnight(request: Request, response: Response) -> dict:
    """한국 24시간 참고가: HIP-3 마크 × H.10 공식환율 대 마지막 공식 종가.

    HIP-3 공개 표시 게이트가 닫혀 있으면 응답 전체가 기존 503 계약을 따른다.
    FSC·H.10 쪽 결손은 카드 안에서 상태 코드와 null로 표현된다.
    """
    require_hip3_public_display()
    response.headers["Cache-Control"] = "private, max-age=3, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid HIP-3 + FSC + BOK ECOS"
    return build_kr_overnight()


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


@app.get("/api/kr/fundamentals/{code}")
@limiter.limit(config.RATE_LIMIT)
def kr_fundamentals_report(code: str, request: Request, response: Response) -> dict:
    """국내 종목 연간 재무제표(DART 주요계정). 캐시 우선, 미스에서만 단발 조회."""
    code = code.strip().upper()
    if not (4 <= len(code) <= 12) or not code.isalnum():
        raise HTTPException(status_code=422, detail="code must be a KRX issue code")
    try:
        payload = kr_fundamentals.get_report(code)
    except kr_fundamentals.KrFundamentalsDisabled as exc:
        detail = (
            data_rights.KR_FUNDAMENTALS_NOT_CONFIGURED
            if exc.reason == "not_configured"
            else data_rights.KR_FUNDAMENTALS_DISABLED
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    except kr_fundamentals.KrFundamentalsUnknown as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "kr_fundamentals_unknown", "message": f"{code} is not a DART-listed issue"},
        ) from exc
    except (DataUnavailable, RateLimited) as exc:
        raise HTTPException(status_code=503, detail="DART fundamentals unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "FSS DART"
    return payload


@app.get("/api/kr/holdings")
@limiter.limit(config.RATE_LIMIT)
def kr_holdings_filings(request: Request, response: Response) -> dict:
    """대량보유(5% 룰) 공시 — 전체 보고자. 배치가 저장한 결과만 읽는다."""
    try:
        payload = kr_holdings.get_holdings()
    except kr_holdings.KrHoldingsDisabled as exc:
        # kr_pension과 같은 DART 게이트에서 갈라진 lane이라 안내문을 공유한다.
        detail = (
            data_rights.KR_PENSION_NOT_CONFIGURED
            if exc.reason == "not_configured"
            else data_rights.KR_PENSION_DISABLED
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="major-holding filings not collected yet"
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    return payload


@app.get("/api/kr/pension")
@limiter.limit(config.RATE_LIMIT)
def kr_pension_filings(request: Request, response: Response) -> dict:
    """국민연금 대량보유(5%) 공시. ingest 배치가 저장한 결과만 읽는다."""
    try:
        payload = kr_pension.get_filings()
    except kr_pension.KrPensionDisabled as exc:
        detail = (
            data_rights.KR_PENSION_NOT_CONFIGURED
            if exc.reason == "not_configured"
            else data_rights.KR_PENSION_DISABLED
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="NPS major-holding filings not collected yet"
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "FSS DART"
    return payload


@app.get("/api/kr/press")
@limiter.limit(config.RATE_LIMIT)
def kr_press_feed(request: Request, response: Response) -> dict:
    """정부 보도자료 헤드라인. ingest 배치가 저장한 결과만 읽는다."""
    try:
        payload = kr_press.get_press()
    except kr_press.KrPressDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "kr_press_disabled", "message": "Press lane is disabled."},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail="press not collected yet") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    return payload


@app.get("/api/news")
@limiter.limit(config.RATE_LIMIT)
def news_headlines(request: Request, response: Response) -> dict:
    """GDELT 뉴스 헤드라인. ingest 배치가 저장한 결과만 읽는다."""
    try:
        payload = news_feed.get_news()
    except news_feed.NewsFeedDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "news_disabled", "message": "News lane is disabled."},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail="news not collected yet") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "GDELT"
    return payload


@app.get("/api/feed")
@limiter.limit(config.RATE_LIMIT)
def unified_feed(request: Request, response: Response) -> dict:
    """통합 신호 피드 — 저장된 lane들의 재조립. 저장소만 읽는다."""
    response.headers["Cache-Control"] = "public, max-age=300"
    return signal_feed.build_feed()


@app.get("/api/kr/events")
@limiter.limit(config.RATE_LIMIT)
def kr_events_feed(request: Request, response: Response) -> dict:
    """주요사항보고 공시 속보. ingest 배치가 저장한 결과만 읽는다."""
    try:
        payload = kr_events.get_events()
    except kr_events.KrEventsDisabled as exc:
        detail = (
            data_rights.KR_PENSION_NOT_CONFIGURED
            if exc.reason == "not_configured"
            else data_rights.KR_PENSION_DISABLED
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Korean material-event filings not collected yet"
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "FSS DART"
    return payload


@app.get("/api/us/ptr")
@limiter.limit(config.RATE_LIMIT)
def us_ptr_filings(request: Request, response: Response) -> dict:
    """미 하원 의원 주기거래보고(PTR). ingest 배치가 저장한 결과만 읽는다."""
    try:
        payload = us_ptr.get_filings()
    except us_ptr.UsPtrDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail=data_rights.US_PTR_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="House PTR filings not collected yet"
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "Clerk of the U.S. House of Representatives"
    return payload


@app.get("/api/calendar")
@limiter.limit(config.RATE_LIMIT)
def economic_calendar(request: Request, response: Response) -> dict:
    """다가오는 경제 일정. FRED 릴리스 예정일(저장분) + 검증된 정책회의 큐레이션."""
    response.headers["Cache-Control"] = "public, max-age=1800"
    response.headers["X-Data-Source"] = "FRED release metadata + official calendars"
    return econ_calendar.build_calendar()


@app.get("/api/us/fundamentals/{ticker}")
@limiter.limit(config.RATE_LIMIT)
def us_fundamentals_report(ticker: str, request: Request, response: Response) -> dict:
    """미국 상장사 재무제표(EDGAR XBRL). 저장소만 읽고, 미수집 티커는 큐에 태운다."""
    if not ticker.strip():
        raise HTTPException(status_code=422, detail="ticker is required")
    try:
        payload = us_fundamentals.build_report(ticker)
    except us_fundamentals.UsFundamentalsDisabled as exc:
        detail = (
            data_rights.US_FUNDAMENTALS_NOT_CONFIGURED
            if exc.reason == "not_configured"
            else data_rights.US_FUNDAMENTALS_DISABLED
        )
        raise HTTPException(
            status_code=503, detail=detail, headers=dict(data_rights.NO_STORE_HEADERS)
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "SEC EDGAR"
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


@app.get("/api/us/events")
@limiter.limit(config.RATE_LIMIT)
def us_events_feed(
    request: Request,
    response: Response,
    limit: int = Query(us_events.DEFAULT_EVENTS, ge=1, le=us_events.MAX_EVENTS),
) -> dict:
    """커버 중인 티커의 8-K 이벤트 공시 피드. 저장소만 읽는다."""
    try:
        payload = us_events.build_events_feed(limit)
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
