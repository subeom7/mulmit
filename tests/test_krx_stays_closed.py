"""KRX Open API는 기다릴 승인이 없다.

2026-08-24 한국거래소 데이터사업부 회신(운영자 문의에 대한 답):

    "KRX: … 비상업적 목적을 위한 데이터 공개 및 판매로서, 상업적 목적을 위한
     라이선스 계약 등은 존재하지 않습니다"

    "원천 데이터를 제3자에게 재배포하는 것은 불가합니다. 이는 API 상의 수치
     데이터를 웹사이트에 그대로 표출하는 것도 포함합니다"

지금까지 이 게이트는 "승인이 오면 연다"는 대기 상태였다. 이제 아니다 —
KRX에는 열어 줄 상업 계약이 존재하지 않고, 상업 경로는 코스콤이라는 다른
회사다. 키를 구해 오는 것으로는 아무것도 바뀌지 않는다.

이 테스트는 코드가 아니라 **기억**을 지킨다. 몇 달 뒤 누군가 "키 있으니 켜자"고
할 때, 그 사람이 먼저 만나는 것이 이 문장이어야 한다.
"""

from __future__ import annotations

from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parents[1]


def test_the_gate_defaults_to_off() -> None:
    assert config.KRX_ENABLED is False, (
        "KRX는 기다릴 승인이 없다 — 발행기관이 상업 라이선스가 없다고 회신했다"
    )


def test_the_reason_is_written_where_someone_would_flip_the_switch() -> None:
    """이유가 등록부에만 있으면, 게이트를 여는 사람은 그것을 안 읽는다."""
    source = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    start = source.index("KRX_ENABLED")
    comment = source[max(0, start - 900) : start]
    assert "KOSCOM" in comment, "상업 경로가 코스콤이라는 사실이 여기 있어야 한다"
    assert "존재하지 않습니다" in comment, "회신 원문이 여기 있어야 한다"


def test_the_register_keeps_the_publishers_own_words() -> None:
    """해석이 아니라 회신이라는 것이 기록의 등급을 정한다."""
    register = (ROOT / "docs" / "DATA_SOURCE_REGISTER.md").read_text(encoding="utf-8")
    assert "6.2b" in register
    assert "웹사이트에 그대로 표출하는 것도 포함합니다" in register, (
        "우리가 가정하던 해석을 발행기관이 문장으로 확인해 준 부분이다"
    )
    assert "코스콤" in register and "data.koscom.co.kr" in register
