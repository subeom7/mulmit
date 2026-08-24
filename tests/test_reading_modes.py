"""쉬움 / 전문가 모드가 실제로 다른 화면을 보여 주는가.

운영자 지적(2026-08-24): "전문가/쉬움 모드가 있는데 사실상 변별력이 거의 없고
같아." 재 보니 정확했다 — **전 사이트에 모드 의존 요소가 두 개**였다(landing 1,
us 1). 토글은 있는데 바뀌는 것이 없었다.

기능이 조용히 죽는 방식이 이렇다. 하나씩 옳은 이유로 사라진다 — 오늘도 내가
하나를 뺐다("검색량 순위 아님" 배지는 정렬된 표를 순위로 오해하는 초보자에게
**더** 필요한 정보라 `pro-only`가 거꾸로였다). 그 판단 하나하나는 맞는데,
합쳐 놓으면 토글이 아무것도 안 하게 된다.

그래서 여기서 센다. 숫자를 지키자는 게 아니라, **모드가 죽었는지 사람이
알아채기 전에 테스트가 알아채자**는 것이다.

무엇이 어느 쪽인가:

- **쉬움 전용**(`easy-only`) — 이 숫자가 무슨 뜻인지 그 자리에서 말하는 한 줄.
  용어 사전으로 보내면 대부분 안 간다.
- **전문가 전용**(`pro-only`) — 배수를 이해한 다음에 읽는 값(백분위·표본 수),
  산출 근거, 원자료 링크.

**섞으면 안 되는 것**: 근거·권리 문구(`section-copy`의 "장 마감 확정값입니다",
"자본시장법 5% 룰에 따른")는 어느 모드에서도 감추지 않는다. 고지는 모드가
아니다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PAGES = ("landing.html", "kr.html", "us.html", "crypto.html", "stock.html", "bio.html")

# 2026-08-24에 두 개였다. 이 아래로 내려가면 토글은 다시 장식이 된다.
MODE_FLOOR = 6


def _mode_marks(text: str) -> int:
    return len(re.findall(r"\b(?:pro-only|easy-only)\b", text))


def test_the_toggle_actually_changes_something() -> None:
    total = sum(_mode_marks((STATIC / page).read_text(encoding="utf-8")) for page in PAGES)
    total += _mode_marks((STATIC / "monitor.js").read_text(encoding="utf-8"))
    assert total >= MODE_FLOOR, (
        f"모드 의존 요소가 {total}개다. 토글이 있는데 바뀌는 것이 없으면 그건 기능이 "
        "아니라 장식이다 — 늘리든지, 토글을 지우든지 둘 중 하나여야 한다"
    )


def test_both_modes_are_represented() -> None:
    """한쪽만 있으면 토글이 한 방향으로만 의미가 있다."""
    text = "".join((STATIC / page).read_text(encoding="utf-8") for page in PAGES)
    text += (STATIC / "monitor.js").read_text(encoding="utf-8")
    assert "easy-only" in text, "쉬움 모드에만 보이는 설명이 있어야 한다"
    assert "pro-only" in text, "전문가 모드에만 보이는 세부가 있어야 한다"


def test_the_plain_language_line_is_easy_only() -> None:
    """도움말이 양쪽에 다 뜨면 전문가에게는 소음이다."""
    source = (STATIC / "monitor.js").read_text(encoding="utf-8")
    start = source.index("function renderKrSearchInterest()")
    block = source[start : source.index("function renderKrEtf()", start)]
    assert 'help.className = "easy-only ksi-help"' in block

    stock = (STATIC / "stock.html").read_text(encoding="utf-8")
    line = next(row for row in stock.splitlines() if "ksi-help" in row and "<p" in row)
    assert "easy-only" in line


def test_the_percentile_waits_for_pro_mode() -> None:
    """백분위는 배수를 이해한 다음에 읽는 값이다.

    두 숫자를 나란히 놓으면 초보자는 어느 쪽을 봐야 할지부터 헤맨다.
    """
    source = (STATIC / "monitor.js").read_text(encoding="utf-8")
    header = next(
        row for row in source.splitlines()
        if "ksi.colPercentile" in row and "<th" in row
    )
    assert "pro-only" in header

    stock = (STATIC / "stock.html").read_text(encoding="utf-8")
    line = next(row for row in stock.splitlines() if 'id="ksi-pct"' in row)
    assert "pro-only" in line


def test_basis_and_rights_copy_is_never_mode_dependent() -> None:
    """고지는 모드가 아니다.

    `section-copy`에는 설명과 **근거·권리 문구**가 섞여 있다("장 마감 확정값입니다",
    "자본시장법 5% 룰에 따른"). 전문가 모드에서 감추면 고지가 사라진다 — 그래서
    감추는 대신 **더하는** 쪽으로만 모드를 만든다.
    """
    for page in PAGES:
        for row in (STATIC / page).read_text(encoding="utf-8").splitlines():
            if "section-copy" in row:
                assert "pro-only" not in row and "easy-only" not in row, (
                    f"{page}: 근거 문구를 모드로 감추지 말 것 — {row.strip()[:80]}"
                )
