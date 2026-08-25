"""이력 차트를 훑으면 게이지가 그날 자리로 간다 (2026-08-25).

게이지가 "조금 더 동적"이어야 한다는 요청에서 나왔다. 값이 하루 한 번밖에
안 바뀌므로 가짜 움직임을 붙이는 대신, **이미 갖고 있는 이력**을 만질 수 있게
했다 — 심리 지수 82개, 공포·탐욕 91개 관측치는 전부 실제 값이다.

여기서 지키는 것은 세 가지다: 남의 차트를 건드리지 않을 것, 훑는 값이 오늘
값처럼 읽히지 않을 것, 그리고 스크롤을 뺏지 않을 것.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
JS = (STATIC / "monitor.js").read_text(encoding="utf-8")
CSS = (STATIC / "monitor.css").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = JS.index(f"function {name}(")
    return JS[start : JS.index("\nfunction ", start + 1)]


def test_only_the_two_gauge_charts_are_scrubbable() -> None:
    """`lineChart`는 지표 카드와 비교 차트에서도 쓰인다 — 그쪽은 훑을 대상이 아니다.

    그래서 훑기는 **선택 인자**로만 붙는다. 인자를 안 주면 층도, 이벤트도
    만들어지지 않아 기존 호출부는 한 줄도 달라지지 않는다.
    """
    assert "function lineChart(series, color = null, normalize = false, onScrub = null)" in JS, (
        "훑기가 선택 인자가 아니게 됐다 — 다른 차트까지 바뀐다"
    )
    assert "if (onScrub) attachScrub(" in JS, "인자를 줬을 때만 붙어야 한다"
    # 실제로 넘기는 곳은 두 게이지뿐이다.
    assert JS.count("scrubGauge(body, point)") == 2, (
        "훑기를 넘기는 차트가 둘이 아니다 — 심리 지수와 공포·탐욕만이어야 한다"
    )


def test_a_past_reading_never_looks_like_todays() -> None:
    """마커만 옮기면 옆의 큰 숫자는 그대로 오늘 값이다.

    둘이 서로 다른 날을 가리키면서 같은 것처럼 보인다 — 이 사이트에서 제일
    하면 안 되는 종류의 화면이다. 큰 숫자를 흐리고, 훑는 날짜와 값을 따로 적어
    "이건 지금 값이 아니다"를 먼저 말한다.
    """
    body = _function("scrubGauge")
    assert 'classList.add("scrubbing")' in body and 'classList.remove("scrubbing")' in body
    assert "dateText(point.date)" in body, "훑는 값에 날짜가 안 붙으면 언제 값인지 알 수 없다"
    dim = re.search(r"\.stress-score\.scrubbing[^{]*\{([^}]*)\}", CSS)
    assert dim and "opacity" in dim.group(1), "훑는 동안 오늘 값이 그대로 또렷하다"


def test_leaving_the_chart_puts_the_gauge_back() -> None:
    """훑다 벗어나면 오늘 자리로 돌아와야 한다. 안 돌아오면 값이 틀린 채 남는다."""
    body = _function("scrubGauge")
    assert "track.dataset.gaugeAt" in body, "돌아갈 자리를 어디서도 읽지 않는다"
    attach = _function("attachScrub")
    for event in ("pointerleave", "pointercancel"):
        assert event in attach, f"{event}에서 정리하지 않는다"
    assert "onScrub(null)" in attach, "벗어날 때 null을 돌려주지 않는다"


def test_scrubbing_does_not_steal_touch_scrolling() -> None:
    """터치까지 받으면 세로 스크롤을 가로챈다.

    이 기능이 없어도 같은 숫자가 바로 아래 표에 다 있다. 스크롤을 뺏을 만한
    값어치는 아니다.
    """
    assert 'event.pointerType === "touch"' in _function("attachScrub"), (
        "터치를 걸러내지 않는다 — 모바일에서 차트 위 스크롤이 막힌다"
    )


def test_the_readout_reserves_its_space() -> None:
    """훑을 때 생겼다 사라지면 그때마다 아래 차트와 표가 한 줄씩 튄다."""
    assert JS.count("if (chart) scrubGauge(body, null);") == 2, (
        "읽기 줄을 렌더 시점에 만들지 않는다 — 첫 훑기에서 화면이 밀린다"
    )
    rule = re.search(r"\.gauge-readout\s*\{([^}]*)\}", CSS)
    assert rule and "min-height" in rule.group(1), "비어 있을 때 자리를 잡지 않는다"
