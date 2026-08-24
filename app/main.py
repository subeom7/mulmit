"""FastAPI 엔트리포인트.

엔드포인트를 async가 아닌 def로 선언한 건 의도적이다. statsmodels/numpy는
동기 블로킹 코드라서 async def 안에서 돌리면 이벤트 루프를 멈춰 세운다.
일반 def로 두면 FastAPI가 알아서 스레드풀로 넘긴다.
"""

from __future__ import annotations

import logging
import mimetypes
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
    crypto_coin_page,
    crypto_gas,
    crypto_kimchi,
    crypto_liquidations,
    crypto_market,
    crypto_regime,
    crypto_structure,
    data_rights,
    econ_calendar,
    glossary,
    ingest,
    kr_events,
    kr_fundamentals,
    kr_holdings,
    kr_insider,
    kr_pension,
    kr_pension_portfolio,
    kr_press,
    kr_search_interest,
    kr_stocks,
    news_feed,
    news_page,
    news_videos,
    search,
    service,
    signal_feed,
    stock_page,
    store,
    us_events,
    us_fundamentals,
    us_overnight,
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
        "한국·미국 시장과 암호화폐를 공시 기록과 공공데이터로 봅니다 — 종목별 "
        "재무제표·내부자 거래·공시, 거시 지표, 크립토 파생 지표. / Korean and US "
        "markets and crypto, from filings and public data."
    ),
    lifespan=lifespan,
)
app.state.limiter = limiter


