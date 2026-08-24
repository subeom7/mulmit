"""종목 허브가 크롤러에게 내용을 준다.

사이트맵에 3,000여 개의 종목 URL을 올려 두었는데, 자바스크립트를 실행하지 않는
방문자가 받는 본문이 **214자**였다(2026-08-24 실측). 크롤러가 바로 그런
방문자다. 값은 전부 JS가 나중에 채웠기 때문이고, 구글이 JS를 렌더하긴 하지만
대기열이 길다 — 거의 똑같은 214자 껍데기 3,000개는 "크롤링됨 — 색인 생성되지
않음"으로 빠지는 전형적인 모양이다.

이 파일이 고정하는 것:

1. 저장된 값이 있으면 서버가 본문을 낸다.
2. 없으면 **빈 문자열이지 500이 아니다** — 아직 수집 안 된 종목이 3,000개 중
   대부분이고, 그 페이지들은 지금과 같은 상태로 나가면 된다.
3. 요청 경로에서 **상류를 부르지 않는다**. 크롤러 한 번이 DART·SEC 3,000번이
   되면 그건 우리가 남에게 하는 짓이다.
"""

from __future__ import annotations

import datetime as dt
import html
import re

import pytest

from app import config, kr_insider, stock_page
from app.kr_stocks import stock_series_spec

TODAY = dt.date(2026, 8, 21)


def _visible_text(page: str) -> str:
    body = re.search(r"(?is)<body[^>]*>(.*)</body>", page)
    inner = body.group(1) if body else page
    inner = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", inner)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", inner))).strip()


@pytest.fixture
def kr_stock(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FSC_API_KEY", "test-key")
    db.save_kr_listings(
        [{"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
          "isin_cd": "KR7000660001", "clpr": 1593000.0, "flt_rt": -0.5,
          "mrkt_tot_amt": 1.1e15}],
        "2026-08-21",
    )
    values, price = [], 1_000_000.0
    for offset in range(400, 0, -1):
        day = TODAY - dt.timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        price *= 1.001
        values.append((day, round(price, 2)))
    spec = stock_series_spec("000660", "SK하이닉스")
    db.save_economic_series(
        spec.series_key, provider_id="fsc", provider_series_id="000660",
        metadata_fields={"title": "SK하이닉스", "units": "KRW", "units_short": "원",
                         "frequency": "Daily", "frequency_short": "D"},
        observations=values, publisher="금융위원회",
        publisher_url="https://www.fsc.go.kr/",
        series_url="https://www.data.go.kr/data/15094808/openapi.do",
        rights_status="approved",
    )
    return "000660"


def test_a_stock_with_stored_values_renders_a_body(kr_stock):
    body = stock_page.render(kr_stock, korean=True)
    text = _visible_text(body)
    assert "시세 요약" in body
    assert "52주 범위" in text and "최대 낙폭" in text
    # 종가만 저장된 종목의 실측 크기다. 재무제표·내부자가 모이면 훨씬 커진다.
    assert len(text) > 80, f"본문이 여전히 얇다: {len(text)}자"


def test_a_stock_with_nothing_stored_renders_nothing_rather_than_failing(db):
    """3,000개 중 대부분이 아직 수집 전이다. 그 페이지들은 지금 상태로 나가면 된다."""
    assert stock_page.render("999999", korean=True) == ""
    assert stock_page.render("NOSUCH", korean=False) == ""


def test_the_render_never_calls_upstream(kr_stock, monkeypatch):
    """크롤러 한 번이 DART 3,000번이 되면 그건 우리가 남에게 하는 짓이다.

    DART 공급자를 폭발물로 바꿔 둔다 — 렌더가 그것을 건드리면 터진다.
    """
    def explode(*args, **kwargs):
        raise AssertionError("렌더 경로에서 상류를 불렀다")

    monkeypatch.setattr(kr_insider, "_provider", explode)
    body = stock_page.render(kr_stock, korean=True)
    assert "시세 요약" in body, "상류 없이도 저장된 값으로 본문이 나와야 한다"


def test_the_page_substitutes_the_placeholder(kr_stock):
    from fastapi.testclient import TestClient

    from app.main import app

    page = TestClient(app).get(f"/stock/{kr_stock}").text
    assert "{{SSR}}" not in page, "자리표시자가 그대로 나가면 화면에 중괄호가 보인다"
    # 아무것도 없을 때가 214자였다(2026-08-24 실측). 종가만 있어도 그보다 늘어야 한다.
    assert len(_visible_text(page)) > 260, "크롤러가 읽을 것이 늘어야 한다"


def test_the_indexing_block_is_not_hidden() -> None:
    """숨긴 텍스트는 가중치가 깎이고, JS가 실패한 사람에게 빈 화면을 준다.

    대신 화면 스크립트가 진짜 섹션을 그린 뒤에 지운다 — 실패하면 남아서 대신
    읽힌다.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "static" / "stock.html").read_text(
        encoding="utf-8"
    )
    assert '<div id="ssr-body">{{SSR}}</div>' in source, "숨김 속성 없이 서야 한다"
    assert "if (ssr && drew) ssr.remove();" in source, (
        "진짜 섹션이 하나라도 섰을 때만 지운다 — 아무것도 못 그렸는데 지우면 빈 페이지가 남는다"
    )
