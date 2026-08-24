"""README가 실제 앱과 어긋나지 않게 한다.

문서는 조용히 낡는다. 2026-08-24에 확인해 보니 README 첫 문단이 이 사이트를
"개별 티커의 CAPM 지표 · 최대낙폭(MDD) · 미래 MDD 확률분포를 보는 분석 화면도
그대로 있다"고 소개하고 있었다 — 그 화면은 같은 날 지웠고, 그 전에도 가격
lane이 꺼져 있어 운영에서 보이지 않던 화면이었다. API 표에는 다섯 개가 빠져
있었고, 구조 트리는 없어진 파일을 가리켰다.

읽는 사람은 저장소를 처음 보는 사람이다. 첫 문단이 틀리면 나머지를 믿을
이유가 없어진다. 그래서 기계로 확인할 수 있는 것만 기계에 맡긴다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.main import app

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

API_ROUTES = sorted({
    route.path for route in app.routes
    if getattr(route, "path", "").startswith("/api/")
})
PAGE_ROUTES = sorted({
    route.path for route in app.routes
    if getattr(route, "path", "")
    and not route.path.startswith(("/api/", "/static"))
    and "{" not in route.path
    and route.path.endswith(("/", "s", "r", "o", "c", "y", "w"))  # 사람이 여는 페이지만
    and not route.path.endswith((".xml", ".txt", ".ico", ".html"))
})


def _documented(path: str) -> bool:
    """파라미터가 붙은 라우트는 접두사만 적혀 있어도 적힌 것으로 본다."""
    return path in README or path.split("{")[0].rstrip("/") in README


def test_there_are_routes_to_check():
    """정규식이 헛돌면 아래 테스트가 통과가 아니라 무의미해진다."""
    assert len(API_ROUTES) >= 40, API_ROUTES


@pytest.mark.parametrize("path", API_ROUTES)
def test_every_api_route_appears_in_the_readme(path: str):
    assert _documented(path), (
        f"{path}가 README에 없다. 새 엔드포인트를 열었으면 'API' 표에 한 줄 적어라 — "
        "여기서 걸리는 것이 배포 뒤 아무도 모르는 것보다 낫다."
    )


@pytest.mark.parametrize("page", ["/", "/kr", "/us", "/crypto", "/bio", "/analytics", "/news", "/glossary"])
def test_every_reader_facing_page_appears_in_the_readme(page: str):
    assert f"`{page}`" in README, f"{page}가 화면 표에 없다"


def test_the_readme_does_not_advertise_a_screen_that_was_removed():
    """CAPM·MDD 분석 화면은 2026-08-24에 지웠다(ROADMAP §3).

    서버의 `/api/metrics`는 남아 있으므로 README가 그것을 설명하는 것은 맞다.
    틀린 것은 **화면이 있다고 말하는 것**이다.
    """
    assert not (STATIC / "index.html").exists(), "index.html이 돌아왔다 — 이 테스트를 고쳐라"

    for claim in ("CAPM 지표", "미래 MDD 확률분포를 보는 분석", "개별 티커 분석 —"):
        assert claim not in README, f"없는 화면을 소개하고 있다: {claim!r}"
    # 지웠다는 사실 자체는 적혀 있어야 한다 — 서버에 엔드포인트가 남아 있으므로.
    assert "/api/metrics" in README


def test_the_structure_tree_only_names_files_that_exist():
    """구조 트리가 없어진 파일을 가리키고 있었다."""
    tree_start = README.index("  static/")
    tree = README[tree_start : README.index("deploy/", tree_start)]
    named = {
        word for line in tree.splitlines() for word in line.split()
        if word.endswith((".html", ".js", ".css"))
    }
    assert named, "트리에서 파일 이름을 못 찾았다 — 테스트를 고쳐라"
    missing = sorted(name for name in named if not (STATIC / name).exists())
    assert not missing, f"README 구조 트리가 없는 파일을 가리킨다: {missing}"


@pytest.mark.parametrize("gate", [
    "FSC_ENABLED", "DART_ENABLED", "SEC_EDGAR_ENABLED", "CRYPTO_SECTION_ENABLED",
    "BIO_SECTION_ENABLED", "YOUTUBE_ENABLED", "NAVER_DATALAB_ENABLED",
    "COINALYZE_ENABLED", "CHAIN_GAS_ENABLED",
])
def test_the_lane_table_names_the_gate_that_opens_each_lane(gate: str):
    """lane 표는 '무엇을 켜면 열리는가'가 있어야 쓸모가 있다."""
    assert gate in README, f"{gate} lane이 README에 없다"
