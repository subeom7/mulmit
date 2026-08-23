"""`disabledCode()`가 걸러 내는 코드는 등록돼 있어야 한다 — 안 그러면 조용히 안 숨는다.

`disabledCode(key)`는 서버가 준 코드를 그대로 주지 않는다. `DISABLED_CODES`에
있는 것만 통과시키고 나머지는 `null`이다. 그래서 렌더러가

    if (disabledCode("x") === "some_disabled") { section.hidden = true; return; }

라고 써도, `some_disabled`가 등록부에 없으면 이 분기는 **영원히 거짓**이고
섹션은 숨는 대신 "불러올 수 없음 · 다시 시도"를 띄운다. 꺼 둔 lane이 고장 난
lane처럼 보이는 것이다 — 배포는 성공했고 테스트도 통과한 채로.

`news_videos_disabled`가 정확히 이렇게 라이브에 나갔다(2026-08-23).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[1] / "app" / "static" / "monitor.js").read_text(encoding="utf-8")


def _registered() -> set[str]:
    block = SCRIPT[SCRIPT.index("const DISABLED_CODES = {"):]
    block = block[: block.index("\n};")]
    return set(re.findall(r"^\s*([a-z0-9_]+)\s*:", block, re.M))


def _compared() -> set[str]:
    """`disabledCode(...)`나 `errorCode(...)`의 결과와 견주는 문자열 리터럴."""
    found: set[str] = set()
    for call in ("disabledCode", "errorCode"):
        found |= set(re.findall(rf'{call}\([^)]*\)\s*===\s*"([^"]+)"', SCRIPT))
        found |= set(re.findall(rf'"([^"]+)"\s*===\s*{call}\([^)]*\)', SCRIPT))
    return found


def test_the_registry_and_the_comparisons_were_both_found():
    """정규식이 헛돌면 아래 테스트가 통과가 아니라 무의미해진다."""
    assert len(_registered()) >= 15
    assert len(_compared()) >= 2


@pytest.mark.parametrize("code", sorted(_compared()))
def test_every_compared_code_is_registered(code: str):
    # errorCode()는 등록부를 거치지 않으므로 비교는 성립한다. 하지만 등록해 두면
    # 두 경로가 같은 뜻을 갖고, 나중에 disabledCode로 바꿔도 조용히 깨지지 않는다.
    assert code in _registered(), (
        f'"{code}"가 DISABLED_CODES에 없다. disabledCode()가 null을 돌려주므로 '
        "이 분기는 절대 참이 되지 않고, 꺼 둔 섹션이 고장 난 섹션처럼 보인다."
    )


def test_the_guard_would_have_caught_the_one_that_shipped():
    """가드가 실패할 수 없으면 가드가 아니다."""
    assert "news_videos_disabled" in _compared(), "렌더러가 이 코드를 더는 안 본다면 테스트를 고쳐라"
    assert "news_videos_disabled" in _registered()
    assert "definitely_not_a_real_code" not in _registered()
