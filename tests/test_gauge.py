"""게이지 세 개(스트레스 · 시장 심리 · 공포탐욕)의 규칙 (2026-08-25).

이전 게이지는 6px 색 띠 **전체**를 켜 두고 3px 눈금 하나로 값을 가리켰다.
띠가 전부 밝으니 눈이 잡을 곳이 없고, 눈금은 너무 가늘어 어디에 있는지 찾아야
했다. 길이가 값을 말하게 하고(0부터 현재값까지만 켠다), 이력이 있는 지수는
어제 자리를 남긴다.

여기서 지키는 것은 **모양이 아니라 정직함**이다 — 없는 이력을 그리지 않고,
하루 한 번 바뀌는 값에 쉬지 않는 애니메이션을 붙이지 않으며, 애니메이션이
값의 정확성을 좌우하지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
CSS = (STATIC / "monitor.css").read_text(encoding="utf-8")
JS = (STATIC / "monitor.js").read_text(encoding="utf-8")


def _painter() -> str:
    """paintGauge 함수 본문."""
    start = JS.index("function paintGauge(")
    return JS[start : JS.index("\nfunction ", start + 1)]


def test_the_track_lights_only_up_to_the_value() -> None:
    """길이가 값을 말한다 — 범위 전체는 꺼 두고 현재값까지만 켠다."""
    lit = re.search(r"\.gauge-lit\s*\{([^}]*)\}", CSS)
    assert lit and "clip-path" in lit.group(1), (
        "채워지는 구간이 사라졌다 — 띠 전체가 다시 켜지면 눈금 하나로 값을 찾아야 한다"
    )
    assert "clipPath" in _painter(), "JS가 채움 길이를 갱신하지 않는다"


def test_the_value_does_not_depend_on_an_animation_frame() -> None:
    """rAF로 최종 위치를 미루면 백그라운드 탭에서 마커가 시작 자리에 멈춘다.

    실측(2026-08-25, 숨은 탭): 스트레스 마커가 0%, 심리 마커가 어제 값 62.3%에
    멈춰 있었다. 점수는 73.6과 64.3이었다. 애니메이션이 아니라 **표시되는 값이**
    틀렸다. 리플로우만으로 전환이 걸리므로 rAF는 필요 없다.
    """
    assert "requestAnimationFrame" not in _painter(), (
        "게이지 위치를 rAF에 맡겼다 — 숨은 탭에서 콜백이 돌지 않아 값이 틀리게 보인다"
    )
    assert "offsetWidth" in _painter(), "리플로우로 시작 자리를 확정하지 않으면 전환이 안 걸린다"


def test_the_gauge_never_invents_a_history_it_does_not_have() -> None:
    """유동성·스트레스 지수는 이력을 내려주지 않는다(components만 있다).

    어제 자리를 0이나 50에서 시작하면 "어제는 거기였다"는 뜻이 되어 버린다.
    그래서 이 게이지에는 previous를 넘기지 않고, 어제 자국도 그리지 않는다.
    """
    call = re.search(r'paintGauge\(\$\("#stress-marker"\)[^;]*;', JS)
    assert call, "스트레스 게이지 호출을 찾지 못했다"
    assert "previous" not in call.group(0), (
        "이력이 없는 지수에 어제 값을 넘기고 있다 — 없는 값은 만들지 않는다"
    )
    # 이력이 있는 둘은 반대로 반드시 넘긴다.
    for marker in ("#sentiment-marker", "#cfng-marker"):
        found = re.search(r'paintGauge\(\$\("' + marker + r'"\)[^;]*;', JS)
        assert found and "previous" in found.group(0), f"{marker}: 어제 자리를 그리지 않는다"


def test_motion_only_happens_when_the_value_actually_moves() -> None:
    """하루 한 번 갱신되는 지수에 무한 애니메이션을 붙이면 실시간처럼 읽힌다."""
    assert "infinite" not in CSS[CSS.index(".stress-scale {") : CSS.index(".stress-method")], (
        "게이지에 무한 반복 애니메이션이 붙었다 — 값이 계속 움직이는 것처럼 보인다"
    )
    assert ".stress-scale i.changed" in CSS, "값이 바뀔 때의 표시가 사라졌다"
    assert 'classList.add("changed")' in _painter()


def test_the_gauge_honours_reduced_motion() -> None:
    """움직임을 끈 사람에게는 움직이지 않는다. 값은 그대로 맞아야 한다."""
    blocks = re.findall(r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", CSS, flags=re.S)
    covered = " ".join(block for block in blocks if "gauge" in block or "stress-scale" in block)
    assert covered, "게이지가 prefers-reduced-motion 블록에 없다"
    for name in (".gauge-lit", ".gauge-trail"):
        assert name in covered, f"{name}의 전환이 꺼지지 않는다"
    assert "prefers-reduced-motion" in _painter(), "JS가 움직임 설정을 보지 않는다"
