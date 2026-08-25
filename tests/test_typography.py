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
# 인라인 <style>을 가진 페이지까지 본다. stock.html과 crypto-coin.html이 목록에
# 없어서 등폭 글꼴이 3,130개 상세 페이지에 그대로 남아 있었다(실측 2026-08-23:
# 종목 2,953 + 코인 177). 새 시트가 생기면 여기에 더한다.
SHEETS = ["monitor.css", "console.css", "tokens.css",
          "analytics.html", "stock.html", "crypto-coin.html"]

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


def test_every_dashboard_page_loads_the_design_system():
    """monitor.css를 부르는 페이지는 토큰·콘솔 시트도 그 뒤에 불러야 한다.

    앞선 테스트는 **인라인 `<style>`이 있는** 페이지만 봤다. `bio.html`은 인라인
    스타일이 없어서 목록에 걸리지 않았고, 그래서 `/bio`는 리디자인을 통째로
    놓친 채 남아 있었다 — 글꼴도, 패널 여백도, 배지도.

    법적 고지 3종(privacy·terms·disclaimer)은 `legal.css`로 따로 디자인한
    산문 페이지라 여기 해당하지 않는다.
    """
    for page in sorted(STATIC.glob("*.html")):
        source = page.read_text(encoding="utf-8")
        if "monitor.css" not in source:
            continue
        for sheet in ("tokens.css", "console.css"):
            assert sheet in source, f"{page.name}이 {sheet}를 부르지 않는다"
            assert source.index("monitor.css") < source.index(sheet), (
                f"{page.name}: {sheet}가 monitor.css보다 앞에 있어 토큰이 덮이지 않는다"
            )


def test_every_page_that_ships_its_own_styles_loads_the_design_system():
    """인라인 <style>을 가진 페이지도 토큰과 콘솔 시트를 불러야 한다.

    `/stock/{코드}`와 `/crypto/{심볼}`은 제 스타일만 들고 있어서 리디자인을
    통째로 놓쳤다. 사이트맵 기준 3,130개 — 종목 2,953 + 코인 177로, URL 수로는
    사이트의 대부분이고 검색 유입이 닿는 면 전체다(실측 2026-08-23).

    시트는 인라인 <style> **뒤에** 와야 한다. 앞에 두면 같은 특이도에서 지고,
    `/analytics`에서 실제로 그렇게 토큰이 먹히지 않았다.
    """
    for name in ("analytics.html", "stock.html", "crypto-coin.html"):
        source = (STATIC / name).read_text(encoding="utf-8")
        assert "<style>" in source, f"{name}에 인라인 스타일이 없다 — 목록을 손보라"
        for sheet in ("tokens.css", "console.css"):
            assert sheet in source, f"{name}이 {sheet}를 부르지 않는다"
            assert source.index("</style>") < source.index(sheet), (
                f"{name}: {sheet}가 인라인 <style>보다 앞에 있어 특이도에서 진다"
            )


def test_the_lookup_panel_insets_its_contents():
    """패널은 스스로 안쪽 여백을 주지 않는다 — 표가 자기 padding을 갖기 때문이다.

    그래서 패널 안에 표가 아닌 것을 넣으면 테두리에 그대로 붙는다. `/analytics`의
    종목 찾기가 그랬다(2026-08-24 운영자 지적). 실측하니 입력창·설명문·칩의 좌·상·하
    여백이 전부 1px, 즉 테두리 두께뿐이었다.
    """
    source = (STATIC / "analytics.html").read_text(encoding="utf-8")
    match = re.search(r"\.lookup\s*\{([^}]*)\}", source)
    assert match, ".lookup 규칙이 있어야 한다"
    assert "padding" in match.group(1), (
        "패널 안의 내용은 스스로 여백을 가져야 한다 — 안 그러면 테두리에 1px까지 붙는다"
    )


def test_the_lookup_panel_respects_the_label_floor():
    """tokens.css: `--fs-xs: 12 — 라벨 하한선. 이보다 작게 쓰지 않는다`."""
    source = (STATIC / "analytics.html").read_text(encoding="utf-8")
    style = source[source.index("<style>") : source.index("</style>")]
    tiny = re.findall(r"font:[^;]*?\b(\d+)px", style) + re.findall(r"font-size:\s*(\d+)px", style)
    assert not [size for size in tiny if int(size) < 12], (
        f"12px보다 작은 글자가 있다: {tiny} — tokens.css의 하한선을 지킬 것"
    )