class HeadAsGet:
    """HEAD를 GET처럼 처리하고 본문만 뺀다.

    Starlette의 평범한 `Route`는 GET을 선언하면 HEAD를 함께 붙여 주는데,
    **FastAPI의 `APIRoute`는 그러지 않는다.** 그래서 이 앱의 모든 경로가 —
    홈페이지와 `/favicon.ico`까지 — HEAD에 405를 돌려주고 있었다(실측
    2026-08-24: `HEAD /` → `{"detail":"Method Not Allowed"}`).

    존재하는 페이지가 HEAD에 405를 주는 것은 그 자체로 틀린 동작이다. 링크
    검사기·업타임 모니터·일부 크롤러가 본문을 안 받으려고 HEAD를 쓴다.

    라우트마다 `methods=["GET", "HEAD"]`를 다는 대신 여기서 한 번에 처리한다 —
    앞으로 추가되는 라우트도 자동으로 따라온다. RFC 9110 §9.3.2대로 헤더는
    GET과 같게 두고(`Content-Length` 포함) 본문만 비운다.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or scope.get("method") != "HEAD":
            await self.app(scope, receive, send)
            return

        async def drop_body(message):
            if message["type"] == "http.response.body":
                # 헤더는 그대로 두고 바이트만 지운다. more_body가 남아 있으면
                # 서버가 다음 청크를 기다리므로 여기서 끊는다.
                message = {"type": "http.response.body", "body": b"", "more_body": False}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, drop_body)


# 가격 시계열이 수천 포인트라 압축이 체감된다
app.add_middleware(GZipMiddleware, minimum_size=1000)
# HEAD 변환은 가장 바깥에 둔다 — 안쪽 미들웨어와 라우트는 GET만 보면 된다.
app.add_middleware(HeadAsGet)


# 캐시 지시를 명시한다.
#
# 안 붙이면 브라우저가 **휴리스틱 캐싱**을 쓴다 — 보통 (지금 − Last-Modified)의
# 10%. 배포 직후에는 창이 짧지만 열흘 손대지 않은 파일은 하루치가 되고, 그러면
# 재방문자는 하루 지난 HTML을 받는다. 그 HTML이 가리키는 `?v=`도 옛 버전이라
# 에셋까지 통째로 옛 판이 된다. 깨지지는 않지만(둘이 같은 판이라 정합은 맞다)
# 모든 수정이 사용자에게 늦게 도착한다. 실측 2026-08-23: 배포 1시간 뒤에 연
# 브라우저가 `v=20260823-22`를 그리고 있었고, 같은 순간 `fetch(cache:"reload")`는
# 새 HTML을 받았다.
#
#   HTML          no-cache — 금지가 아니라 "쓰기 전에 물어봐"다. ETag가 있어
#                 안 바뀌었으면 304로 끝나고 본문은 다시 오지 않는다.
#   `?v=` 있는 정적 파일  판이 바뀌면 URL이 바뀌므로 영구 캐시.
#   폰트           92개 서브셋은 이름이 곧 내용이고 바뀌지 않는다. 영구 캐시.
#   그 밖의 정적    버전 없는 링크가 사용자를 1년 묶어 두면 안 되니 짧게.
#
# 라우트가 직접 정한 값이 있으면 건드리지 않는다 — `/glossary`·`/stock`처럼
# 서버 렌더 페이지는 짧은 공개 캐시를 일부러 걸어 둔 것이다.
# 폰트만 영구 고정한다. 서브셋 92개는 파일 이름이 곧 내용이라 같은 URL이 다른
# 바이트를 줄 일이 없다.
FONT_IMMUTABLE = "public, max-age=31536000, immutable"

# `?v=` 붙은 자산은 **자가 치유가 되는 만큼만** 잡는다.
#
# 예전에는 여기도 `immutable` 1년이었다. 그런데 `?v=`는 쿼리일 뿐이고 서버는 늘
# 같은 파일 하나를 준다 — URL과 내용이 1:1로 묶여 있지 않다. 배포 도중 HTML은
# 새 버전인데 파일이 아직 옛것인 찰나에 요청이 들어오면, 브라우저는 **옛 내용을
# 새 키로** 받아 1년 동안 고정한다. immutable이라 재검증도 하지 않으니 스스로
# 낫지 않는다.
#
# 실측 2026-08-23: 배포 직후 `monitor.js?v=20260823-31`을 실행 중인 코드에 새
# 함수가 없었다. 같은 URL을 `cache:"reload"`로 받으면 있었다. 캐시를 비우니
# 즉시 정상이 됐다. 사용자는 캐시를 비우지 않는다.
#
# 하루면 ETag 재검증으로 스스로 낫는다. 이 규모(14일 32PV)에서 잃는 것은 없고,
# 잃을 뻔한 것은 사용자 브라우저에 1년 박히는 깨진 화면이다.
STATIC_VERSIONED = "public, max-age=86400"
# 304에 실어 보내도 되는 헤더(RFC 9110 §15.4.5). 본문은 없다.
_REVALIDATED_HEADERS = ("cache-control", "etag", "last-modified", "vary", "content-location")


def _etag_matches(if_none_match: str | None, etag: str | None) -> bool:
    """`If-None-Match`가 이 응답의 ETag를 가리키는가.

    쉼표로 여러 개가 올 수 있고, 약한 검증자는 `W/` 접두가 붙는다. 304 판정에는
    약한 비교를 쓴다(RFC 9110 §13.1.2) — 접두를 떼고 견준다.
    """
    if not if_none_match or not etag:
        return False
    if if_none_match.strip() == "*":
        return True
    candidates = {value.strip().removeprefix("W/") for value in if_none_match.split(",")}
    return etag.strip().removeprefix("W/") in candidates


@app.middleware("http")
async def _cache_headers(request: Request, call_next):
    response = await call_next(request)

    if not response.headers.get("cache-control"):
        path = request.url.path
        if path.startswith("/static/"):
            if path.startswith("/static/fonts/"):
                policy = FONT_IMMUTABLE
            elif "v" in request.query_params:
                policy = STATIC_VERSIONED
            else:
                policy = "public, max-age=3600"
            response.headers["Cache-Control"] = policy
        elif (response.headers.get("content-type") or "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"

    # 조건부 요청에 304로 답한다.
    #
    # `StaticFiles`는 스스로 If-None-Match를 보지만, 라우트가 그냥 돌려주는
    # `FileResponse`는 보지 않는다(starlette 0.46 실측). 그래서 위의 no-cache가
    # "물어보기"가 아니라 "매번 전체 다시 받기"가 되고 있었다. 여기서 마저 한다.
    if (
        request.method in ("GET", "HEAD")
        and response.status_code == 200
        and _etag_matches(request.headers.get("if-none-match"), response.headers.get("etag"))
    ):
        kept = {
            name: response.headers[name]
            for name in _REVALIDATED_HEADERS
            if name in response.headers
        }
        return Response(status_code=304, headers=kept)
    return response


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요. ({exc.detail})"},
    )


# 웹폰트 MIME을 못 박는다. StaticFiles는 mimetypes.guess_type에 기대는데 그
# 표는 OS마다 다르고, woff2를 모르는 환경에서는 바이너리가
# `text/plain; charset=utf-8`로 나간다(윈도우 실측). 브라우저가 스니핑해서
# 대개는 그려지지만, charset이 붙은 바이너리는 중간에 낀 프록시 하나가
# 변환을 시도하면 그대로 깨진다. 서버마다 다르게 동작할 이유가 없다.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

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
    if not crypto_coin.PAGE_SYMBOL_PATTERN.fullmatch(raw):
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
    # 크롤러가 읽을 본문. 이미 이스케이프된 HTML이라 위 치환 뒤에 넣는다.
    page = page.replace("{{SSR}}", crypto_coin_page.render(resolved, label=spec.label_ko))
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=300"})


@app.get("/monitor", include_in_schema=False)
def market_monitor() -> FileResponse:
    """분리 전의 통합 모니터. 페이지 레이어의 기준 구현으로 남겨 둔다."""
    return FileResponse(config.STATIC_DIR / "monitor.html")


@app.get("/analytics", include_in_schema=False)
def stock_analytics() -> FileResponse:
    """종목 찾기 진입 페이지. 종목 데이터는 여기서 그리지 않는다.

    예전에는 이 페이지가 국내·미국 종목을 각자 다른 모양으로 직접 렌더했고,
    그 두 벌이 `/stock/{심볼}`이 그리는 것과 같은 payload를 세 번째로 그리는
    셈이었다. 한쪽만 고쳐서 다른 쪽이 조용히 깨지는 사고가 실제로 났다.
    지금은 찾아서 보내 주기만 한다.
    """
    return FileResponse(config.STATIC_DIR / "analytics.html")


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
    return FileResponse(
        config.STATIC_DIR / "robots.txt", media_type="text/plain",
        headers={"Cache-Control": "public, max-age=3600"},
    )




_STOCK_TEMPLATE: str | None = None


_CRYPTO_COIN_TEMPLATE: str | None = None
_GLOSSARY_TEMPLATE: str | None = None


def _crypto_coin_template() -> str:
    global _CRYPTO_COIN_TEMPLATE
    if _CRYPTO_COIN_TEMPLATE is None:
        _CRYPTO_COIN_TEMPLATE = (config.STATIC_DIR / "crypto-coin.html").read_text(encoding="utf-8")
    return _CRYPTO_COIN_TEMPLATE


def _glossary_template() -> str:
    global _GLOSSARY_TEMPLATE
    if _GLOSSARY_TEMPLATE is None:
        _GLOSSARY_TEMPLATE = (config.STATIC_DIR / "glossary.html").read_text(encoding="utf-8")
    return _GLOSSARY_TEMPLATE


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
    korean = bool(re.fullmatch(r"\d{6}", symbol))
    if korean:
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
    # 크롤러가 읽을 본문. 이미 이스케이프된 HTML이라 위 치환 뒤에 넣는다.
    page = page.replace("{{SSR}}", stock_page.render(symbol, korean=bool(korean)))
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=600"})


@app.get("/sitemap-pages.xml", include_in_schema=False)
def sitemap_pages() -> FileResponse:
    return FileResponse(
        config.STATIC_DIR / "sitemap-pages.xml", media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sitemap-stocks.xml", include_in_schema=False)
def sitemap_stocks() -> PlainResponse:
    """종목 허브 사이트맵 — **값이 있는 종목만**.

    로스터 전체를 올리던 때가 있었다. 2026-08-24에 재 보니 국내 2,873종목 중
    저장된 종가가 있는 것이 19개였다 — 나머지는 방문할 때 그 자리에서 모으는
    구조라 크롤러가 볼 때 비어 있다. 빈 페이지를 3,000개 광고하면 그것들이 색인
    안 되는 데서 끝나지 않고 사이트 전체의 품질 신호를 끌어내린다.

    좁힌다고 페이지가 사라지지는 않는다 — 사람이 찾아오면 그때 수집해서 보여
    준다. 사이트맵은 "이건 지금 볼 것이 있다"는 약속이고, 그 약속만 지킨다.
    수집이 진행되면 이 목록은 저절로 늘어난다.
    """
    with_data = set(store.list_kr_codes_with_series())
    urls = [
        f"https://mulmit.com/stock/{code}"
        for code, _name in store.list_kr_codes()
        if code in with_data
    ]
    urls += [
        f"https://mulmit.com/stock/{row['ticker']}"
        for row in store.list_insider_companies(status="ok")
    ]
    # 코인 상세도 같은 사이트맵에 올린다. 지금까지 아예 빠져 있어서 구글이 존재를
    # 모르는 상태였다(2026-08-24 확인). 큐레이션된 목록이라 값이 없는 페이지가
    # 섞이지 않는다 — 종목과 달리 여기서는 전수가 곧 "볼 것이 있는" 목록이다.
    if data_rights.crypto_section_enabled():
        urls += [
            f"https://mulmit.com/crypto/{symbol}"
            for symbol in crypto_coin.curated_symbols()
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


@app.get("/sitemap-coins.xml", include_in_schema=False)
def sitemap_coins() -> PlainResponse:
    """코인 허브 URL — 거래소가 지금 상장한 시장만 싣는다.

    목록은 페이지 라우트와 같은 판정을 쓴다(`crypto_coin.page_symbols`). 상장
    폐지된 시장이나 라우트가 받지 않는 심볼을 사이트맵에 올리면 404를 색인하라고
    광고하는 셈이라, 두 곳이 갈라지지 않도록 판정을 한 군데서만 한다.
    섹션이 꺼져 있으면 빈 사이트맵 — 게이트가 닫힌 페이지를 권하지 않는다.
    """
    rows = crypto_coin.page_symbols() if data_rights.crypto_overview_enabled() else []
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    lines.extend(
        f"  <url><loc>https://mulmit.com/crypto/{symbol}</loc>"
        f"<changefreq>hourly</changefreq><priority>{'0.7' if curated else '0.5'}</priority></url>"
        for symbol, curated in rows
    )
    lines.append("</urlset>")
    return PlainResponse(
        content="\n".join(lines) + "\n", media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> FileResponse:
    return FileResponse(
        config.STATIC_DIR / "sitemap.xml", media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/privacy", include_in_schema=False)
def privacy_policy() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "privacy.html")


@app.get("/terms", include_in_schema=False)
def terms_of_use() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "terms.html")


@app.get("/news", include_in_schema=False)
def news_feed_page() -> HTMLResponse:
    """전용 신호 피드. 서버에서 렌더한다.

    이 페이지를 만드는 이유의 절반이 색인이고, JS로 채우면 크롤러가 빈 화면을
    읽는다. `/glossary`와 같은 이유로 같은 선택이다. 캐시는 짧게 — 15분 주기로
    갱신되는 레인이라 한 시간을 물고 있으면 낡은 목록을 보여 준다.
    """
    page = news_page.template()
    filled = news_page.render()
    page = page.replace("{{JSONLD}}", news_page.json_ld())
    for key, value in filled.items():
        page = page.replace("{{" + key + "}}", value)
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=300"})


@app.get("/glossary", include_in_schema=False)
def glossary_page() -> HTMLResponse:
    """용어 사전. 크롤러가 JS를 실행하지 않으므로 서버가 본문을 렌더한다.

    "펀딩비 뜻" 같은 검색 유입이 이 페이지의 존재 이유라 내용이 HTML 안에
    있어야 한다. 사전은 화면의 용어 팝오버와 같은 파일(static/terms.json)이다.
    """
    page = _glossary_template()
    for key, value in (
        ("{{JSONLD}}", glossary.json_ld()),
        ("{{INDEX}}", glossary.index_html()),
        ("{{TERMS}}", glossary.terms_html()),
    ):
        page = page.replace(key, value)
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=3600"})


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
    """가스·수수료 스트립 — 운영자 RPC 계정으로 읽는 공개 체인 상태. URL·키 비노출.

    저장된 스트립을 즉시 돌려주고 30초가 지났으면 뒤에서 갱신한다 — 이걸 만드는
    데 업스트림 왕복 4번(실측 콜드 1.57초)이 들어서, 예전 모양에서는 30초마다
    한 명이 그 값을 전부 물었다.
    """
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
    return crypto_gas.snapshot()


@app.get("/api/crypto/liquidations")
@limiter.limit(config.RATE_LIMIT)
def crypto_liquidations_route(request: Request, response: Response) -> dict:
    """거래소 집계 청산·미결제약정 — 수집된 블롭만 읽는다.

    합계는 **응답한 거래소들의 합**이며 전체 시장 합계가 아니다. Coinalyze에는
    집계 심볼이 없고, 데이터가 없는 심볼은 없는 심볼과 똑같이 `200 []`로
    돌아온다 — 그래서 포함된 거래소와 침묵한 거래소를 값과 함께 싣는다.
    """
    require_crypto_section()
    try:
        payload = crypto_liquidations.build_crypto_liquidations()
    except crypto_liquidations.LiquidationsUnavailable as exc:
        code = (
            "crypto_liquidations_disabled"
            if not data_rights.coinalyze_serving_enabled()
            else "crypto_liquidations_collecting"
        )
        raise HTTPException(
            status_code=503,
            detail={"code": code, "message": str(exc)},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=120"
    response.headers["X-Data-Source"] = "Coinalyze"
    return payload


@app.get("/api/crypto/news")
@limiter.limit(config.RATE_LIMIT)
def crypto_news_route(
    request: Request,
    response: Response,
    symbol: str | None = Query(None, max_length=24),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    """코인 태그가 붙은 헤드라인 — 저장된 GDELT 블롭만 읽는다(제목·출처·링크까지)."""
    require_crypto_section()
    try:
        payload = news_feed.crypto_articles(symbol, limit=limit)
    except news_feed.NewsFeedDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "crypto_news_disabled", "status": "disabled",
                    "message": "The news lane is disabled for this deployment."},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "crypto_news_collecting", "status": "collecting",
                    "message": "Headlines appear after the next collection pass."},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "GDELT"
    return payload


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


@app.get("/api/search")
@limiter.limit(config.RATE_LIMIT)
def global_search(
    request: Request,
    response: Response,
    q: str = Query(..., min_length=1, max_length=40),
    limit: int = Query(search.DEFAULT_LIMIT, ge=1, le=search.MAX_LIMIT),
) -> dict:
    """한 칸에서 코인·국내 종목·미국 종목을 함께 찾는다.

    저장된 로스터만 읽는다 — 코인은 대시보드가 이미 폴링하는 스냅샷 캐시,
    국내는 금융위 상장 로스터, 미국은 공시 수집 대상 티커 표다. 타이핑마다
    외부 API를 부르지 않는다. 세 로스터 중 하나가 꺼져 있거나 비어 있으면 그
    묶음만 빠지고 나머지는 그대로 답한다 — 검색이 한 레인의 가용성에 걸리면
    안 된다.
    """
    payload = search.search(q, limit=limit)
    response.headers["Cache-Control"] = "public, max-age=120"
    response.headers["X-Data-Source"] = (
        "Hyperliquid; Financial Services Commission (data.go.kr); SEC EDGAR"
    )
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


@app.get("/api/kr/search-interest")
@limiter.limit(config.RATE_LIMIT)
def kr_search_interest_board(request: Request, response: Response) -> dict:
    """종목 검색 관심도: 네이버 데이터랩 통합검색어 트렌드, 저장 없이 요청 경로에서.

    값은 요청 기간의 최댓값을 100으로 둔 **상대값**이라 요청이 갈라지면 100의 뜻도
    갈라진다. 그래서 종목 간 비교는 자기 평소 대비 배수·백분위로만 하고, 원값을
    섞지 못하도록 각 종목에 `batch` 번호를 실어 보낸다.
    """
    try:
        payload = kr_search_interest.build()
    except kr_search_interest.KrSearchInterestDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail=data_rights.KR_SEARCH_INTEREST_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except kr_search_interest.DatalabConfigError as exc:
        raise HTTPException(status_code=503, detail="NAVER DataLab credentials are not configured") from exc
    except (DataUnavailable, RateLimited) as exc:
        raise HTTPException(status_code=503, detail="Search-interest data unavailable") from exc
    # 상류가 하루 단위로만 바뀐다. 브라우저 캐시도 그 리듬에 맞춘다.
    response.headers["Cache-Control"] = "public, max-age=900"
    response.headers["X-Data-Source"] = "NAVER DataLab search trends"
    return payload


@app.get("/api/kr/search-interest/{code}")
@limiter.limit(config.RATE_LIMIT)
def kr_search_interest_one(code: str, request: Request, response: Response) -> dict:
    """종목 하나의 검색 관심도. 상류 호출 한 번, 6시간 캐시.

    국내 종목 전용이다 — 네이버에서 미국 티커를 검색하는 모집단은 다르고
    훨씬 작아서, 그것을 재면 신호가 아니라 잡음이다.
    """
    code = code.strip().upper()
    if not re.fullmatch(r"\d{6}", code):
        raise HTTPException(status_code=404, detail="국내 종목 코드가 아닙니다")
    try:
        payload = kr_search_interest.build_for(code)
    except kr_search_interest.KrSearchInterestDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail=data_rights.KR_SEARCH_INTEREST_DISABLED,
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except kr_search_interest.DatalabConfigError as exc:
        raise HTTPException(status_code=503, detail="NAVER DataLab credentials are not configured") from exc
    except (DataUnavailable, RateLimited) as exc:
        raise HTTPException(status_code=503, detail="Search-interest data unavailable") from exc
    response.headers["Cache-Control"] = "public, max-age=900"
    response.headers["X-Data-Source"] = "NAVER DataLab search trends"
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


@app.get("/api/us/overnight")
@limiter.limit(config.RATE_LIMIT)
def us_overnight_route(request: Request, response: Response) -> dict:
    """미국 대형주 24시간 참고가: HIP-3 마크 대 마지막 정규장 마감(16:00 ET).

    정규장이 열려 있으면 카드를 만들지 않고 `status: "market_open"`만 답한다 —
    그때는 진짜 호가가 있고, 합성 퍼프를 나란히 두면 나은 게 없으면서
    "실시간 주가"로 오해만 부른다.
    """
    require_hip3_public_display()
    response.headers["Cache-Control"] = "private, max-age=3, stale-while-revalidate=300"
    response.headers["X-Data-Source"] = "Hyperliquid HIP-3"
    return us_overnight.build_us_overnight()


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


@app.get("/api/kr/pension-portfolio")
@limiter.limit(config.RATE_LIMIT)
def kr_pension_portfolio_snapshot(request: Request, response: Response) -> dict:
    """국민연금 국내주식 포트폴리오(연말 스냅샷).

    저장소에 들어 있는 파일을 읽으므로 게이트도 수집 배치도 없다. 이용허락범위가
    제한 없음이라 막을 권리 문제가 없고, 요청 시 외부를 부르지 않으므로 꺼야 할
    쿼터도 없다 — 끌 수 없는 게이트는 안전을 더하지 않고 고장날 곳만 만든다.
    사정은 `docs/DATA_SOURCE_REGISTER.md` §3.30에 적었다.
    """
    if not data_rights.nps_portfolio_serving_enabled():  # pragma: no cover - 항상 참
        raise HTTPException(status_code=503, detail="NPS portfolio lane is closed")
    payload = kr_pension_portfolio.get_portfolio()
    # 이미지 안에서 바뀌지 않는 파일이다. 짧게 잡을 이유가 없다.
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.headers["X-Data-Source"] = "data.go.kr NPS"
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


@app.get("/api/news/videos")
@limiter.limit(config.RATE_LIMIT)
def news_video_list(request: Request, response: Response) -> dict:
    """뉴스 영상 목록. ingest 배치가 저장한 결과만 읽는다.

    이 경로도, 이 경로가 돌려주는 payload도 유튜브로 요청을 내지 않는다.
    재생을 누를 때 브라우저가 처음으로 유튜브에 접속한다.
    """
    try:
        payload = news_videos.get_videos()
    except news_videos.NewsVideosDisabled as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "news_videos_disabled", "message": "News video lane is disabled."},
            headers=dict(data_rights.NO_STORE_HEADERS),
        ) from exc
    except DataUnavailable as exc:
        raise HTTPException(status_code=503, detail="news videos not collected yet") from exc
    response.headers["Cache-Control"] = "public, max-age=300"
    response.headers["X-Data-Source"] = "YouTube"
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
def us_ptr_filings(
    request: Request,
    response: Response,
    ticker: str | None = Query(None, max_length=12),
) -> dict:
    """미 하원 의원 주기거래보고(PTR). ingest 배치가 저장한 결과만 읽는다.

    `ticker`를 주면 그 종목의 거래만. 티커가 보고서가 아니라 그 안의 거래에
    붙어 있어 두 단계로 좁힌다.
    """
    try:
        payload = us_ptr.get_filings(ticker=ticker)
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
    ticker: str | None = Query(None, max_length=12),
) -> dict:
    """커버 중인 티커의 8-K 이벤트 공시 피드. 저장소만 읽는다.

    `ticker`를 주면 그 종목만. 이 인자가 없던 동안 종목 화면이 그것을 붙여
    부르고 있었고, FastAPI가 모르는 쿼리를 조용히 무시해서 **커버리지 전체의
    최근 8-K가 그 종목의 것처럼 실렸다** — 애플 화면에 보잉 공시가 있었다.
    """
    try:
        payload = us_events.build_events_feed(limit, ticker=ticker)
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
