"""화면이 보내는 쿼리 인자를 서버가 실제로 받는지.

FastAPI는 선언하지 않은 쿼리 인자를 **조용히 무시한다**. 요청은 200으로
성공하고, 응답도 형태가 멀쩡하다. 다만 좁혀지지 않았을 뿐이다.

2026-08-24에 그래서 애플 종목 화면에 보잉의 8-K가 실려 있었다. 화면은
`/api/us/events?ticker=AAPL`을 부르고 있었는데 라우트에 `ticker`가 없었고,
커버리지 전체의 최근 목록이 그 종목의 공시인 것처럼 표에 들어갔다. 에러도
빈 표도 없었고, 원문 링크가 빠져 있던 동안에는 남의 것인지 확인할 방법조차
없었다.

사람이 눈으로 맞춰 보는 방법으로는 다시 놓친다. 그래서 OpenAPI 스펙과 화면의
호출을 여기서 기계적으로 맞춘다.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

# 서버가 안 받는 것을 알면서 보내는 자리. 왜 괜찮은지 여기 적어야 통과한다.
ALLOWED_UNKNOWN: dict[tuple[str, str], str] = {}


def _declared() -> dict[str, set[str]]:
    """경로별로 라우트가 선언한 쿼리 인자. 경로 파라미터 자리는 {x}로 눕힌다."""
    spec = TestClient(app).get("/openapi.json").json()
    out: dict[str, set[str]] = {}
    for path, operations in spec.get("paths", {}).items():
        flat = re.sub(r"\{[^}]+\}", "{x}", path)
        for method, operation in operations.items():
            if method not in ("get", "post"):
                continue
            out.setdefault(flat, set()).update(
                parameter["name"]
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "query"
            )
    return out


def _calls() -> list[tuple[str, str, set[str]]]:
    """화면이 부르는 (파일, 경로, 인자 이름들).

    `${...}` 안에는 `encodeURIComponent(...)`처럼 괄호가 들어간다. 그것을 먼저
    지우지 않으면 쿼리 문자열이 첫 괄호에서 잘려서, 뒤에 붙은 인자를 통째로
    놓친다 — 이 감사를 처음 짤 때 실제로 그랬다.
    """
    found: list[tuple[str, str, set[str]]] = []
    for file in sorted([*STATIC.glob("*.html"), *STATIC.glob("*.js")]):
        text = file.read_text(encoding="utf-8")
        for quoted in re.findall(r'["`]([^"`\n]*?/api/[^"`\n]*)["`]', text):
            # 템플릿 자리를 먼저 지운다(괄호가 들어 있다).
            cleaned = re.sub(r"\$\{[^}]*\}", "{x}", quoted)
            if "?" not in cleaned:
                continue
            path, _, query = cleaned.partition("?")
            path = path[path.index("/api") :]
            names = set(re.findall(r"(?:^|&)([A-Za-z_][A-Za-z0-9_]*)=", query))
            if names:
                found.append((file.name, path, names))
    return found


def test_every_query_argument_the_screen_sends_is_one_the_route_declares() -> None:
    declared = _declared()
    problems = []
    for file, path, names in _calls():
        known = declared.get(path)
        if known is None:
            problems.append(f"{file}: {path} — 그런 경로가 없다")
            continue
        for unknown in sorted(names - known):
            if ALLOWED_UNKNOWN.get((path, unknown)):
                continue
            problems.append(f"{file}: {path}?{unknown}= — 라우트가 이 인자를 모른다(조용히 무시된다)")
    assert not problems, (
        "화면이 서버가 모르는 인자를 보내고 있다. 요청은 200으로 성공하지만 좁혀지지 "
        f"않으므로, 화면은 남의 데이터를 이 종목의 것처럼 싣게 된다: {problems}"
    )


def test_the_audit_actually_reads_the_arguments_after_a_template_hole() -> None:
    """감사 자체가 눈뜬장님이면 위 테스트는 언제나 통과한다.

    `?a=${encodeURIComponent(x)}&b=1`에서 `b`를 못 읽으면 아무것도 못 잡는다.
    """
    calls = {(path, frozenset(names)) for _file, path, names in _calls()}
    multi = [names for path, names in calls if len(names) > 1]
    assert multi, "인자가 둘 이상인 호출을 하나도 못 읽었다면 추출이 잘못된 것이다"
