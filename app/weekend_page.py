"""주말 참고가 전용 페이지의 서버 렌더 본문.

**왜 별도 페이지인가.** 이 사이트의 문제는 기능이 아니라 유입이다(2026-08-24
실측: 색인 5개 / 미색인 2,957개). `물밑`은 일반명사라 잡을 수 없지만
`주말 삼성전자 주가` 같은 **롱테일 질의**는 잡을 수 있고, 지금 그 답은 `/kr`의
여러 섹션 중 하나로 묻혀 있다. 그 질의에만 답하는 자리가 없었다.

**무엇을 말하고 무엇을 말하지 않는가.** 2026-08-24에 홍보 훅을 판정하면서
정리한 선을 그대로 지킨다.

    말할 수 있다   "금요일 종가 뒤로 무슨 일이 있었나"
                   "장이 닫혀 있는 동안에도 움직이는 참고가"
    말할 수 없다   "월요일에 얼마로 출발할지"

뒤엣것은 우리 자신의 고지가 정면으로 부정한다 — 얕은 유동성·레버리지·
마크-오라클 괴리 때문에 크게 왜곡될 수 있다고 `/api/market/weekend`가 이미
적어 두었다. 홍보가 제품 고지와 반대면 둘 중 하나가 거짓이 되고, 그 훅으로
데려온 사람은 월요일에 배신감을 느낀다. **신규 유입을 얻고 재방문을 잃는
거래**라 하지 않는다.

**요청 경로의 비용.** `build_kr_overnight()`은 5초 TTL 캐시(300초 stale 폴백)
뒤에 있어 크롤러가 몰려도 상류 호출은 5초에 한 번이다. `/stock/{code}`처럼
3,000개가 아니라 URL 하나뿐이라 이 정도면 충분하다.

**값은 만들지 않는다.** lane이 조립해 둔 것을 배치만 한다.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from . import config, data_rights, kr_overnight

log = logging.getLogger(__name__)

SITE = "https://mulmit.com"

#: 이 페이지가 답하는 질의. 제목·본문이 이 말들을 실제로 담고 있어야 한다.
TARGET_QUERIES = ("주말 삼성전자 주가", "주말 주식 시세", "SK하이닉스 주말", "코스피 주말")


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


#: 이 페이지가 답하는 질문은 "주말에 한국 주식 얼마인가"다.
#:
#: ADR과 미국 ETF 카드는 같은 lane에 있지만 **다른 질문에 답한다.** SK하이닉스
#: ADR의 `vs_official_percent`는 실측 30.5%인데, 그것은 고장이 아니라 **ADR
#: 프리미엄**이다(원주 1주 = ADR 10주). 그 값을 이 표에 넣으면 원화 두 값이
#: 30% 벌어진 채 나란히 놓여 **깨진 것처럼 보인다** — 여기 온 사람은 프리미엄을
#: 물으러 온 것이 아니다. EWY는 값이 아예 `null`이다. 둘 다 `/kr`에서 제 맥락과
#: 함께 본다.
PAGE_KINDS = ("equity", "index")


def _amount(value: Any, unit: Any) -> str:
    """금액 또는 지수. **단위는 페이로드가 들고 있는 것을 쓴다.**

    처음엔 원화라고 가정하고 "원"을 붙였다가 **코스피 200에 `1,054원`** 이 찍혔다
    (2026-08-25 라이브 실측). 지수의 단위는 `pt`이고, 그 사실이 카드에 이미
    적혀 있었다 — 읽지 않은 쪽이 틀렸다.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if str(unit or "").upper() == "KRW":
        return f"{round(number):,}원"
    if str(unit or "") == "pt":
        return f"{number:,.2f}pt"
    return f"{number:,.2f} {_esc(unit)}".strip()


def _pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:+.2f}%"


