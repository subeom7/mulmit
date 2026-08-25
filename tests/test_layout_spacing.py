"""운영자가 화면에서 짚은 여백·정렬 여섯 가지 (2026-08-25).

전부 "값은 맞는데 눈이 걸리는" 종류다. 오류도, 콘솔 로그도 남지 않으므로
테스트가 없으면 다음 손질에서 조용히 되돌아간다. 그래서 고친 규칙마다
**무엇이 잘못 보였는지**를 여기 적어 둔다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _declarations(sheet: str, selector: str) -> str:
    """주석을 걷어낸 뒤 그 셀렉터의 선언부를 모아 돌려준다."""
    source = re.sub(r"/\*.*?\*/", " ", (STATIC / sheet).read_text(encoding="utf-8"), flags=re.S)
    found = [
        match.group(2)
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", source)
        if selector in {part.strip() for part in match.group(1).split(",")}
    ]
    assert found, f"{sheet}: `{selector}` 규칙을 찾지 못했다"
    return " ".join(found)


def test_the_rank_column_is_centred() -> None:
    """순위는 크기가 아니라 이름표다 — 오른쪽 정렬이면 1~9와 10이 어긋나 보인다.

    실측(mulmit.com/kr): `text-align: right`. 1부터 9까지는 오른쪽 끝이 같고
    10만 왼쪽으로 삐져나왔고, 순위 변동 배지가 붙는 줄은 더 밀렸다.
    """
    for selector in (".accessible-table th.ksi-rank", ".accessible-table td.ksi-rank"):
        assert "text-align: center" in _declarations("console.css", selector), (
            f"{selector}가 가운데 정렬이 아니다"
        )
    # th에도 같은 이름이 붙어 있어야 규칙 하나로 머리와 몸을 함께 덮는다.
    monitor = (STATIC / "monitor.js").read_text(encoding="utf-8")
    assert 'class="num ksi-rank"' in monitor, "순위 th에서 ksi-rank가 빠졌다 — 머리만 딴 정렬이 된다"


def test_the_segmented_toggle_respects_the_label_floor() -> None:
    """`.segmented button`은 9px로 짜여 있었다.

    헤더 **안**에 있는 토글만 12px로 올리는 예외가 있었고, 헤더 밖에 선
    `#ksi-sort`("평소 대비" / "관심도 수준")는 9px 그대로 낱말을 찍었다.
    tokens.css의 하한선은 `--fs-xs: 12`다.
    """
    body = _declarations("monitor.css", ".segmented button")
    sizes = [float(px) for px in re.findall(r"font:[^;]*?\b(\d+(?:\.\d+)?)px", body)]
    sizes += [float(px) for px in re.findall(r"font-size:\s*(\d+(?:\.\d+)?)px", body)]
    assert not [size for size in sizes if size < 12], f"12px 아래로 돌아갔다: {sizes}"
    assert "var(--fs-xs)" in body or "var(--fs-xs)" in _declarations("tokens.css", ".segmented button")


def test_the_summary_strip_is_not_glued_to_the_cards_below() -> None:
    """`.crypto-strip`의 아래 여백이 0이라 요약 줄이 카드 격자에 붙어 있었다.

    실측 간격 0px — /crypto의 김치프리미엄과 HL 전체 시장 보드, /bio의 여섯 곳.
    이 줄은 섹션 전체의 요약이라 어느 카드에도 속하지 않는다.
    """
    body = _declarations("monitor.css", ".crypto-strip")
    margin = re.search(r"margin:\s*([^;]+);", body)
    assert margin, ".crypto-strip에 margin 선언이 없다"
    parts = margin.group(1).split()
    bottom = parts[2] if len(parts) >= 3 else parts[0]
    assert bottom not in {"0", "0px"}, f"아래 여백이 다시 0이 됐다: {margin.group(1)}"


def test_the_big_number_does_not_touch_its_detail_lines() -> None:
    """가스 카드: 22px 숫자와 12px 세부 줄 사이 간격이 0px이었다.

    같은 카드의 h3에는 8px가 있는데 여기만 없었고, `line-height: 1`이라
    글자 아래 여유조차 없었다.
    """
    assert "margin-top" in _declarations("monitor.css", ".cvol-card strong + small"), (
        "큰 숫자와 첫 세부 줄이 다시 붙었다"
    )


def test_the_stock_tables_start_on_the_heading_line() -> None:
    """표의 모든 칸에 좌우 9px가 있어서 첫 열이 h2보다 9px 안쪽에서 시작했다."""
    source = (STATIC / "stock.html").read_text(encoding="utf-8")
    style = source[source.index("<style>") : source.index("</style>")]
    match = re.search(
        r"\.stock-table th:first-child,\s*\.stock-table td:first-child\s*\{([^}]*)\}", style
    )
    assert match and "padding-left: 0" in match.group(1), (
        "첫 칸의 들여쓰기가 돌아왔다 — 표가 제목선에서 어긋나 보인다"
    )


def test_the_licence_note_is_not_a_button_in_the_link_row() -> None:
    """설명 문장이 버튼들과 같은 flex 줄의 항목으로 들어가 있었다.

    "낙폭·변동성 분석은 국내 종목만 …" 한 문장이 30px 높이 버튼 두 개 사이에
    끼었고, 폭이 좁아지면 글자 단위로 접혔다(실측: 폭 11.4px · 높이 671.6px).
    """
    source = (STATIC / "stock.html").read_text(encoding="utf-8")
    row = re.search(r'<div class="stock-links">(.*?)</div>', source, flags=re.S)
    assert row, ".stock-links 줄을 찾지 못했다"
    assert "no-risk-note" not in row.group(1), "문장이 다시 버튼 줄 안으로 들어갔다"
    assert 'id="no-risk-note"' in source, "문장 자체가 사라졌다 — 옮기랬지 지우랬나"
