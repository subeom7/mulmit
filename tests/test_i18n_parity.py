"""화면 문구 사전의 두 언어가 어긋나지 않는지.

`t()`는 영어 키가 없으면 조용히 한국어로 되돌아간다.

    const t = (key, params) => TEXT[state.lang]?.[key] || TEXT.ko[key] || key;

그래서 EN 키를 빠뜨려도 에러가 나지 않는다. 영어로 바꿨는데 값 몇 개만
한국어로 남은 채 배포됐고, 콘솔에도 아무 흔적이 없었다. 두 언어를 나란히 놓고
사람이 세는 방법으로는 다시 놓친다 — 그래서 여기서 센다.

사전은 두 벌이다. 대시보드는 monitor.js의 `TEXT`를, `/analytics`는 제 안의
`I18N`을 쓴다. 페이지가 어느 사전을 읽는지까지 확인해야 "사전에는 있는데 그
화면에서는 안 잡히는" 열쇠를 잡을 수 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
MONITOR = STATIC / "monitor.js"

# `"key": "값"` 꼴만 센다. 값이 따옴표로 시작하는 항목이 사전의 전부다.
ENTRY = re.compile(r'[{,]\s*"([A-Za-z][\w.]*)"\s*:\s*"')
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# `document.createElement(` 처럼 t로 끝나는 이름에 걸리지 않도록 앞을 막는다.
CALL = re.compile(r'(?<![\w.$])t\(\s*"([A-Za-z][\w.]*)"')
ATTR = re.compile(r'data-i18n="([A-Za-z][\w.]*)"')


def _blocks(source: str, marker: str) -> tuple[str, str]:
    start = source.index(marker)
    ko = source.index("\n  ko: {", start)
    en = source.index("\n  en: {", ko)
    return source[ko:en], source[en : source.index("\n};", en)]


def _entries(block: str) -> dict[str, str]:
    """키 → 값. 값은 다음 키가 시작되기 전까지의 원문 조각으로 충분하다."""
    found: dict[str, str] = {}
    matches = list(ENTRY.finditer(block))
    for index, match in enumerate(matches):
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        found[match.group(1)] = block[match.end() : stop]
    return found


def _dictionary(path: Path, marker: str) -> tuple[dict[str, str], dict[str, str]]:
    ko_block, en_block = _blocks(path.read_text(encoding="utf-8"), marker)
    return _entries(ko_block), _entries(en_block)


# `/analytics`는 2026-08-24에 자체 사전을 버리고 `.lang-ko`/`.lang-en` 스팬
# 방식으로 바뀌었다(용어 사전과 같은 방식). 대조할 사전이 하나 남는다.
DICTIONARIES = {
    "monitor.js TEXT": (MONITOR, "const TEXT = {"),
}


def test_the_two_languages_carry_the_same_keys():
    for name, (path, marker) in DICTIONARIES.items():
        ko, en = _dictionary(path, marker)
        assert len(ko) > 100, f"{name} 사전을 제대로 못 읽었다 — 파싱이 깨졌는지 먼저 보라"
        missing_en = sorted(set(ko) - set(en))
        missing_ko = sorted(set(en) - set(ko))
        assert not missing_en, f"{name}: 영어가 없어 한국어로 되돌아갈 키 {missing_en}"
        assert not missing_ko, f"{name}: 한국어에만 없는 키 {missing_ko}"


def test_both_languages_take_the_same_placeholders():
    """`{n}`이 한쪽에만 있으면 그 언어에서 숫자가 사라지거나 중괄호가 노출된다."""
    for name, (path, marker) in DICTIONARIES.items():
        ko, en = _dictionary(path, marker)
        mismatched = {
            key: (sorted(set(PLACEHOLDER.findall(ko[key]))), sorted(set(PLACEHOLDER.findall(value))))
            for key, value in en.items()
            if key in ko and set(PLACEHOLDER.findall(ko[key])) != set(PLACEHOLDER.findall(value))
        }
        assert not mismatched, f"{name}: 자리표시자가 어긋난 키 {mismatched}"


def test_every_key_monitor_asks_for_exists():
    known = set(_dictionary(MONITOR, "const TEXT = {")[0])
    asked = set(CALL.findall(MONITOR.read_text(encoding="utf-8")))
    assert asked, "t(\"…\") 추출이 깨졌다"
    assert asked <= known, f"사전에 없는 문구를 부른다: {sorted(asked - known)}"


def _dictionary_for(page: Path) -> set[str] | None:
    """그 페이지의 `data-i18n`을 실제로 풀어 줄 사전. 없으면 None."""
    source = page.read_text(encoding="utf-8")
    if "const I18N = {" in source:
        return set(_entries(_blocks(source, "const I18N = {")[0]))
    if "monitor.js" in source:
        return set(_dictionary(MONITOR, "const TEXT = {")[0])
    return None


def test_every_data_i18n_on_a_page_has_a_dictionary_that_answers_it():
    """`data-i18n`은 사전을 찾는 열쇠다. 사전이 없으면 EN에서 한국어로 남는다.

    monitor.js도 제 사전도 없는 페이지에 `data-i18n`을 달면 조용히 아무 일도
    일어나지 않는다 — 언어를 바꿔도 그 자리만 한국어로 남는다.
    """
    orphans: dict[str, list[str]] = {}
    for page in sorted(STATIC.glob("*.html")):
        keys = set(ATTR.findall(page.read_text(encoding="utf-8")))
        if not keys:
            continue
        known = _dictionary_for(page)
        if known is None:
            orphans[page.name] = sorted(keys)
        elif keys - known:
            orphans[page.name] = sorted(keys - known)
    assert not orphans, f"풀리지 않는 data-i18n: {orphans}"
