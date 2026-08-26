"""Favicon set: search engines need a real ICO at /favicon.ico and square PNGs.

Google's search-result favicon wants a square raster in multiples of 48px and
Naver reads /favicon.ico directly; an SVG-only setup left a blank globe in
both. These pin the served formats and the <link> declarations on every page.
The headers are parsed by hand so the test suite needs no imaging library —
Pillow is only a dev dependency of scripts/make_favicons.py.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

from fastapi.testclient import TestClient

from app import config
from app.main import app

BRAND = Path(config.STATIC_DIR) / "brand"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _ico_sizes(data: bytes) -> set[tuple[int, int]]:
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1, "not an ICO header"
    sizes = set()
    for index in range(count):
        width, height = data[6 + index * 16], data[7 + index * 16]
        sizes.add((width or 256, height or 256))
    return sizes


def _png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == PNG_SIGNATURE, "not a PNG"
    assert data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_favicon_ico_is_a_real_multi_size_ico():
    response = TestClient(app).get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/x-icon")
    assert {(16, 16), (32, 32), (48, 48)} <= _ico_sizes(response.content)


def test_png_set_is_square_at_the_sizes_the_pages_declare():
    for name, size in (
        ("favicon-96.png", 96),
        ("favicon-192.png", 192),
        ("favicon-512.png", 512),
        ("apple-touch-icon.png", 180),
    ):
        assert _png_size((BRAND / name).read_bytes()) == (size, size), name


def test_every_public_page_declares_ico_png_svg_and_apple_touch_icons():
    # Search-engine ownership files live beside the pages but are not pages,
    # and offline.html is the service worker's fallback — deliberately
    # self-contained, so it declares no external icon links.
    pages = [
        p for p in Path(config.STATIC_DIR).glob("*.html")
        if not p.name.startswith(("naver", "google")) and p.name != "offline.html"
    ]
    assert pages
    for page in pages:
        head = page.read_text(encoding="utf-8").split("</head>", 1)[0]
        assert 'rel="icon" href="/favicon.ico"' in head, page.name
        assert 'sizes="96x96" href="/static/brand/favicon-96.png"' in head, page.name
        assert 'type="image/svg+xml" href="/static/brand/mulmit-favicon.svg"' in head, page.name
        assert 'rel="apple-touch-icon"' in head, page.name


# --- 웹폰트 -----------------------------------------------------------------

FONT_DIR = Path(config.STATIC_DIR) / "fonts" / "pretendard"
WOFF2_SIGNATURE = b"wOF2"


def test_pretendard_is_self_hosted_and_complete():
    """폰트는 저장소가 들고 있어야 한다 — 제3자 CDN 요청을 만들지 않는다.

    구간 분할본이라 CSS가 참조하는 파일이 하나라도 빠지면 그 유니코드 대역만
    조용히 시스템 글꼴로 떨어진다. 눈에 잘 안 띄는 실패라 개수를 못 박는다.
    """
    stylesheet = (FONT_DIR / "PretendardVariable-dynamic-subset.css").read_text(encoding="utf-8")
    referenced = re.findall(r"url\((\./woff2-dynamic-subset/[^)]+)\)", stylesheet)
    assert referenced, "분할본 CSS가 woff2를 하나도 참조하지 않는다"
    for relative in referenced:
        assert (FONT_DIR / relative[2:]).is_file(), f"참조된 폰트가 없다: {relative}"
    assert (FONT_DIR / "OFL.txt").is_file(), "OFL 라이선스 원문이 함께 있어야 한다"


def test_woff2_is_served_as_a_font_not_as_text():
    """StaticFiles는 mimetypes 표에 기대고, 그 표는 OS마다 다르다.

    woff2를 모르는 환경에서는 바이너리가 `text/plain; charset=utf-8`로 나갔다
    (윈도우 실측). 브라우저가 스니핑해서 대개는 그려지지만, charset이 붙은
    바이너리는 중간의 프록시가 변환을 시도하면 그대로 깨진다.
    """
    client = TestClient(app)
    response = client.get("/static/fonts/pretendard/woff2-dynamic-subset/PretendardVariable.subset.0.woff2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "font/woff2"
    assert response.content[:4] == WOFF2_SIGNATURE

def test_the_root_carries_both_naver_ownership_proofs():
    """네이버는 http와 https를 **다른 사이트**로 본다.

    그래서 소유확인이 둘 필요하다. http:// 쪽은 루트에 놓인 파일
    (naverf28e…html)로, https:// 쪽은 루트 문서의 메타 태그로 확인한다.
    메타가 사라지면 https:// 사이트의 소유확인이 풀리고, 거기 붙여 둔
    사이트맵 제출이 통째로 무의미해진다 — 그런데 화면은 멀쩡해 보인다.
    """
    static = Path(config.STATIC_DIR)
    files = [p.name for p in static.glob("naver*.html")]
    assert files, "http:// 소유확인 파일이 사라졌다"

    head = (static / "landing.html").read_text(encoding="utf-8").split("</head>", 1)[0]
    assert 'name="naver-site-verification"' in head, "https:// 소유확인 메타가 루트에 없다"
