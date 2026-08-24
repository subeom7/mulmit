"""종목 화면의 표는 원문으로 나가는 길을 가지고 있어야 한다.

공시를 옮겨 적는 화면에서 원문으로 갈 수 없는 것은 값이 틀린 것 다음으로 나쁘다.
읽는 사람이 "정말 그렇게 적혀 있나"를 확인할 방법이 사라지기 때문이다.

이 페이지를 국내·미국 한 벌로 다시 쓰면서 여섯 표가 전부 링크를 잃었다
(2026-08-24 운영자 지적). 데이터에는 계속 URL이 있었고 — `report_url`·`url`·
`filing_url`·`pdf_url` — 화면만 조용히 못 쓰고 있었다. 에러도 빈칸도 없이,
그냥 링크가 아니게 됐다.

되살릴 때 처음엔 보고일·의원 이름 같은 **값에 링크를 얹었다**. 운영자가 그것도
지적했고 옳았다 — 날짜는 눈으로 훑는 숫자인데 밑줄이 훑기를 방해하고, 어느 칸이
눌리는지가 표마다 달랐다(보고일·의원 이름·Item 텍스트). 지금은 **전용 열**이다.
"""

from __future__ import annotations

import re
from pathlib import Path

STOCK = Path(__file__).resolve().parents[1] / "app" / "static" / "stock.html"


def _source() -> str:
    return STOCK.read_text(encoding="utf-8")


def test_the_cell_helper_can_render_a_link() -> None:
    source = _source()
    start = source.index("const fill = (tableId, headers, rows)")
    block = source[start : start + 2000]
    assert 'a.rel = "noopener noreferrer"' in block
    assert "if (href)" in block, "href가 없으면 링크로 만들지 않는다 — 빈 링크는 눌리기만 한다"
    assert 'a.setAttribute("aria-label"' in block, (
        "같은 말이 세로로 반복되므로 스크린리더에는 어느 줄의 원문인지 알려야 한다"
    )


def test_the_link_lives_in_its_own_column_not_on_a_value() -> None:
    """값과 링크가 한 칸에 섞이면 둘 다 읽기 나빠진다.

    날짜에 밑줄이 그어지면 훑기가 막히고, 표마다 눌리는 칸이 달라지면 어디를
    눌러야 하는지 매번 찾아야 한다. 열을 따로 빼면 누를 자리가 언제나 같다.
    """
    source = _source()
    assert "const docCell = (url)" in source, "원문 칸을 만드는 자리가 있어야 한다"
    assert "const DOC_HEAD = (source)" in source, "출처 이름은 헤더에 한 번만 적는다"

    strays = re.findall(r'\["(?:num)?",\s*[^]]*?,\s*(?:r|x)\.[a-z_]*url[^]]*?\]', source)
    assert not strays, f"값 칸에 링크가 얹혀 있다: {strays}"


def test_every_filing_table_points_at_its_source_document() -> None:
    """여섯 표 각각이 payload의 URL 필드를 실제로 넘기는지.

    필드 이름이 표마다 다르다(`report_url`·`url`·`filing_url`·`pdf_url`).
    하나라도 빠지면 그 표만 조용히 링크를 잃는다.
    """
    source = _source()
    wanted = {
        "국내 임원·주요주주 소유보고": "docCell(r.report_url)",
        "국내 주요사항보고": "docCell(x.url)",
        "국민연금 5% 공시": "docCell(x.report_url)",
        "미국 내부자 Form 3·4·5": "docCell(r.filing_url)",
        "미 하원 PTR": "url: filing.pdf_url",
    }
    missing = [label for label, needle in wanted.items() if needle not in source]
    assert not missing, f"원문 링크가 빠진 표: {missing}"
    assert source.count("DOC_HEAD(") == 6, "여섯 표 모두 원문 열 헤더를 가져야 한다"


def test_the_source_name_is_written_once_in_the_header() -> None:
    """출처 이름을 열두 줄에 반복하면 그건 정보가 아니라 소음이다."""
    source = _source()
    assert 'DOC_HEAD("DART")' in source and 'DOC_HEAD("EDGAR")' in source
    assert '"열기"' in source, "칸은 같은 말만 하고, 어디로 가는지는 헤더가 말한다"


def test_a_row_without_a_document_says_so() -> None:
    """URL이 없는 행은 빈칸이 아니라 —다. 빈칸은 열이 깨진 것처럼 보인다."""
    assert 'url ? "열기" : "—"' in _source()


def test_the_link_style_stays_quieter_than_the_value() -> None:
    """표를 훑는 눈이 숫자에서 걸리지 않아야 한다."""
    source = _source()
    match = re.search(r"\.doc-link\s*\{([^}]*)\}", source)
    assert match, ".doc-link 스타일이 있어야 한다"
    body = match.group(1)
    assert "var(--faint)" in body, "기본 상태에서는 값보다 옅다"
    assert "text-decoration: none" in body, "밑줄로 값과 경쟁하지 않는다"
    assert ".doc-link:hover" in source, "올려다볼 때는 또렷해져야 누를 수 있다는 걸 알린다"


def test_the_us_filing_link_comes_from_the_filing_not_the_transaction() -> None:
    """의원 거래 PDF는 거래가 아니라 **보고서**에 붙어 있다.

    거래 쪽에서 찾으면 언제나 undefined라 링크가 조용히 사라진다 — 라이브에서
    6행 전부 링크가 없었다(2026-08-24).
    """
    source = _source()
    start = source.index("// 의원 거래 언급 (PTR)")
    block = source[start : start + 1600]
    assert "url: filing.pdf_url" in block, "PDF는 filing에서 가져온다"
    assert "x.pdf_url" not in block, "거래 객체에는 pdf_url이 없다"
