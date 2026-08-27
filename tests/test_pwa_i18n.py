"""PWA 배너와 알림 UI가 언어 설정을 따른다 (2026-08-27).

`pwa.js`는 **모든 페이지에 실린다.** 그래서 여기 한국어가 박혀 있으면 영어
모드로 보는 사람은 사이트 어디에서든 한국어 배너를 만난다 — 종목·코인 상세를
이중언어로 만든 뒤에도 마지막까지 남아 있던 것이 이것이었다(실측 2026-08-26).

언어를 스스로 판단해야 하는 이유. 다른 페이지들은 `<html lang>`을 보고 갈리지만
그 속성을 세우는 주체가 페이지마다 다르고(대시보드는 monitor.js, 상세 페이지는
자기 `<head>` 부트), `pwa.js`는 그보다 먼저 돌 수도 있다. 그래서 저장된 값을
직접 읽는다 — 열쇠는 사이트 전체가 공유하는 `monitor.locale` 하나다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PWA = (STATIC / "pwa.js").read_text(encoding="utf-8")


def _without_comments(source: str) -> str:
    source = re.sub(r"(?m)^\s*//.*$", "", source)
    return re.sub(r"(?s)/\*.*?\*/", "", source)


def test_it_reads_the_shared_locale_key_itself() -> None:
    """`<html lang>`을 기다리면 늦는다 — 이 스크립트가 먼저 돌 수 있다."""
    assert 'localStorage.getItem("monitor.locale")' in PWA, (
        "저장된 언어를 직접 읽지 않는다"
    )
    assert "function t(ko, en)" in PWA, "번역 헬퍼가 없다"
    assert "catch (e)" in PWA, (
        "저장소가 막힌 브라우저에서 터진다 — 사생활 모드가 그렇다"
    )


def test_every_ui_string_is_bilingual() -> None:
    """빠뜨린 문자열은 영어 화면에 한글로 남는다.

    검사는 `t()`의 첫 인자를 지우고 남은 한글을 본다. 첫 인자가 문자열 **연결**인
    경우(`t("±" + n + "% …", …)`)는 지워지지 않으므로 따로 봐준다 — 그 형태도
    감싸진 것이다.
    """
    body = _without_comments(PWA)
    stripped = body
    for quote in ('"', "'", "`"):
        q = re.escape(quote)
        stripped = re.sub(r"t\(" + q + r"[^" + q + r"\n]*" + q + r"\s*,", "t(", stripped)
    leaked = [
        line.strip()[:70]
        for line in stripped.split("\n")
        if re.search(r"[가-힣]", line) and not re.search(r"\bt\(", line)
    ]
    assert not leaked, f"영어 모드에서 한글로 남을 줄: {leaked}"


def test_the_alert_button_speaks_both_languages() -> None:
    """설치 배너만이 아니라 **알림 UI 전체**가 대상이었다.

    켜짐·차단됨·임계값 세 상태가 모두 한국어 고정이었다.
    """
    for korean in ("알림 켜짐", "알림이 차단됨", "넘으면 알림 받기"):
        match = re.search(r"t\([^)]*" + re.escape(korean), PWA)
        assert match, f"'{korean}' 상태 문구가 t()로 감싸지지 않았다"
    assert "Alerts on" in PWA and "blocked by the browser" in PWA, "영문 상태 문구가 없다"


def test_the_ios_hint_is_translated_too() -> None:
    """iOS는 설치 이벤트가 없어 이 안내가 유일한 관문이다 — 여기가 한국어면 막힌다."""
    assert "Add to Home Screen" in PWA, "iOS 안내의 영문이 없다"
    assert "홈 화면에 추가" in PWA, "한국어 안내가 사라졌다"
