"""13F 카드의 인물 사진을 내려받아 카드 크기로 굽는다.

**개발 머신 전용이다.** Pillow는 `requirements.txt`에 없고 CI는 그 파일만
설치하므로, 앱이나 테스트가 이 모듈을 import하면 수집 단계에서 배포가 막힌다
(2026-08-21에 실제로 겪었다). 결과물만 저장소에 담기고 이 스크립트는 출처를
남기는 기록으로 함께 둔다.

왜 자체 호스팅인가
------------------
커먼즈에서 바로 불러오면(핫링크) 읽는 사람의 브라우저가 위키미디어 서버를
때린다. 이 사이트는 쿠키를 심지 않는 것을 방침으로 걸어 두었고, 외부 요청은
그 자체로 방문 사실을 흘린다. 파일이 넷뿐이고 각 15KB 아래라 담아 두는 편이
싸다.

라이선스
--------
전부 위키미디어 커먼즈에서 왔고 자유 라이선스만 골랐다. **자르고 줄이는 것은
변형(adaptation)에 해당한다** — CC BY-SA 항목은 가공본도 같은 라이선스로
표시해야 한다. 표기 문구는 `app/us_managers.py`의 `PORTRAITS`가 들고 있고
화면까지 payload로 실려 간다.

    python scripts/fetch_portraits.py
"""

from __future__ import annotations

import io
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

OUT_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "portraits"
UA = "Mulmit/1.0 (https://mulmit.com) portrait fetch"

#: 카드에 88px로 놓고 고해상도 화면을 위해 2배로 굽는다.
SIZE = 176

#: (slug, 커먼즈 파일명, 세로 기준점 0~1, 가로 기준점 0~1, 확대율 0~1)
#: 뒤의 셋은 결과를 눈으로 보고 맞춘 값이다. 가운데를 그냥 자르면 인물 사진은
#: 이마 위가 잘리거나 턱이 날아가고, 원본이 넓게 찍힌 사진은 얼굴이 작게
#: 들어간다(캐시 우드가 그랬다 — 확대율 0.62로 당겼다).
SOURCES = [
    ("buffett", "Warren Buffett at the 2015 SelectUSA Investment Summit (cropped).jpg",
     0.02, 0.50, 1.00),
    ("ackman", "Valeant Pharmaceuticals' Business Model (headshot).jpg",
     0.00, 0.50, 1.00),
    ("wood", "Cathie Wood ARK Invest Photo.jpg",
     0.06, 0.52, 0.62),
    ("dalio", "Web Summit 2018 - Forum - Day 2, November 7 HM1 7481 (44858045925).jpg",
     0.06, 0.50, 1.00),
]


def commons_url(filename: str) -> str:
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
           "&iiprop=url&titles=" + urllib.parse.quote("File:" + filename))
    request = urllib.request.Request(api, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    page = next(iter(payload["query"]["pages"].values()))
    return page["imageinfo"][0]["url"]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read()


def square(image: Image.Image, top_bias: float, x_bias: float, zoom: float) -> Image.Image:
    """정사각형으로 자른다.

    `zoom`이 1보다 작으면 그만큼 좁은 정사각형을 떠서 얼굴을 당긴다. 기준점은
    `x_bias`(가로)와 `top_bias`(세로)로, 둘 다 남는 여백 안에서의 비율이다.
    """
    width, height = image.size
    side = int(min(width, height) * zoom)
    left = int((width - side) * x_bias)
    top = int((height - side) * top_bias)
    left = max(0, min(left, width - side))
    top = max(0, min(top, height - side))
    return image.crop((left, top, left + side, top + side))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug, filename, top_bias, x_bias, zoom in SOURCES:
        url = commons_url(filename)
        raw = fetch(url)
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        cut = square(image, top_bias, x_bias, zoom).resize((SIZE, SIZE), Image.LANCZOS)
        target = OUT_DIR / f"{slug}.webp"
        cut.save(target, "WEBP", quality=82, method=6)
        print(f"{slug:8} {image.size[0]}x{image.size[1]} -> {SIZE}x{SIZE} "
              f"{target.stat().st_size // 1024}KB  {target.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
