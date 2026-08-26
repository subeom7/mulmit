"""종목 상세 페이지가 언어 설정을 따른다 (2026-08-26).

운영자 지적: "EN 토글 켜고 들어가도 한국어로 나와."

실측으로 좁힌 원인. `/analytics` 목록 자체는 멀쩡했다 — 영어 모드에서 UI 한글이
0개였고 남은 것은 회사 이름뿐이었다. 문제는 거기서 **들어가는 상세 페이지**였다:

    저장된 설정   monitor.locale = "en"
    그런데        <html lang> = "ko"
    이중언어 요소  0개
    언어 토글      없음

`console.js`는 `<html lang>`을 `data-lang`으로 **미러링만** 한다. 그것을 세팅하는
주체가 페이지마다 다른데(대시보드는 monitor.js, /analytics는 자기 인라인 스크립트)
`/stock/{코드}`에는 그 주체가 아예 없었다.

이 파일이 지키는 것:

1. 저장된 언어를 **본문이 그려지기 전에** 적용한다 — 늦으면 한국어가 번쩍인다.
2. 언어 토글이 있고, 그것이 저장한다.
3. UI 문구가 이중언어다. 값·고유명사는 아니다.
4. 서버가 박는 제목은 **시장에 맞춘다** — 국내 종목은 한국어 질의를, 미국 티커는
   영어 질의를 노리는 값이라 사용자 로케일로 뒤집지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
PAGE = (STATIC / "stock.html").read_text(encoding="utf-8")


def _script() -> str:
    start = PAGE.index("<script>", PAGE.index("</header>"))
    return PAGE[start : PAGE.index("</script>", start)]


def test_the_saved_locale_is_applied_before_the_body_renders() -> None:
    """늦게 적용하면 영어 사용자에게 한국어가 한 프레임 번쩍인다."""
    head = PAGE[: PAGE.index("</head>")]
    assert 'localStorage.getItem("monitor.locale")' in head, (
        "저장된 언어를 <head>에서 읽지 않는다 — 본문이 먼저 그려진다"
    )
    assert 'document.documentElement.lang = "en"' in head, (
        "<html lang>을 세팅하지 않으면 console.js가 미러링할 것이 없다"
    )


def test_the_page_has_a_language_toggle_that_persists() -> None:
    """토글이 없으면 이 페이지에 들어온 사람은 언어를 바꿀 방법이 없다."""
    assert 'id="locale-toggle"' in PAGE, "언어 버튼이 없다"
    script = _script()
    assert 'localStorage.setItem("monitor.locale"' in script, "토글이 저장하지 않는다"
    assert "location.reload()" in script, (
        "이 페이지는 한 번 그리고 끝난다 — 부분 재렌더 대신 새로고침으로 맞춘다"
    )


def test_the_ui_strings_are_bilingual() -> None:
    """마크업은 두 span으로, JS는 t(ko, en)으로."""
    assert PAGE.count('class="lang-ko"') >= 10, "이중언어 마크업이 거의 없다"
    assert PAGE.count('class="lang-en"') == PAGE.count('class="lang-ko"'), (
        "한쪽 언어만 있는 자리가 있다"
    )
    script = _script()
    assert "const t = (ko, en) =>" in script, "JS 번역 헬퍼가 없다"
    assert script.count("t(") >= 30, "JS 문자열 대부분이 아직 한국어 고정이다"


def test_no_ui_string_is_left_hardcoded_korean() -> None:
    """빠뜨린 문자열은 영어 화면에 한글로 남는다 — 그게 이 버그의 모양이었다.

    검사 방식으로 두 번 헤맸다. 기록해 둔다.

    1. 따옴표 짝으로 리터럴을 뽑았더니 템플릿 리터럴 안의 `${... ? "PER " : ""}`
       에서 따옴표를 가로질러 잡아, 멀쩡한 코드를 "누락"으로 신고했다.
    2. 그래서 줄 단위로 바꿨더니 이번엔 **못 잡았다** — 표 머리글은 한 줄에
       여러 문자열이 오므로, 같은 줄에 `t(`가 하나라도 있으면 옆의 한글 고정
       문자열이 통과했다. 이 파일에서 가장 흔한 모양이 그것이다.

    지금 방식: `t(첫인자,` 를 먼저 **지우고** 남은 한글을 본다. 따옴표 종류를
    맞춰 지우므로 템플릿 리터럴 안의 다른 따옴표에 걸리지 않는다.
    """
    script = _script()
    without_comments = re.sub(r"(?m)^\s*//.*$", "", script)
    without_comments = re.sub(r"(?s)/\*.*?\*/", "", without_comments)

    # 번역된 것(= t()의 첫 인자)을 지운다. 같은 따옴표만 제외하고 훑으므로
    # 백틱 리터럴 안의 "..."에는 걸리지 않는다.
    stripped = without_comments
    for quote in ('"', "'", "`"):
        q = re.escape(quote)
        stripped = re.sub(r"t\(" + q + r"[^" + q + r"\n]*" + q + r"\s*,", "t(", stripped)

    leaked = [
        line.strip()[:64]
        for line in stripped.split("\n")
        if re.search(r"[가-힣]", line)
    ]
    assert not leaked, f"영어 모드에서 한글로 남을 줄: {leaked}"


def test_the_lane_english_text_is_used() -> None:
    """레인이 basis_ko와 basis_en을 둘 다 준다. 페이지가 한쪽만 쓰고 있었다."""
    script = _script()
    assert "payload.basis_en" in script, "영문 설명을 받아 두고도 쓰지 않는다"
    assert ".basis_ko ||" not in script, "아직 한국어 설명을 직접 박는 곳이 있다"


def test_the_server_title_stays_market_appropriate() -> None:
    """제목은 사용자 로케일이 아니라 시장을 따른다.

    국내 종목 페이지는 한국어 질의를, 미국 티커 페이지는 영어 질의를 노린다.
    사용자가 EN을 켰다고 국내 종목 제목을 영어로 바꾸면 색인에서 잃는다.
    """
    main = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    block = main[main.index("def stock_hub") : main.index("def stock_hub") + 2200]
    assert "주가·재무·내부자 공시" in block, "국내 종목 제목이 한국어가 아니다"
    assert "financials, insiders & 8-K" in block, "미국 티커 제목이 영어가 아니다"
