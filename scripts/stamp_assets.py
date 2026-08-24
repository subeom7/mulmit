"""`?v=`를 파일 내용의 해시로 찍는다 — URL과 내용을 1:1로 묶기 위해.

버전이 손으로 매기는 숫자인 동안 같은 사고가 세 번 났다. 마지막(2026-08-23,
PR #189)은 이랬다: 두 PR이 같은 `-47`에서 갈라져 하나는 `-49`, 하나는 `-48`로
올렸고, 병합이 끝난 main은 **`-49`를 가리키는데 `monitor.js` 내용만 바뀐**
상태가 됐다. 브라우저에게 URL은 캐시 키라, 이전 배포 때 사이트를 연 사람은
`max-age=86400` 동안 옛 파일을 계속 실행했다. 배포도 CI도 초록이었다.

숫자를 잘 고르는 규율로는 못 막는다. 두 사람(또는 두 PR)이 같은 숫자를 고르는
것이 문제이고, 해시는 고를 것이 없다 — 내용이 같으면 반드시 같고 다르면 반드시
다르다.

파일 단위로 찍으므로 `monitor.js`를 고쳐도 `legal.css`의 캐시는 살아 있다.

    python scripts/stamp_assets.py          # 찍는다
    python scripts/stamp_assets.py --check  # 어긋난 곳만 알려 준다(0/1로 끝난다)

`tests/test_asset_versions.py`가 같은 계산을 다시 해서 강제한다.

캐시 수명은 건드리지 않는다. 해시는 **충돌**을 없애지 그 자체로 배포의 원자성을
주지는 않는다 — HTML은 새 해시를 가리키는데 서버 파일이 아직 옛것인 찰나가
남아 있으므로, `app/main.py`의 `STATIC_VERSIONED`(하루, ETag로 자가 치유)는
그대로 두는 것이 맞다.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
# `/static/monitor.js?v=...`의 이름과 기존 버전을 잡는다.
REFERENCE = re.compile(r'(/static/([A-Za-z0-9_.-]+\.(?:js|css)))\?v=([^"\'\s>]*)')
DIGEST_LENGTH = 10


def digest(path: Path) -> str:
    """줄바꿈을 LF로 맞춘 뒤 해싱한다.

    같은 파일이 작업 사본에서는 CRLF, 저장소에서는 LF일 수 있다(git의 `text=auto`).
    바이트를 그대로 해싱하면 그 둘의 해시가 달라져서, 윈도우에서 찍은 스탬프가
    CI에서 어긋난다 — 2026-08-24에 실제로 그랬다. 파일 하나를 CRLF로 다시 쓴
    편집 스크립트 때문이었고, 화면은 멀쩡한데 CI만 빨개져서 원인을 찾는 데
    시간이 걸렸다.

    URL은 **내용**을 가리켜야 하고, 줄바꿈 표기는 내용이 아니다.
    """
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()[:DIGEST_LENGTH]


def expected_versions() -> dict[str, str]:
    """자산 파일 이름 -> 그 내용의 해시."""
    return {
        asset.name: digest(asset)
        for asset in sorted(STATIC.iterdir())
        if asset.is_file() and asset.suffix in (".js", ".css")
    }


def stamp(text: str, versions: dict[str, str]) -> tuple[str, list[str]]:
    """HTML 한 장을 다시 찍고, 이름을 모르는 참조를 함께 돌려준다."""
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        href, name = match.group(1), match.group(2)
        version = versions.get(name)
        if version is None:
            unknown.append(name)
            return match.group(0)
        return f"{href}?v={version}"

    return REFERENCE.sub(replace, text), unknown


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="고치지 않고 어긋난 곳만 보고한다")
    args = parser.parse_args()

    versions = expected_versions()
    stale: list[str] = []
    missing: list[str] = []
    for page in sorted(STATIC.glob("*.html")):
        original = page.read_text(encoding="utf-8")
        stamped, unknown = stamp(original, versions)
        missing.extend(f"{page.name}: {name}" for name in unknown)
        if stamped == original:
            continue
        stale.append(page.name)
        if not args.check:
            page.write_text(stamped, encoding="utf-8", newline="\n")

    for name in missing:
        print(f"참조하는 자산이 없다: {name}", file=sys.stderr)
    if args.check:
        if stale:
            print("자산 버전이 내용과 어긋난다: " + ", ".join(stale), file=sys.stderr)
            print("python scripts/stamp_assets.py 로 다시 찍어라", file=sys.stderr)
        return 1 if (stale or missing) else 0

    print(f"{len(stale)}장 다시 찍었다" if stale else "이미 맞다")
    for name, version in versions.items():
        print(f"  {name:16} {version}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
