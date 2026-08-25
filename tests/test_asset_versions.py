"""`?v=`는 자산 내용의 해시여야 한다 — URL과 내용이 1:1이 되도록.

손으로 매기는 숫자로는 같은 사고가 세 번 났다. 마지막(2026-08-23, PR #189):
두 PR이 같은 `-47`에서 갈라져 하나는 `-49`, 하나는 `-48`로 올렸고, 병합 뒤
main은 `-49`를 가리키는데 `monitor.js` 내용만 바뀌었다. 브라우저에게 URL은
캐시 키라 이전 배포 때 방문한 사람은 `max-age=86400` 동안 옛 파일을 실행했다.
배포도 CI도 테스트도 초록이었고, 사이트만 옛 코드로 돌았다.

해시는 고를 것이 없다. 내용이 같으면 반드시 같고, 다르면 반드시 다르다.

어긋나면: `python scripts/stamp_assets.py`
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.stamp_assets import REFERENCE, STATIC, digest, expected_versions  # noqa: E402

PAGES = sorted(page.name for page in STATIC.glob("*.html"))
FIX = "python scripts/stamp_assets.py"


def test_there_are_pages_and_assets_to_check():
    """정규식이 헛돌면 아래 테스트가 통과가 아니라 무의미해진다."""
    assert len(PAGES) >= 10, PAGES
    assert len(expected_versions()) >= 5


@pytest.mark.parametrize("page", PAGES)
def test_every_asset_reference_carries_its_content_hash(page: str):
    versions = expected_versions()
    text = (STATIC / page).read_text(encoding="utf-8")
    wrong = [
        f"{name}?v={found} (내용은 {versions.get(name)})"
        for _href, name, found in REFERENCE.findall(text)
        if versions.get(name) != found
    ]
    assert not wrong, f"{page}의 자산 버전이 내용과 어긋난다: {wrong}. {FIX}"


UNSTAMPED = re.compile(r'(?:src|href)="(/static/[A-Za-z0-9_.-]+\.(?:js|css))(?!\?v=)')


@pytest.mark.parametrize("page", PAGES)
def test_no_asset_reference_ships_without_a_hash(page: str):
    """해시가 **없는** 참조는 스탬퍼도 위 테스트도 보지 못한다.

    `stamp_assets.REFERENCE`가 `?v=`를 요구하기 때문이다 — 새 `<script>`를
    `?v=` 없이 붙이면 스탬퍼가 건너뛰고, 위 테스트도 찾을 게 없어 통과한다.
    그대로 배포되면 브라우저가 그 파일을 영구히 캐시한다.

    2026-08-26에 실제로 그랬다. `/bio`에 console.js를 추가하면서 `?v=`를 안
    붙였는데 `stamp_assets --check`가 "ok"라고 답했다. 통과하는 검사가 아무것도
    보고 있지 않았던 것이다.
    """
    text = (STATIC / page).read_text(encoding="utf-8")
    bare = UNSTAMPED.findall(text)
    assert not bare, (
        f"{page}에 해시 없는 자산 참조가 있다: {bare} — `?v=0`을 붙이고 {FIX} 를 돌리라"
    )


@pytest.mark.parametrize("page", PAGES)
def test_every_referenced_asset_exists(page: str):
    versions = expected_versions()
    text = (STATIC / page).read_text(encoding="utf-8")
    missing = [name for _href, name, _v in REFERENCE.findall(text) if name not in versions]
    assert not missing, f"{page}가 없는 자산을 가리킨다: {missing}"


def test_the_same_bytes_always_get_the_same_version(tmp_path: Path):
    """해시가 자리나 시각이 아니라 내용에만 달려 있어야 한다."""
    one, two = tmp_path / "a.js", tmp_path / "b.js"
    one.write_bytes(b"console.log(1);")
    two.write_bytes(b"console.log(1);")
    assert digest(one) == digest(two)

    two.write_bytes(b"console.log(2);")
    assert digest(one) != digest(two)


def test_a_changed_asset_forces_a_changed_url():
    """이 가드가 막으려는 사고 그 자체 — 내용이 바뀌었는데 URL이 그대로인 상태."""
    target = STATIC / "monitor.js"
    original = target.read_bytes()
    before = digest(target)
    try:
        target.write_bytes(original + b"\n// a change\n")
        assert digest(target) != before
        # 그리고 그 상태에서는 페이지가 어긋난 것으로 잡혀야 한다.
        text = (STATIC / "landing.html").read_text(encoding="utf-8")
        stamped = {name: found for _href, name, found in REFERENCE.findall(text)}
        assert stamped["monitor.js"] != digest(target), "바뀐 파일이 옛 URL을 그대로 쓰고 있다"
    finally:
        target.write_bytes(original)


def test_the_digest_ignores_line_endings():
    """같은 파일이 작업 사본에서는 CRLF, 저장소에서는 LF일 수 있다(git `text=auto`).

    바이트를 그대로 해싱하면 그 둘의 해시가 달라진다. 윈도우에서 찍은 스탬프가
    CI에서 어긋나고, 화면은 멀쩡한데 CI만 빨개진다 — 2026-08-24에 실제로 그랬다.
    편집 스크립트 하나가 CSS를 CRLF로 다시 쓴 것이 원인이었다.

    URL은 내용을 가리켜야 하고, 줄바꿈 표기는 내용이 아니다.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        lf = Path(folder) / "lf.css"
        crlf = Path(folder) / "crlf.css"
        lf.write_bytes(b"a {\n  color: red;\n}\n")
        crlf.write_bytes(b"a {\r\n  color: red;\r\n}\r\n")
        assert digest(lf) == digest(crlf), "줄바꿈 표기가 URL을 바꾸면 안 된다"
