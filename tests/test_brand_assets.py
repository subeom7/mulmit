"""Favicon set: search engines need a real ICO at /favicon.ico and square PNGs.

Google's search-result favicon wants a square raster in multiples of 48px and
Naver reads /favicon.ico directly; an SVG-only setup left a blank globe in
both. These pin the served formats and the <link> declarations on every page.
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import config
from app.main import app

BRAND = Path(config.STATIC_DIR) / "brand"


def test_favicon_ico_is_a_real_multi_size_ico():
    response = TestClient(app).get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/x-icon")
    icon = Image.open(io.BytesIO(response.content))
    assert icon.format == "ICO"
    assert {(16, 16), (32, 32), (48, 48)} <= set(icon.info["sizes"])


def test_png_set_is_square_at_the_sizes_the_pages_declare():
    for name, size in (
        ("favicon-96.png", 96),
        ("favicon-192.png", 192),
        ("favicon-512.png", 512),
        ("apple-touch-icon.png", 180),
    ):
        image = Image.open(BRAND / name)
        assert image.size == (size, size), name
        assert image.format == "PNG", name


def test_every_public_page_declares_ico_png_svg_and_apple_touch_icons():
    pages = [p for p in Path(config.STATIC_DIR).glob("*.html") if not p.name.startswith("naver")]
    assert pages
    for page in pages:
        head = page.read_text(encoding="utf-8").split("</head>", 1)[0]
        assert 'rel="icon" href="/favicon.ico"' in head, page.name
        assert 'sizes="96x96" href="/static/brand/favicon-96.png"' in head, page.name
        assert 'type="image/svg+xml" href="/static/brand/mulmit-favicon.svg"' in head, page.name
        assert 'rel="apple-touch-icon"' in head, page.name
