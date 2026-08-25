"""히트맵이 페이지 스크롤을 가로채면 안 된다 (이슈 #247).

TradingView 히트맵은 `isZoomEnabled`라 iframe 위에서 휠을 확대에 쓴다. 그
iframe은 **교차 출처**라 우리가 그 안의 핸들러를 손댈 수 없고, 결과가 둘 다
나쁘다.

1. **가로채기** — 히트맵을 지나쳐 내려가려던 사람의 스크롤이 확대에 먹힌다.
2. **튀어나감** — 위젯이 그만 먹는 순간 페이지가 갑자기 뛴다. 이슈가 지적한 것이
   이쪽이다.

실측(2026-08-25, 라이브): 커서를 히트맵 위에 두고 휠 5번에 페이지가 **500px**
내려갔다.

`overscroll-behavior`로는 못 막는다 — 그건 스크롤 컨테이너의 연쇄를 막는
속성이고, 여기서 휠을 쥐고 있는 것은 다른 출처의 문서다. 그래서 **iframe에
이벤트가 닿기 전**에 막을 세운다: 클릭하기 전에는 위젯이 포인터 이벤트를 아예
받지 못한다.

DOM 동작 자체는 브라우저에서 확인했다(초기 잠금 → 클릭 시 해제 → 포인터가
떠나면 재잠금). 여기서는 **그 장치가 코드에서 사라지지 않는지**를 지킨다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
SCRIPT = (STATIC / "monitor.js").read_text(encoding="utf-8")
STYLE = (STATIC / "console.css").read_text(encoding="utf-8")


def test_the_widget_is_shielded_until_the_reader_asks():
    """막이 없으면 위젯이 곧바로 휠을 가져간다."""
    assert "tv-shield" in SCRIPT, "활성화 막을 만드는 코드가 없다"
    assert 'shield.className = "tv-shield"' in SCRIPT


def test_the_widget_cannot_take_pointer_events_before_activation():
    """이 규칙 하나가 실제로 휠을 막는다 — 없으면 막이 있어도 소용없다."""
    assert ".tv-panel .tradingview-host:not(.tv-active) .tradingview-widget-container" in STYLE
    block = STYLE[STYLE.index(".tv-panel .tradingview-host:not(.tv-active)"):]
    assert "pointer-events: none" in block[:200]


def test_the_shield_is_a_real_button():
    """마우스에만 있는 기능을 만들지 않는다 — 키보드로도 열려야 한다."""
    assert 'document.createElement("button")' in SCRIPT
    assert 'shield.type = "button"' in SCRIPT
    assert 'event.key === "Enter"' in SCRIPT


def test_leaving_the_area_locks_it_again():
    """열어 둔 채로 두면 다음에 지나가는 사람이 다시 가로채인다."""
    assert 'host.addEventListener("mouseleave"' in SCRIPT
    assert 'host.classList.remove("tv-active")' in SCRIPT


def test_the_host_can_position_the_shield():
    """`position: relative`가 없으면 막이 화면 전체를 덮는다."""
    assert ".tv-panel .tradingview-host { position: relative; }" in STYLE


@pytest.mark.parametrize("key", ["tv.activate", "tv.activateAria"])
def test_both_languages_explain_what_the_shield_does(key: str):
    assert SCRIPT.count(f'"{key}":') == 2, f"{key}가 ko/en 양쪽에 있지 않다"


def test_the_shield_says_what_happens_before_activation():
    """'클릭하세요'만으로는 왜 클릭해야 하는지 모른다. 열기 전에는 휠이 페이지
    스크롤에 쓰인다는 사실을 보조 설명이 말해야 한다."""
    assert "휠이 페이지 스크롤에 쓰입니다" in SCRIPT
    assert "the wheel scrolls the page" in SCRIPT


def test_the_heatmap_lives_on_the_home_page():
    """이슈 신고자가 본 화면이 여기다(#256으로 홈 전용이 됐다)."""
    landing = (STATIC / "landing.html").read_text(encoding="utf-8")
    assert 'id="constituent-heatmap"' in landing
    assert 'id="tradingview-host"' in landing
