"""글꼴 규칙 두 가지.

화면 곳곳에서 느껴지던 "폰트 부조화"의 정체는 하나였다 — **한글이 등폭 스택에
들어가 있었다.** "저유동성 가능", "확정 종가 코스피 6,852.58", "마지막 갱신
2026년 8월 23일" 같은 줄이 전부 그랬다. 등폭 스택에 없는 한글은 대체 글꼴로
빠지므로, 한 줄 안에 서로 다른 두 글꼴이 선다. 눈에는 "뭔가 어긋났다"로만
보이고 원인은 안 보인다.

그래서 수치·라벨 면을 `--num`(Pretendard)으로 옮기고, `--mono`는 글이 아닌
식별자에만 남겼다. 이 파일은 그 결정이 조용히 되돌아가지 않게 지킨다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SHEETS = ["monitor.css", "console.css", "tokens.css", "index.html"]

# 등폭을 써도 되는 곳: 글이 아니라 식별자인 것들.
IDENTIFIER_SELECTORS = {".kro-sym"}


def _rules(source: str) -> list[tuple[str, str]]:
    """(셀렉터, 선언부) 목록. 중첩 없는 평범한 규칙만 다루면 충분하다."""
    # 주석을 먼저 걷어낸다 — 안 그러면 규칙 앞의 설명이 셀렉터에 딸려 온다.
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    found = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", source):
        selector = " ".join(match.group(1).split())
        if selector.startswith("@") or not selector:
            continue
        found.append((selector, match.group(2)))
    return found


def test_the_monospace_face_is_only_for_identifiers():
    """`--mono`는 티커 같은 식별자에만. 한글이 들어갈 자리에 쓰면 글꼴이 갈린다."""
    offenders = []
    for name in SHEETS:
        for selector, body in _rules((STATIC / name).read_text(encoding="utf-8")):
            if "var(--mono)" not in body:
                continue
            parts = {piece.strip() for piece in selector.split(",")}
            if not parts <= IDENTIFIER_SELECTORS:
                offenders.append(f"{name}: {selector}")
    assert not offenders, (
        "등폭 글꼴을 글에 쓰고 있다 — 한글이 대체 글꼴로 빠진다. "
        f"수치·라벨이면 var(--num)을 쓰라: {offenders}"
    )


def test_every_font_shorthand_on_the_number_face_reenables_tabular_figures():
    """`font:` 단축 속성은 `font-variant-numeric`을 normal로 되돌린다(CSS 명세).

    그래서 body에 켜 둔 자리폭 숫자가 --num을 쓰는 자리마다 조용히 꺼졌다.
    실측으로 큰 가격이 `font-variant-numeric: normal`이었다 — 값이 바뀔 때마다
    자릿수 폭이 흔들리고, 자리별로 굴러가는 계기판도 어긋난다.
    """
    missing = []
    for name in SHEETS:
        for selector, body in _rules((STATIC / name).read_text(encoding="utf-8")):
            if not re.search(r"font:\s*[^;]*var\(--num\)", body):
                continue
            if "font-variant-numeric" not in body:
                missing.append(f"{name}: {selector}")
    assert not missing, (
        "font: 단축 속성이 자리폭 숫자를 껐다. 같은 블록에 "
        f"`font-variant-numeric: tabular-nums`를 함께 적으라: {missing}"
    )


def test_the_number_face_is_not_actually_monospace():
    """--num이 다시 등폭을 가리키면 이 작업이 통째로 되돌아간 것이다."""
    tokens = (STATIC / "tokens.css").read_text(encoding="utf-8")
    declaration = re.search(r"--num:\s*([^;]+);", tokens)
    assert declaration, "--num 정의를 찾지 못했다"
    value = declaration.group(1)
    assert "Pretendard" in value, f"--num이 본문 글꼴이 아니다: {value}"
    assert "monospace" not in value, f"--num이 등폭으로 되돌아갔다: {value}"
