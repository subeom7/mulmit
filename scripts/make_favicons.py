"""Rasterize the Mulmit favicon mark into the PNG/ICO set search engines need.

The SVG (`app/static/brand/mulmit-favicon.svg`) is the source of truth: a
rounded dark square with the "M" split at the waterline — white above, blue
below. Google Search wants a square raster that is a multiple of 48px and
Naver reads /favicon.ico, so this script redraws the same geometry with
Pillow at 16x supersampling and writes:

    favicon-16/32/48/96/192/512.png, apple-touch-icon.png (180, opaque),
    favicon.ico (16+32+48), maskable-192/512.png (PWA)

The maskable pair is for the web app manifest (``purpose: "maskable"``).
Android crops installed-app icons to arbitrary shapes and only guarantees
the inner 80% circle (radius 40% of the edge). The mark's corners sit at
~29.7 units from center on the 64-unit canvas — outside that 25.6-unit
radius — so the maskable render shrinks the mark to 0.85 around center
(29.7 x 0.85 = 25.2) and fills the whole square with the brand background.

Run from the repo root: ``python scripts/make_favicons.py``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

BRAND = Path(__file__).resolve().parents[1] / "app" / "static" / "brand"
BG = (0x0F, 0x12, 0x14, 255)
ABOVE = (0xF3, 0xF6, 0xF8, 255)
BELOW = (0x42, 0xA5, 0xFF, 255)
# From the SVG path: M10 52 V12 H22 L32 29 L42 12 H54 V52 H44 V28 L32 45 L20 28 V52 Z
MARK = [(10, 52), (10, 12), (22, 12), (32, 29), (42, 12), (54, 12), (54, 52), (44, 52),
        (44, 28), (32, 45), (20, 28), (20, 52)]
WATERLINE_TOP = 32.5  # white clip ends here
WATERLINE_BOTTOM = 35.5  # blue clip starts here
RADIUS = 14  # rx on the 64-unit viewBox


def render(
    size: int, *, opaque: bool = False, shrink: float = 1.0, supersample: int = 16
) -> Image.Image:
    big = 64 * supersample
    scale = supersample
    canvas = Image.new("RGBA", (big, big), BG if opaque else (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    if not opaque:
        draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=RADIUS * scale, fill=BG)

    def toward_center(value: float) -> float:
        return 32 + (value - 32) * shrink

    polygon = [(toward_center(x) * scale, toward_center(y) * scale) for x, y in MARK]
    mark = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mark).polygon(polygon, fill=255)

    above = Image.new("L", (big, big), 0)
    ImageDraw.Draw(above).rectangle((0, 0, big, int(toward_center(WATERLINE_TOP) * scale)), fill=255)
    below = Image.new("L", (big, big), 0)
    ImageDraw.Draw(below).rectangle(
        (0, int(toward_center(WATERLINE_BOTTOM) * scale), big, big), fill=255
    )

    from PIL import ImageChops

    canvas.paste(Image.new("RGBA", (big, big), ABOVE), mask=ImageChops.multiply(mark, above))
    canvas.paste(Image.new("RGBA", (big, big), BELOW), mask=ImageChops.multiply(mark, below))
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    BRAND.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 96, 192, 512):
        render(size).save(BRAND / f"favicon-{size}.png", optimize=True)
    render(180, opaque=True).save(BRAND / "apple-touch-icon.png", optimize=True)
    for size in (192, 512):
        render(size, opaque=True, shrink=0.85).save(BRAND / f"maskable-{size}.png", optimize=True)
    # Pillow only keeps ICO sizes no larger than the base frame, so the base is
    # the biggest one and the smaller frames ride along explicitly.
    ico_frames = [render(size) for size in (48, 32, 16)]
    ico_frames[0].save(
        BRAND / "favicon.ico",
        format="ICO",
        sizes=[(48, 48), (32, 32), (16, 16)],
        append_images=ico_frames[1:],
    )
    listed = sorted(BRAND.glob("favicon*")) + sorted(BRAND.glob("maskable-*"))
    for path in listed + [BRAND / "apple-touch-icon.png"]:
        print(f"{path.name:22s} {path.stat().st_size:6d} B")


if __name__ == "__main__":
    main()
