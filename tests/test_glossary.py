"""용어 사전 `/glossary`.

이 페이지의 존재 이유는 "펀딩비 뜻" 같은 검색 유입이다. 그래서 검증할 것은
"200이 나온다"가 아니라 **본문이 HTML 안에 있다**는 것이다 — 크롤러는 JS를
실행하지 않는다. 그리고 화면의 용어 팝오버와 사전이 갈라지지 않는지도 함께
본다. 두 벌이 되는 순간 같은 말이 화면마다 다르게 설명된다.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import config, glossary
from app.main import app

TERMS_FILE = Path(config.STATIC_DIR) / "terms.json"


def _terms() -> dict:
    return json.loads(TERMS_FILE.read_text(encoding="utf-8"))


def test_every_term_is_rendered_into_the_html():
    """JS 없이 읽히는지. 항목 하나라도 빠지면 그 검색어를 잃는다."""
    client = TestClient(app)
    response = client.get("/glossary")
    assert response.status_code == 200
    body = response.text
    assert "{{" not in body, "치환되지 않은 자리표시자가 남았다"

    data = _terms()
    for term_id, entry in data["terms"].items():
        assert f'id="{term_id}"' in body, f"{term_id} 항목이 렌더되지 않았다"
        for lang in ("ko", "en"):
            # 본문은 이스케이프돼 들어간다(작은따옴표가 &#x27;이 되는 식).
            # 같은 규칙으로 이스케이프한 뒤 앞부분을 비교한다.
            definition = html.escape(entry[lang]["def"], quote=True)
            assert definition[:24] in body, f"{term_id}/{lang} 정의가 본문에 없다"


def test_every_term_belongs_to_a_declared_group():
    """묶음 없는 용어는 화면에서 조용히 사라진다."""
    data = _terms()
    declared = set(data["groups"])
    for term_id, entry in data["terms"].items():
        assert entry.get("group") in declared, f"{term_id}의 묶음이 선언되지 않았다"


def test_every_term_has_all_three_lines_in_both_languages():
    """뜻·읽는 법·흔한 오해 셋이 이 사전의 약속이다. 하나라도 비면 형식이 깨진다."""
    for term_id, entry in _terms()["terms"].items():
        for lang in ("ko", "en"):
            text = entry.get(lang)
            assert text, f"{term_id}에 {lang}가 없다"
            for field in ("title", "def", "read", "caution"):
                assert text.get(field), f"{term_id}/{lang}에 {field}가 비었다"


def test_structured_data_covers_the_same_terms():
    """검색엔진이 읽는 목록과 사람이 읽는 목록이 같아야 한다."""
    payload = json.loads(glossary.json_ld().replace("<\\/", "</"))
    assert payload["@type"] == "DefinedTermSet"
    coded = {term["termCode"] for term in payload["hasDefinedTerm"]}
    assert coded == set(_terms()["terms"]), "JSON-LD와 사전의 용어 목록이 어긋난다"


def test_popover_targets_exist_in_the_dictionary():
    """화면이 부르는 용어가 사전에 있어야 한다.

    `data-term="…"`은 팝오버가 사전에서 찾을 열쇠다. 오타가 나면 클릭해도
    아무 일이 없고, 그건 콘솔 에러도 없이 조용히 실패한다.
    """
    known = set(_terms()["terms"])
    used: set[str] = set()
    for page in Path(config.STATIC_DIR).glob("*.html"):
        used |= set(re.findall(r'data-term="([a-z0-9-]+)"', page.read_text(encoding="utf-8")))
    assert used, "어느 화면도 용어를 걸어 두지 않았다"
    assert used <= known, f"사전에 없는 용어를 화면이 부른다: {sorted(used - known)}"


def test_glossary_is_listed_in_the_sitemap():
    client = TestClient(app)
    sitemap = client.get("/sitemap-pages.xml")
    assert sitemap.status_code == 200
    assert "https://mulmit.com/glossary" in sitemap.text
