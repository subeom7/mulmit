"""캐시 지시가 빠지지 않았는지.

`Cache-Control`이 없으면 브라우저는 **휴리스틱 캐싱**을 쓴다 — 보통
(지금 − Last-Modified)의 10%. 배포 직후에는 창이 짧아서 눈에 띄지 않다가,
열흘 손대지 않은 파일에서는 하루치가 된다. 그러면 재방문자가 하루 지난 HTML을
받고, 그 HTML이 가리키는 `?v=`도 옛 버전이라 에셋까지 통째로 옛 판이 된다.

깨지지는 않는다 — HTML과 에셋이 같은 판이라 정합은 맞다. 그래서 더 잡기 어렵다.
증상은 "배포했는데 왜 안 바뀌지?" 하나뿐이다(실측 2026-08-23: 배포 1시간 뒤에 연
브라우저가 `v=20260823-22`를 그리고 있었고, 같은 순간 `fetch(cache:"reload")`는
새 HTML을 받았다).

그래서 "헤더가 있다"가 아니라 **어떤 값이어야 하는지**까지 못 박는다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

PAGES = ["/", "/kr", "/us", "/crypto", "/bio", "/analytics", "/privacy", "/terms", "/disclaimer"]
CRAWLER_FILES = ["/robots.txt", "/sitemap.xml", "/sitemap-pages.xml"]


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("path", PAGES)
def test_every_page_revalidates_instead_of_being_guessed_at(client, path):
    """페이지 HTML은 매번 물어본다. 안 그러면 수정이 사용자에게 늦게 도착한다."""
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-cache", (
        f"{path}에 캐시 지시가 없거나 다르다 — 브라우저가 알아서 추측한다"
    )


def test_no_cache_still_answers_304_so_it_costs_one_request(client):
    """`no-cache`는 캐시 금지가 아니라 '쓰기 전에 물어봐'다.

    ETag가 함께 나가지 않으면 매번 본문 전체가 다시 온다 — 그건 no-store다.
    """
    first = client.get("/")
    etag = first.headers.get("etag")
    assert etag, "ETag가 없으면 no-cache가 곧 매번 전체 재전송이 된다"
    again = client.get("/", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert not again.content


def test_a_versioned_asset_is_pinned_forever(client):
    """판이 바뀌면 `?v=`가 바뀌므로 같은 URL의 내용은 영원히 같다."""
    response = client.get("/static/monitor.js?v=20260823-24")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_an_unversioned_asset_is_not_pinned(client):
    """버전 없는 링크 하나가 사용자를 1년 묶어 두면 안 된다."""
    response = client.get("/static/monitor.js")
    assert response.status_code == 200
    assert "immutable" not in response.headers["cache-control"]
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_fonts_are_pinned_even_without_a_version():
    """서브셋 92개는 CSS 안에서 버전 없이 불린다. 이름이 곧 내용이라 안 바뀐다."""
    client = TestClient(app)
    response = client.get("/static/fonts/pretendard/PretendardVariable-dynamic-subset.css")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("path", CRAWLER_FILES)
def test_crawler_files_say_how_long_they_keep(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers.get("cache-control"), f"{path}도 추측에 맡기고 있다"


def test_a_route_that_chose_its_own_value_keeps_it(client):
    """서버 렌더 페이지는 짧은 공개 캐시를 일부러 걸어 둔 것이다 — 덮어쓰지 않는다."""
    assert client.get("/glossary").headers["cache-control"] == "public, max-age=3600"


def test_api_answers_are_not_touched(client):
    """API는 응답마다 제 수명을 정한다. 미들웨어가 끼어들면 안 된다."""
    response = client.get("/api/calendar")
    assert response.status_code == 200
    assert response.headers.get("cache-control") != "no-cache"
