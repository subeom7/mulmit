"""종목 화면의 표는 원문으로 나가는 길을 가지고 있어야 한다.

공시를 옮겨 적는 화면에서 원문으로 갈 수 없는 것은 값이 틀린 것 다음으로 나쁘다.
읽는 사람이 "정말 그렇게 적혀 있나"를 확인할 방법이 사라지기 때문이다.

이 페이지를 국내·미국 한 벌로 다시 쓰면서 여섯 표가 전부 링크를 잃었다
(2026-08-24 운영자 지적). 데이터에는 계속 URL이 있었고 — `report_url`·`url`·
`filing_url`·`pdf_url` — 화면만 조용히 못 쓰고 있었다. 에러도 빈칸도 없이,
그냥 링크가 아니게 됐다. 그래서 사람이 눈으로 세는 대신 여기서 센다.
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
    block = source[start : start + 1400]
    assert "[cls, text, href]" in block, "칸의 세 번째 자리가 링크다"
    assert 'a.rel = "noopener noreferrer"' in block
    assert "if (href)" in block, "href가 없으면 링크로 만들지 않는다 — 빈 링크는 눌리기만 한다"


def test_every_filing_table_points_at_its_source_document() -> None:
    """여섯 표 각각이 payload의 URL 필드를 실제로 넘기는지.

    필드 이름이 표마다 다르다(`report_url`·`url`·`filing_url`·`pdf_url`).
    하나라도 빠지면 그 표만 조용히 링크를 잃는다.
    """
    source = _source()
    wanted = {
        "국내 임원·주요주주 소유보고": "r.report_url",
        "국내 주요사항보고": "x.report_name, x.url",
        "국민연금 5% 공시": "x.report_date, x.report_url",
        "미국 내부자 Form 3·4·5": "r.filing_url",
        "미국 8-K": '"—", x.url',
        "미 하원 PTR": "url: filing.pdf_url",
    }
    missing = [label for label, needle in wanted.items() if needle not in source]
    assert not missing, f"원문 링크가 빠진 표: {missing}"


def test_the_link_style_stays_quieter_than_the_value() -> None:
    """표 안의 링크가 값보다 시끄러우면 눈이 숫자를 못 읽는다."""
    source = _source()
    match = re.search(r"\.doc-link\s*\{([^}]*)\}", source)
    assert match, ".doc-link 스타일이 있어야 한다"
    body = match.group(1)
    assert "color: inherit" in body, "기본 상태에서는 값과 같은 색이다"
    assert "dotted" in body, "점선 밑줄만으로 링크임을 알린다"


def test_the_us_filing_link_comes_from_the_filing_not_the_transaction() -> None:
    """의원 거래 PDF는 거래가 아니라 **보고서**에 붙어 있다.

    거래 쪽에서 찾으면 언제나 undefined라 링크가 조용히 사라진다 — 라이브에서
    6행 전부 링크가 없었다(2026-08-24).
    """
    source = _source()
    start = source.index("// 의원 거래 언급 (PTR)")
    block = source[start : start + 1400]
    assert "url: filing.pdf_url" in block, "PDF는 filing에서 가져온다"
    assert "x.pdf_url" not in block, "거래 객체에는 pdf_url이 없다"