# 하한선을 일부러 비켜 가는 자리. 늘리려면 tokens.css에도 이유를 적을 것.
ALLOWED_BELOW_FLOOR = {
    # 브랜드 로크업의 부제. tokens.css가 11px로 못박아 둔 유일한 예외다 —
    # 데이터가 아니라 장식이라, 읽히지 않아도 잃는 정보가 없다.
    ".brand small",
}


def _floor_selectors() -> set[str]:
    """tokens.css가 12px 이상으로 끌어올려 둔 셀렉터들."""
    covered = set(ALLOWED_BELOW_FLOOR)
    for selector, body in _rules((STATIC / "tokens.css").read_text(encoding="utf-8")):
        if re.search(r"font-size:\s*var\(--fs-(xs|sm)\)", body):
            covered.update(part.strip() for part in selector.split(","))
    return covered


def test_nothing_renders_below_the_label_floor() -> None:
    """12px 하한선은 **tokens.css에 적힌 것만** 지켜진다.

    각 시트는 여전히 9~11.5px을 선언하고, tokens.css가 나중에 실려서 그걸
    덮는 구조다. 그래서 규칙을 새로 쓰면서 이 목록에 넣는 걸 잊으면 아무도
    안 잡는다 — 실제로 그렇게 샌 것이 `.segmented button`(9px)이었다. 헤더 안의
    토글만 12px로 올리는 예외가 따로 있어서, 헤더 밖에 선 토글 하나만 9px로
    낱말을 찍고 있었고 운영자가 화면에서 그걸 짚었다.

    2026-08-25에 브라우저로 모든 페이지를 훑어 남은 72개를 목록에 넣었다.
    가장 작았던 건 `/bio`의 `.bio-chip small` 9.17px 184곳 — 규칙이 아예 없어
    브라우저 기본값(부모의 0.83배)에 앉아 있었다.

    이 테스트는 하한선을 **선언 시점에** 강제한다. 12px 미만을 쓰려면 같은
    셀렉터를 tokens.css의 바닥 목록에도 넣어야 한다.
    """
    leaking = []
    covered = _floor_selectors()
    for name in SHEETS:
        if name == "tokens.css":
            continue
        for selector, body in _rules((STATIC / name).read_text(encoding="utf-8")):
            sizes = [float(px) for px in re.findall(r"font:[^;]*?\b(\d+(?:\.\d+)?)px", body)]
            sizes += [float(px) for px in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", body)]
            if not [size for size in sizes if size < 12]:
                continue
            leaking += [
                f"{name}: {part}" for part in (p.strip() for p in selector.split(","))
                if part not in covered
            ]
    assert not leaking, (
        "12px보다 작은 글자가 하한선 밖에 있다. tokens.css의 바닥 목록에 같은 "
        f"셀렉터를 넣거나 크기를 var(--fs-xs)로 올리라: {leaking}"
    )


def test_the_floor_audit_can_actually_see_a_shorthand_declaration() -> None:
    r"""감사 정규식이 자기 대상을 못 보면, 통과는 아무것도 뜻하지 않는다.

    실제로 그랬다. 위 테스트를 처음 쓸 때 `\b`가 파일에 **리터럴 백스페이스
    문자(0x08)**로 들어가서 `font:` 단축형 검사가 죽어 있었다. `font-size: 9px`는
    잡고 `font: 650 9px/1`은 놓쳤는데, 정작 사이트에서 작은 글자는 거의 다
    단축형으로 쓰여 있다 — 운영자가 짚은 `.segmented button`도 단축형이었다.

    같은 실수가 전에도 한 번 있었다(질의 매개변수 감사). 그래서 감사에는
    감사를 붙인다.
    """
    samples = {
        "font-size: 9px;": 9.0,
        "font: 650 9px/1 var(--num);": 9.0,
        "font: 700 8.5px/1.2 var(--num);": 8.5,
        "font: 11.5px/1.4 var(--num);": 11.5,
    }
    for body, expected in samples.items():
        sizes = [float(px) for px in re.findall(r"font:[^;]*?\b(\d+(?:\.\d+)?)px", body)]
        sizes += [float(px) for px in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", body)]
        assert expected in sizes, f"감사가 이 선언을 못 본다: {body!r} → {sizes}"