def _tone(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number > 0:
        return " up"
    return " down" if number < 0 else ""


def _row(card: dict[str, Any]) -> str:
    label = (card.get("label") or {}).get("ko") or card.get("id") or ""
    code = card.get("code")
    official = card.get("official") or {}
    implied = card.get("implied") or {}
    reference = card.get("session_reference") or {}

    close = (
        _amount(official.get("close"), official.get("unit"))
        if official.get("status") == "ok" else "—"
    )
    close_date = _esc(official.get("date") or "")
    now_value = (
        _amount(implied.get("value"), implied.get("unit"))
        if implied.get("status") == "ok" else "—"
    )
    # 마감 이후 얼마나 움직였나 — 이 페이지가 답하는 바로 그 숫자다.
    moved = reference.get("vs_percent") if reference.get("status") == "ok" else None

    name_cell = _esc(label)
    if code:
        name_cell = f'<a href="/stock/{_esc(code)}">{name_cell}</a>'

    return (
        "<tr>"
        f"<th scope=\"row\">{name_cell}</th>"
        f"<td class=\"num\">{close}<small>{close_date}</small></td>"
        f"<td class=\"num\">{now_value}</td>"
        f"<td class=\"num{_tone(moved)}\">{_pct(moved)}</td>"
        "</tr>"
    )


def _session_line(payload: dict[str, Any]) -> str:
    """지금이 주말 창인지 아닌지를 첫 줄에서 말한다.

    창 밖이라고 페이지가 쓸모없어지지는 않는다 — 장이 닫혀 있는 동안의 참고가는
    평일 밤에도 같은 뜻이다. 다만 **지금이 언제인지**를 숨기면 안 된다.
    """
    session = payload.get("session") or {}
    if session.get("active"):
        return (
            "지금은 <strong>주말 참고가 세션</strong>입니다. "
            "한국장은 닫혀 있고, 아래 값은 해외에서 거래되는 합성 무기한선물을 "
            "원화로 환산한 참고가입니다."
        )
    return (
        "지금은 주말 세션이 아닙니다. 아래는 <strong>마지막 정규장 마감 이후</strong>의 "
        "참고가입니다 — 주말 세션은 <strong>금요일 20시부터 월요일 8시(KST)</strong>까지입니다."
    )


def _closed(reason: str) -> dict[str, str]:
    """값 없이도 페이지는 성립한다 — 설명이 이 페이지의 절반이기 때문이다."""
    return {
        "SESSION": _esc(reason),
        "ROWS": '<tr><td colspan="4" class="weekend-empty">'
                + _esc(reason) + "</td></tr>",
        "ASOF": "",
        "DISCLAIMER": "",
        "SOURCE": "",
    }


def render() -> dict[str, str]:
    """(요약, 표, 고지, 출처) — 템플릿이 그대로 끼워 넣는다.

    **권리를 먼저 묻는다.** `/api/kr/overnight`는 `require_hip3_public_display()`를
    거치는데, 여기서 `build_kr_overnight()`을 곧장 부르면 그 문을 돌아서 들어가는
    셈이 된다. 게이트가 닫혀 있으면 값 없이 설명만 낸다 — 이 페이지는 표가
    비어도 질문에는 답하므로 빈손으로 돌아가지 않는다.
    """
    if not data_rights.hip3_public_display_enabled():
        return _closed(
            "지금은 참고가를 표시하지 않습니다. 이 값의 외부 표시 권한을 확인하는 중입니다."
        )
    try:
        payload = kr_overnight.build_kr_overnight()
    except Exception:  # noqa: BLE001 - 색인용 본문 때문에 페이지가 죽으면 안 된다
        log.warning("weekend page SSR failed", exc_info=True)
        return _closed("지금은 값을 불러올 수 없습니다.")

    cards = [
        c for c in (payload.get("cards") or [])
        if isinstance(c, dict) and c.get("kind") in PAGE_KINDS
    ]
    rows = "".join(_row(card) for card in cards)

    official_dates = sorted({
        (c.get("official") or {}).get("date")
        for c in cards
        if (c.get("official") or {}).get("status") == "ok"
    } - {None})
    note = ""
    for card in cards:
        note = (card.get("official") or {}).get("publication_note_ko") or note
        if note:
            break

    as_of = ""
    if official_dates:
        as_of = f"공식 종가 기준일 {_esc(official_dates[-1])}"
        if note:
            as_of += f" · {_esc(note)}"

    disclaimer = (payload.get("disclaimer") or {}).get("ko") or ""
    source = payload.get("source") or {}
    source_html = ""
    if source:
        name = _esc(source.get("provider_name") or source.get("publisher") or "")
        url = _esc(source.get("url") or "")
        if name and url:
            source_html = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{name}</a>'
        elif name:
            source_html = name

    return {
        "SESSION": _session_line(payload),
        "ROWS": rows,
        "ASOF": as_of,
        "DISCLAIMER": _esc(disclaimer),
        "SOURCE": source_html,
    }


def json_ld() -> str:
    """schema.org FAQPage.

    이 페이지는 실제로 질문에 답하는 구조이고, 그 질문이 사람들이 검색창에
    치는 문장 그대로다. 답도 페이지 본문에 그대로 있다 — 본문에 없는 것을
    구조화 데이터로만 주장하지 않는다.
    """
    faq = [
        (
            "주말에 삼성전자 주가를 볼 수 있나요?",
            "한국거래소는 주말에 열지 않아 실제 체결가는 없습니다. 다만 삼성전자·"
            "SK하이닉스·코스피200은 해외 시장에서 24시간 거래되는 합성 무기한선물이 "
            "있어, 그 값을 원화로 환산한 참고가를 볼 수 있습니다.",
        ),
        (
            "이 값이 월요일 시초가인가요?",
            "아닙니다. 얕은 유동성과 레버리지, 기초자산과의 괴리 때문에 실제 시초가와 "
            "크게 다를 수 있습니다. 이 값은 예측이 아니라 장이 닫혀 있는 동안의 참고가입니다.",
        ),
        (
            "주말 참고가는 언제 볼 수 있나요?",
            "금요일 20시부터 월요일 8시(한국시간)까지가 주말 세션입니다. 그 밖의 시간에도 "
            "마지막 정규장 마감 이후의 참고가를 같은 방식으로 볼 수 있습니다.",
        ),
    ]
    payload = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "@id": f"{SITE}/weekend",
        "url": f"{SITE}/weekend",
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "Mulmit", "url": SITE},
        "mainEntity": [
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            }
            for question, answer in faq
        ],
    }
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def template() -> str:
    return (config.STATIC_DIR / "weekend.html").read_text(encoding="utf-8")
