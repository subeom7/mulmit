"""존재하는 페이지는 HEAD에 405를 주면 안 된다.

Starlette의 평범한 `Route`는 GET을 선언하면 HEAD를 함께 붙여 주지만
**FastAPI의 `APIRoute`는 그러지 않는다.** 그래서 이 앱의 모든 경로가 —
홈페이지와 `/favicon.ico`까지 — HEAD에 `{"detail":"Method Not Allowed"}`를
돌려주고 있었다(실측 2026-08-24, 운영 서버).

파비콘이 검색 결과에 안 뜨는 문제를 파다가 나왔다. 그 건의 원인은 아니었지만
(Googlebot은 GET을 쓴다) 링크 검사기·업타임 모니터·일부 크롤러는 본문을 받지
않으려고 HEAD를 쓴다. 있는 페이지에 "그런 메서드 없다"고 답하는 것은 그 자체로
틀린 동작이다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# 사람이 여는 페이지, 정적 파일, 게이트가 없는 API를 한 줄씩.
PATHS = ["/", "/kr", "/us", "/crypto", "/bio", "/analytics", "/news", "/glossary",
         "/favicon.ico", "/robots.txt", "/manifest.webmanifest", "/sw.js",
         "/api/health", "/api/status"]


@pytest.mark.parametrize("path", PATHS)
def test_head_is_not_rejected(path: str):
    assert client.head(path).status_code != 405, (
        f"{path}가 HEAD에 405를 돌려준다 — FastAPI 라우트는 HEAD를 자동으로 "
        "붙이지 않는다. `HeadAsGet` 미들웨어가 빠졌는지 보라."
    )


@pytest.mark.parametrize("path", PATHS)
def test_head_matches_get_status(path: str):
    """HEAD와 GET이 다른 답을 하면 모니터가 거짓 경보를 낸다."""
    assert client.head(path).status_code == client.get(path).status_code


@pytest.mark.parametrize("path", ["/", "/favicon.ico", "/api/health"])
def test_head_sends_no_body_but_keeps_the_length(path: str):
    """RFC 9110 §9.3.2 — 본문은 없고 헤더는 GET과 같아야 한다."""
    head = client.head(path)

    assert head.content == b"", "HEAD 응답에 본문이 실렸다"
    assert head.headers.get("content-length"), "Content-Length가 사라졌다"
    assert int(head.headers["content-length"]) > 0


def test_head_keeps_the_content_type_a_crawler_would_read():
    """파비콘을 HEAD로 확인하는 도구가 형식을 알아볼 수 있어야 한다."""
    head = client.head("/favicon.ico")

    assert head.status_code == 200
    assert "image" in head.headers.get("content-type", ""), head.headers.get("content-type")


def test_a_missing_page_still_says_not_found_rather_than_not_allowed():
    """HEAD를 GET으로 바꾼다고 없는 페이지가 생기지는 않는다."""
    assert client.head("/definitely-not-a-page").status_code == 404


def test_the_middleware_is_wired():
    from app.main import HeadAsGet

    names = [m.cls.__name__ for m in app.user_middleware]
    assert HeadAsGet.__name__ in names, names


@pytest.mark.parametrize("path", ["/", "/glossary", "/favicon.ico"])
def test_head_carries_the_same_cache_headers_as_get(path: str):
    """캐시 헤더를 붙이는 미들웨어는 HEAD 변환보다 **바깥**에 있어야 한다.

    안쪽에 있으면 HEAD 요청에 캐시 지시가 빠지고, 그 응답을 캐시하는 프록시가
    GET과 다른 판단을 하게 된다. 처음엔 "HeadAsGet이 가장 바깥"이라고 못 박았다가
    틀렸다 — 중요한 것은 순서 그 자체가 아니라 이 성질이다.
    """
    head, get = client.head(path), client.get(path)

    assert head.headers.get("cache-control") == get.headers.get("cache-control")
