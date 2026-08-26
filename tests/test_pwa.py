"""PWA 설치 가능 조건을 못 박는다.

브라우저는 조건이 빠져도 아무 경고 없이 조용히 일반 사이트로 취급한다 —
매니페스트 링크가 한 페이지에서 빠지거나, 아이콘 경로가 죽거나, 워커가
루트 스코프를 잃어도 화면은 멀쩡하다. 그래서 회귀는 테스트로만 잡힌다.

서비스 워커에는 이 저장소가 이미 겪은 함정 두 가지를 고정한다:

- 워커 URL(/sw.js)에 `?v=` 를 붙이면 안 된다. 브라우저는 URL을 워커의
  정체성으로 쓰므로, 버전이 붙는 순간 갱신이 아니라 매번 딴 워커가 된다.
- 워커가 `/api/` 나 `?v=` 정적 자산을 캐시하면 안 된다. 시세가 낡은 값으로
  그려지는 것이 오프라인 화면보다 나쁘고, 정적 캐싱은 HTTP 캐시가 이미 한다
  (app/main.py STATIC_VERSIONED의 "옛 내용이 새 키로 박히는" 기록 참고).
  코드 전체를 검사할 수는 없지만 워커가 만지는 URL이 오프라인 페이지 하나뿐인
  것은 확인할 수 있다.
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app

client = TestClient(app)

# 사람이 여는 페이지 전부. offline.html은 워커 전용이고
# naver*.html은 소유확인 파일이라 제외한다.
PAGES = sorted(
    page
    for page in config.STATIC_DIR.glob("*.html")
    if page.name != "offline.html" and not page.name.startswith("naver")
)


def test_manifest_is_served_and_parses():
    response = client.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = json.loads(response.text)
    assert manifest["scope"] == "/", "스코프가 루트가 아니면 일부 페이지가 앱 밖이 된다"
    assert manifest["start_url"].startswith("/")
    assert manifest["display"] == "standalone"


def test_manifest_icons_exist_and_cover_the_required_set():
    """설치 프롬프트의 최소 요건은 192와 512다. 경로가 죽으면 조용히 미달된다."""
    manifest = json.loads(client.get("/manifest.webmanifest").text)

    sizes = set()
    for icon in manifest["icons"]:
        src = icon["src"]
        assert src.startswith("/static/"), f"매니페스트 아이콘이 정적 경로 밖이다: {src}"
        assert (config.STATIC_DIR / src.removeprefix("/static/")).is_file(), f"없는 파일: {src}"
        sizes.add(icon["sizes"])
    assert {"192x192", "512x512"} <= sizes


def test_service_worker_is_served_from_the_root_scope():
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    # 갱신은 이 URL의 바이트 비교로 일어난다 — 캐시가 물고 있으면 안 된다.
    assert response.headers["cache-control"] == "no-cache"


def test_service_worker_never_touches_data_urls():
    """워커 코드에 /api/ 나 `?v=` 자산 URL이 나타나면 그 항목마다 '낡은 값'
    위험을 재검토해야 한다. 캐시에 넣는 URL은 오프라인 페이지 하나뿐이어야
    한다 — 푸시 알림의 아이콘 URL처럼 캐시 밖에서 쓰는 참조는 허용된다."""
    source = (config.STATIC_DIR / "sw.js").read_text(encoding="utf-8")

    urls = set(re.findall(r'"(/[^"]*)"', source))
    assert not any(url.startswith("/api/") for url in urls), urls
    assert not any("?v=" in url for url in urls), urls
    assert source.count("cache.add") == 1, "캐시에 넣는 곳이 늘었다 — 낡은 값 위험을 재검토하라"
    assert 'OFFLINE_URL = "/static/offline.html"' in source


def test_offline_page_is_self_contained():
    """오프라인에 보여 줄 페이지가 네트워크를 참조하면 그 부분만 깨진 화면이 된다."""
    text = (config.STATIC_DIR / "offline.html").read_text(encoding="utf-8")

    assert 'href="/static' not in text
    assert 'src="/static' not in text
    assert "http://" not in text and "https://" not in text
    assert client.get("/static/offline.html").status_code == 200


@pytest.mark.parametrize("page", PAGES, ids=lambda page: page.name)
def test_every_page_declares_the_manifest_and_registers_the_worker(page):
    """설치 가능 판정은 페이지 단위다 — 사용자가 /crypto 로 들어와도 설치할 수
    있어야 하므로 선언은 전 페이지에 있어야 한다."""
    text = page.read_text(encoding="utf-8")

    assert 'rel="manifest"' in text, page.name
    assert 'name="theme-color"' in text, page.name
    assert "/static/pwa.js" in text, page.name


def test_assetlinks_is_wired_but_absent_until_the_play_fingerprint_exists():
    """TWA 검증 파일의 배선. 지문은 Play App Signing 키에서 나오므로 파일은 첫
    AAB 업로드 뒤에 생긴다(DIRECTION.md Phase 0 함정 ②). 파일이 없으면 404 —
    빈 배열로 200을 주면 "검증은 됐는데 연결된 앱이 없다"는 다른 뜻이 된다."""
    response = client.get("/.well-known/assetlinks.json")

    if (config.STATIC_DIR / "assetlinks.json").is_file():
        assert response.status_code == 200
        statements = json.loads(response.text)
        assert statements, "빈 배열을 서빙하면 안 된다 — 파일을 지우는 쪽이 맞다"
        for statement in statements:
            assert statement["relation"] == ["delegate_permission/common.handle_all_urls"]
    else:
        assert response.status_code == 404


def test_the_worker_registration_url_carries_no_version():
    """pwa.js가 register하는 /sw.js 에 ?v= 가 붙으면 워커 정체성이 매번 바뀐다."""
    source = (config.STATIC_DIR / "pwa.js").read_text(encoding="utf-8")

    assert 'register("/sw.js")' in source
    assert "sw.js?v" not in source


def test_install_ui_is_wired_quiet_and_self_contained():
    """설치 유도의 세 규칙을 못 박는다.

    - 크롬 기본 인포바 대신 우리 타이밍: beforeinstallprompt를 잡아 둔다.
    - 조용함: 설치되면 다시 안 보이고(appinstalled), 닫으면 침묵 기간이
      있어야 한다 — 매 방문 배너는 알림 해제보다 빠르게 사이트를 해제당한다.
    - 폰·태블릿 전용: PC에서도 beforeinstallprompt는 발화하지만 거기서
      배너는 소음이다(운영자 결정 2026-08-27) — 터치 기기 판정이 있어야 한다.
    - 자기 완결: pwa.js는 전 페이지에 실리므로 외부 호스트 요청이 없어야 한다.
    """
    source = (config.STATIC_DIR / "pwa.js").read_text(encoding="utf-8")

    assert "beforeinstallprompt" in source
    assert "preventDefault" in source
    assert "appinstalled" in source
    assert "mulmit-install-snooze" in source
    assert "(hover: none) and (pointer: coarse)" in source
    assert "http://" not in source and "https://" not in source
