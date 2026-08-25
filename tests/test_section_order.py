"""섹션 순서는 화면의 뜻이다 — 옮긴 자리가 그대로 남는지 본다.

`/us`와 홈 모두 경제 캘린더를 "미국 대형주, 장 밖에서는" 뒤로 옮겼다(운영자
요청). 지수 카드를 본 다음 "그래서 다음 발표가 언제인데"로 이어지는 순서다.
히트맵이나 피드보다 뒤에 있으면 그 흐름이 끊긴다.

`/us`에 있던 접힌 서랍 "미국 기술주, 장 밖에서는"은 지웠다. 같은 XYZ100을
같은 퍼프 가격으로 보여 주면서 기준선만 달랐다(금요일 마감 vs 마지막 정규장
마감) — 한 화면에서 두 숫자가 다르면 어느 쪽이 맞는지 독자가 알 수 없다.

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


def test_the_us_page_does_not_repeat_what_the_home_page_shows() -> None:
    """같은 섹션을 두 페이지에 두면 어느 쪽이 진짜인지 읽는 사람이 정해야 한다.

    2026-08-25 운영자 지적. 히트맵과 경제 캘린더가 홈과 `/us`에 **같은 id·같은
    렌더러**로 두 벌 있었다. 특히 경제 캘린더는 한 달치 20건 중 한국 일정이
    섞여 있어서(실측: 미국 17 · 한국 3) 미국 탭에 두면 금통위 일정이 미국
    페이지에 서게 된다.

    둘 다 홈에 남긴다 — 홈은 세 시장을 다 다루는 자리이고, 히트맵은 들어오자마자
    눈에 들어오는 유일한 요소다.
    """
    ids = _section_ids("us.html")
    assert "econ-calendar" not in ids, "경제 캘린더는 홈에만 둔다"
    assert "constituent-heatmap" not in ids, "히트맵은 홈에만 둔다"

    home = _section_ids("landing.html")
    assert "econ-calendar" in home and "constituent-heatmap" in home, (
        "빼기만 하고 남기지 않으면 기능이 사라진다"
    )


def test_the_jump_nav_takes_its_order_from_the_page() -> None:
    source = (STATIC / "monitor.js").read_text(encoding="utf-8")
    start = source.index("const nav = $(\"#jump-nav\")")
    block = source[start : source.index("function renderSummary()", start)]
    assert "compareDocumentPosition" in block, (
        "점프 내비 순서를 문서에서 읽지 않으면, 섹션을 옮길 때마다 목록과 화면이 "
        "조용히 갈라진다 — 손으로 적은 순서로 되돌리지 말 것"
    )


def test_the_calendar_follows_the_overnight_cards_on_the_home_page() -> None:
    ids = _section_ids("landing.html")
    for wanted in ("us-overnight", "econ-calendar", "signal-feed"):
        assert wanted in ids, f"{wanted} 섹션이 홈에서 사라졌다"
    assert ids.index("us-overnight") < ids.index("econ-calendar") < ids.index("signal-feed"), (
        "홈도 /us와 같은 순서다 — 야간 카드 → 경제 캘린더 → 신호 피드"
    )


def test_the_us_page_carries_one_after_hours_block_not_two() -> None:
    """접힌 서랍이 새 섹션과 같은 값을 다른 기준선으로 보여 줬다.

    `weekend-details`는 XYZ100 하나를 **금요일 마감** 기준으로, `us-overnight`은
    같은 XYZ100을 **마지막 정규장 마감** 기준으로 그렸다. 한 화면에 두 숫자가
    서면 독자는 어느 쪽이 맞는지 알 수 없다. 서랍을 지웠으니 돌아오지 않게 한다.
    """
    html = (STATIC / "us.html").read_text(encoding="utf-8")
    assert 'id="us-overnight"' in html
    assert 'id="weekend-details"' not in html, (
        "장 밖 블록은 /us에 하나뿐이다 — 되살리려면 기준선을 먼저 합칠 것"
    )
    monitor = (STATIC / "monitor.js").read_text(encoding="utf-8")
    assert 'weekend: ["kr"],' in monitor, (
        "/us가 더는 주말 신호를 그리지 않으므로 그 페이지에서 받아 올 이유도 없다"
    )
