"""섹션 순서는 화면의 뜻이다 — 옮긴 자리가 그대로 남는지 본다.

`/us`에서 경제 캘린더는 "미국 대형주, 장 밖에서는" 바로 뒤로 옮겼다(운영자
요청). 지수 카드를 본 다음 "그래서 다음 발표가 언제인데"로 이어지는 순서다.
히트맵보다 뒤에 있으면 그 흐름이 끊긴다.

그리고 점프 내비게이션. `monitor.js`의 목록은 손으로 적은 순서라, HTML에서
섹션을 옮기면 목록과 화면이 갈라진다. 갈라진 쪽이 화면이라 콘솔에 아무것도
안 찍히고, 링크를 눌러야 알아챈다. 그래서 순서를 목록에서 정하지 않고 문서
위치에서 읽도록 바꿨다 — 그 장치가 남아 있는지 확인한다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def _section_ids(page: str) -> list[str]:
    html = (STATIC / page).read_text(encoding="utf-8")
    return re.findall(r'<section class="console-section" id="([^"]+)"', html)


def test_the_calendar_follows_the_overnight_cards_on_the_us_page() -> None:
    ids = _section_ids("us.html")
    for wanted in ("us-overnight", "econ-calendar", "constituent-heatmap"):
        assert wanted in ids, f"{wanted} 섹션이 /us에서 사라졌다"
    assert ids.index("us-overnight") < ids.index("econ-calendar"), (
        "경제 캘린더는 야간 카드 뒤에 온다 — 카드를 본 다음 다음 발표를 묻는 순서다"
    )
    assert ids.index("econ-calendar") < ids.index("constituent-heatmap"), (
        "히트맵보다 앞이다. 뒤로 밀면 옮기기 전 자리로 돌아간 것이다"
    )


def test_the_jump_nav_takes_its_order_from_the_page() -> None:
    source = (STATIC / "monitor.js").read_text(encoding="utf-8")
    start = source.index("const nav = $(\"#jump-nav\")")
    block = source[start : source.index("function renderSummary()", start)]
    assert "compareDocumentPosition" in block, (
        "점프 내비 순서를 문서에서 읽지 않으면, 섹션을 옮길 때마다 목록과 화면이 "
        "조용히 갈라진다 — 손으로 적은 순서로 되돌리지 말 것"
    )
