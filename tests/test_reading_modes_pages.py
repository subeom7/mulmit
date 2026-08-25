"""쉬움 / 전문가 모드를 /kr · /us · /bio까지 넓힌 규칙 (2026-08-26).

넓히기 전 상태가 문제였다. `/kr`은 **토글이 있는데 모드별 내용이 하나도 없어서**
누르면 아무 일도 안 났고(누르는 사람은 자기가 뭘 잘못했다고 생각한다), `/bio`는
토글도 스크립트도 없었다.

여기서 지키는 것은 셋이다: 토글이 있는 페이지는 실제로 뭔가 달라질 것,
용어 다리는 **있는 항목만** 가리킬 것, 그리고 권리 표기는 어느 모드에서도
사라지지 않을 것.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
DASHBOARDS = ["kr.html", "us.html", "bio.html", "crypto.html", "landing.html"]

# 마크업이 아니라 monitor.js가 모드를 붙이는 페이지. 값은 그 표식 자체라,
# 렌더러에서 사라지면 테스트가 바로 잡는다.
RENDERED_MODE_MARKERS = {
    "bio.html": '"bio-pub pro-only"',  # 임상 표의 서지 줄 (등록번호도 같은 함수)
}


def _text(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("page", DASHBOARDS)
def test_a_page_with_the_toggle_can_actually_answer_it(page: str) -> None:
    """토글만 있고 모드별 내용이 없으면 누르는 사람에게는 고장 난 버튼이다.

    2026-08-26 이전의 `/kr`이 정확히 그랬다 — 토글은 마스트에 있는데 페이지
    전체에 `.easy-only`도 `.pro-only`도 하나 없었다.
    """
    source = _text(page)
    if 'id="mode-switch"' not in source:
        pytest.skip(f"{page}에는 토글이 없다")
    assert "console.js" in source, (
        f"{page}: 토글을 움직이는 스크립트가 없다 — 버튼만 있고 아무 일도 안 난다"
    )
    if re.search(r"easy-only|pro-only", source):
        return
    # 마크업에 없다면 렌더러가 붙이는 것이어야 한다. 페이지 이름만 예외로 적어
    # 두면 그 목록이 썩으므로, 표식이 **실제로 monitor.js에 있는지**까지 본다.
    marker = RENDERED_MODE_MARKERS.get(page)
    assert marker, f"{page}: 모드로 갈리는 내용이 하나도 없다 — 토글이 거짓말을 한다"
    js = _text("monitor.js")
    assert marker in js, (
        f"{page}: 렌더러가 붙이던 표식 {marker!r}이 monitor.js에서 사라졌다 — "
        "이 페이지의 토글은 이제 아무 일도 안 한다"
    )


def test_kr_and_us_and_bio_all_carry_the_toggle() -> None:
    """넓힌 대상 세 곳. 하나라도 빠지면 사이트가 페이지마다 다르게 행동한다."""
    for page in ("kr.html", "us.html", "bio.html"):
        assert 'id="mode-switch"' in _text(page), f"{page}에 토글이 없다"


def test_every_glossary_link_points_at_a_term_that_exists() -> None:
    """죽은 앵커는 없느니만 못하다 — 눌렀는데 아무 데도 안 가면 사전을 안 믿게 된다."""
    known = set(json.loads((STATIC / "terms.json").read_text(encoding="utf-8"))["terms"])
    dead = []
    for page in STATIC.glob("*.html"):
        for anchor in re.findall(r'/glossary#([a-z0-9-]+)', page.read_text(encoding="utf-8")):
            if anchor not in known:
                dead.append(f"{page.name}: #{anchor}")
    assert not dead, f"사전에 없는 용어를 가리킨다: {dead}"


def test_term_bridges_speak_the_readers_language() -> None:
    """안내문만 두 언어로 갈리고 링크 라벨은 한 벌이면, 영어 독자에게 한글이 뜬다.

    `/crypto`가 그렇게 짜여 있었다(2026-08-26 실측). 넓히면서 아홉 곳을 모두
    양언어로 고쳤다 — 링크는 각 언어 span **안에** 들어가야 한다.
    """
    offenders = []
    for page in STATIC.glob("*.html"):
        source = page.read_text(encoding="utf-8")
        for block in re.findall(r'<p class="easy-only term-hints">(.*?)</p>', source, re.S):
            for lang in ("ko", "en"):
                span = re.search(rf'<span class="lang-{lang}">(.*?)</span>', block, re.S)
                if not span or "/glossary#" not in span.group(1):
                    offenders.append(f"{page.name}: lang-{lang} 안에 링크가 없다")
    assert not offenders, offenders


def test_attribution_never_hides_with_the_mode() -> None:
    """출처 표기는 권리 조건이다. 모드로 접으면 조건을 어기는 것이다.

    `/bio`의 `.kro-method`는 방법론이 아니라 **ClinicalTrials.gov · PubMed ·
    식약처 출처 링크**를 담고 있다(실측). 쉬움 모드에서 방법론을 접는 규칙을
    일반화하려다 이걸 함께 지울 뻔했다.
    """
    css = (STATIC / "console.css").read_text(encoding="utf-8")
    hides = re.findall(r'html\[data-mode="easy"\][^{]*\{[^}]*display:\s*none[^}]*\}', css)
    for rule in hides:
        selector = rule.split("{")[0]
        assert "#bio" not in selector and "bio-" not in selector, (
            f"쉬움 모드가 /bio의 요소를 숨긴다 — 출처 표기가 그 안에 있다: {selector.strip()}"
        )
    js = (STATIC / "monitor.js").read_text(encoding="utf-8")
    assert 'className = "kro-method"' in js and 'kro-method pro-only' not in js, (
        "출처 표기를 담은 요소에 pro-only가 붙었다"
    )
