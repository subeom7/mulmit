"""주말 참고가 전용 페이지.

**이 페이지의 존재 이유가 색인이다.** 이 사이트의 문제는 기능이 아니라
유입이고(2026-08-24 실측: 색인 5개 / 미색인 2,957개), `물밑`은 일반명사라
잡을 수 없지만 `주말 삼성전자 주가` 같은 롱테일 질의는 잡을 수 있다. 그
질의에만 답하는 자리가 없어서 만들었다.

그래서 여기 있는 검사는 두 갈래다.

1. **크롤러가 실제로 읽는가** — JS로 채우면 이 페이지를 만든 뜻이 없다.
2. **말하면 안 되는 것을 말하지 않는가** — 훅으로 쓰기 좋은 문장
   ("월요일에 얼마로 출발할지")을 우리 자신의 고지가 부정한다. 그 선을
   테스트가 지킨다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import data_rights, weekend_page
from app.main import app

client = TestClient(app)
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.fixture(scope="module")
def page() -> str:
    response = client.get("/weekend")
    assert response.status_code == 200, response.text
    return response.text


def _text(html: str) -> str:
    body = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S)
    return re.sub(r"<[^>]+>", " ", body)


# --- 1. 크롤러가 읽는가 -------------------------------------------------------

def test_the_page_is_rendered_by_the_server(page):
    """자리표시자가 남아 있으면 렌더가 반쪽이다."""
    assert not re.findall(r"\{\{[A-Z_]+\}\}", page), "치환되지 않은 자리표시자가 있다"


def test_the_body_is_not_an_empty_shell(page):
    """`/stock/*`가 214자였던 것이 이 모든 작업의 출발점이다."""
    words = len(_text(page).split())
    assert words > 150, f"크롤러가 받는 본문이 {words}단어뿐이다"


def test_the_page_says_the_words_people_search(page):
    """제목·본문이 실제 질의를 담아야 그 질의로 잡힌다."""
    text = _text(page)
    for phrase in ("주말", "삼성전자", "SK하이닉스", "참고가"):
        assert phrase in text, f"본문에 {phrase!r}가 없다"
    assert "주말 삼성전자" in page, "제목이 질의를 담지 않는다"


def test_the_answers_are_in_the_body_not_only_in_structured_data(page):
    """본문에 없는 것을 구조화 데이터로만 주장하지 않는다."""
    block = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    assert block, "FAQPage 구조화 데이터가 없다"
    payload = json.loads(block.group(1))
    assert payload["@type"] == "FAQPage"

    text = _text(page)
    for entry in payload["mainEntity"]:
        question = entry["name"]
        assert question in text, f"구조화 데이터의 질문이 본문에 없다: {question}"


def test_the_page_is_in_the_sitemap():
    sitemap = (STATIC / "sitemap-pages.xml").read_text(encoding="utf-8")
    assert "https://mulmit.com/weekend" in sitemap


def test_the_page_declares_its_own_address(page):
    assert '<link rel="canonical" href="https://mulmit.com/weekend">' in page


# --- 2. 말하면 안 되는 것 ----------------------------------------------------

def test_every_mention_of_the_monday_open_is_a_denial(page):
    """훅으로 쓰기 좋은 문장이지만 **우리 고지가 정면으로 부정한다.**

    `/api/market/weekend`가 이미 적어 두었다 — 얕은 유동성·레버리지·기초자산
    괴리 때문에 크게 왜곡될 수 있다고. 홍보가 제품 고지와 반대면 둘 중 하나가
    거짓이 되고, 그 훅으로 데려온 사람은 월요일에 배신감을 느낀다.

    처음엔 "월요일 시초가"라는 말이 **나오면** 실패하게 썼는데, 그러면 정직한
    부인문까지 걸린다 — 한국어는 부정이 뒤에 오기 때문이다("…이 아닙니다",
    "…쓰면 안 됩니다"). 금지어를 세는 대신 **규칙을 검사한다**: 월요일 시초가를
    입에 올렸다면 그 자리에서 부인해야 한다.
    """
    text = _text(page)
    negations = ("아닙니다", "아니며", "아니라", "안 됩니다", "다를 수", "예측이 아")
    mentions = list(re.finditer(r"월요일 시초가|시초가 예측|월요일에 얼마", text))
    assert mentions, "월요일 오해를 아예 언급조차 하지 않는다 — 읽는 사람은 그렇게 오해한다"
    for match in mentions:
        window = text[match.end(): match.end() + 40]
        assert any(word in window for word in negations), (
            f"부인 없이 월요일 시초가를 말한다: ...{text[match.start():match.end() + 40]}..."
        )


def test_the_page_says_plainly_that_it_is_not_the_monday_open(page):
    """말하지 않는 것만으로는 부족하다 — 읽는 사람이 그렇게 오해하기 때문에,
    **아니라고 적어야** 한다."""
    text = _text(page)
    assert "월요일 시초가인가요" in text
    assert "아닙니다" in text
    assert "실제 체결가" in text


def test_the_page_says_these_are_not_real_trades(page):
    text = _text(page)
    assert "실제 체결가는 없습니다" in text or "실제 체결가가 아" in text


def test_the_footer_carries_the_standing_notice(page):
    assert "투자 권유가 아니" in _text(page)


# --- 3. 권리 -----------------------------------------------------------------

def test_the_page_asks_the_rights_gate_before_showing_values():
    """`/api/kr/overnight`는 `require_hip3_public_display()`를 거친다.

    SSR이 `build_kr_overnight()`을 곧장 부르면 **그 문을 돌아서 들어가는**
    셈이 된다. 게이트가 닫혀 있으면 값 없이 설명만 나와야 한다.
    """
    source = (Path(__file__).resolve().parents[1] / "app" / "weekend_page.py").read_text(
        encoding="utf-8"
    )
    assert "data_rights.hip3_public_display_enabled()" in source, "권리를 묻지 않는다"
    # 게이트가 닫힌 상태(테스트 환경)에서는 값이 나가면 안 된다.
    if not data_rights.hip3_public_display_enabled():
        rendered = weekend_page.render()
        assert rendered["ASOF"] == ""
        assert "원" not in rendered["ROWS"], "게이트가 닫혔는데 값이 나갔다"


def test_the_page_still_answers_when_the_gate_is_closed(page):
    """표가 비어도 질문에는 답한다 — 설명이 이 페이지의 절반이다."""
    text = _text(page)
    assert "한국거래소는" in text
    assert "금요일 20시부터 월요일 8시" in text


# --- 4. 다른 화면과 어긋나지 않는가 -------------------------------------------

def test_the_weekend_window_matches_the_lane():
    """세션 창을 페이지가 따로 적고 있다. lane이 말하는 것과 갈라지면
    두 화면이 다른 말을 하게 된다."""
    source = (Path(__file__).resolve().parents[1] / "app" / "weekend_signals.py").read_text(
        encoding="utf-8"
    )
    assert "Friday 20:00 through Monday 08:00 KST" in source, (
        "lane의 세션 창이 바뀌었다 — 페이지의 '금요일 20시부터 월요일 8시'도 함께 고쳐라"
    )

# --- 5. 단위와 범위 ----------------------------------------------------------
#
# 배포하고 라이브를 보다가 나온 것들이다. 둘 다 값은 진짜인데 **표시가 거짓**인
# 종류라, 테스트가 초록인 채로 나갔다.

def test_an_index_is_not_priced_in_won():
    """라이브에 **`코스피 200 → 1,054원`** 이 찍혔다(2026-08-25).

    지수의 단위는 `pt`이고 그 사실이 카드에 이미 적혀 있었다 — 읽지 않은 쪽이
    틀렸다. 단위는 가정하지 않고 페이로드가 들고 있는 것을 쓴다.
    """
    from app.weekend_page import _amount

    assert _amount(257000.0, "KRW") == "257,000원"
    assert _amount(1054.01, "pt") == "1,054.01pt"
    assert "원" not in _amount(1054.01, "pt")
    assert _amount(None, "KRW") == "—"


def test_the_adr_card_stays_off_this_page():
    """SK하이닉스 ADR의 `vs_official_percent`는 실측 **30.5%** 다 — 고장이 아니라
    ADR 프리미엄이다(원주 1주 = ADR 10주).

    그 값을 이 표에 넣으면 원화 두 값이 30% 벌어진 채 나란히 놓여 **깨진 것처럼
    보인다.** 여기 온 사람은 프리미엄을 물으러 온 것이 아니다. EWY는 값이 아예
    `null`이라 빈 줄이 된다. 둘 다 `/kr`에서 제 맥락과 함께 본다.
    """
    from app import weekend_page

    assert "adr" not in weekend_page.PAGE_KINDS
    assert "us_etf" not in weekend_page.PAGE_KINDS
    assert set(weekend_page.PAGE_KINDS) == {"equity", "index"}


def test_only_the_scoped_kinds_reach_the_table():
    from unittest import mock

    from app import weekend_page

    cards = [
        {"id": "a", "kind": "equity", "label": {"ko": "삼성전자"}, "code": "005930",
         "official": {"status": "ok", "close": 257000.0, "unit": "KRW", "date": "2026-08-24"},
         "implied": {"status": "ok", "value": 257992.7, "unit": "KRW"},
         "session_reference": {"status": "ok", "vs_percent": 0.4}},
        {"id": "b", "kind": "index", "label": {"ko": "코스피 200"},
         "official": {"status": "ok", "close": 1054.01, "unit": "pt", "date": "2026-08-24"},
         "implied": {"status": "ok", "value": 1063.3, "unit": "pt"},
         "session_reference": {"status": "ok", "vs_percent": 0.11}},
        {"id": "c", "kind": "adr", "label": {"ko": "SK하이닉스 ADR"},
         "official": {"status": "ok", "close": 1671000.0, "unit": "KRW", "date": "2026-08-24"},
         "implied": {"status": "ok", "value": 2180933.8, "unit": "KRW"},
         "session_reference": {"status": "ok", "vs_percent": -0.9}},
    ]
    payload = {"cards": cards, "session": {"active": True},
               "disclaimer": {"ko": "x"}, "source": {}}
    with mock.patch.object(weekend_page.data_rights, "hip3_public_display_enabled", lambda: True),          mock.patch.object(weekend_page.kr_overnight, "build_kr_overnight", lambda: payload):
        rows = weekend_page.render()["ROWS"]

    assert "삼성전자" in rows and "코스피 200" in rows
    assert "ADR" not in rows, "ADR 카드가 표에 들어왔다"
    assert "1,054.01pt" in rows, "지수가 pt로 나오지 않는다"
    assert "1,054원" not in rows
