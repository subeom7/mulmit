"""Favicon set: search engines need a real ICO at /favicon.ico and square PNGs.

Google's search-result favicon wants a square raster in multiples of 48px and
Naver reads /favicon.ico directly; an SVG-only setup left a blank globe in
both. These pin the served formats and the <link> declarations on every page.
The headers are parsed by hand so the test suite needs no imaging library —
Pillow is only a dev dependency of scripts/make_favicons.py.
"""

from __future__ import annotations

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
    # Search-engine ownership files live beside the pages but are not pages.
    pages = [
        p for p in Path(config.STATIC_DIR).glob("*.html")
        if not p.name.startswith(("naver", "google"))
    ]
    assert pages
    for page in pages:
        head = page.read_text(encoding="utf-8").split("</head>", 1)[0]
        assert 'rel="icon" href="/favicon.ico"' in head, page.name
        assert 'sizes="96x96" href="/static/brand/favicon-96.png"' in head, page.name
        assert 'type="image/svg+xml" href="/static/brand/mulmit-favicon.svg"' in head, page.name
        assert 'rel="apple-touch-icon"' in head, page.name
