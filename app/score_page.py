"""대량보유 스코어보드의 서버 렌더 본문.

`weekend_page`와 같은 문법이다: 롱테일 질의("5% 공시 그 후", "대량보유 공시
주가")에 답하는 SSR 페이지이고, 요청 경로에서 상류를 부르지 않는다 — 배치가
저장한 보드만 배치(配置)한다. 값이 없어도 페이지는 성립한다: 설명(무엇을
어떻게 채점하는가)이 이 페이지의 절반이기 때문이다.

표현 규칙(`docs/DIRECTION.md` §4)이 여기서도 문장을 지배한다: 기록·통계로만
말하고 추천 표현을 쓰지 않는다. 보고자 단위 랭킹은 만들지 않는다 — 카드에
보고자명을 적는 것은 공시 사실의 전달이고, 보고자별 성적 집계는 법인 상대
명예훼손 검토 전 보류다.
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from . import config, kr_scoring
from .providers.base import DataUnavailable

log = logging.getLogger(__name__)

SITE = "https://mulmit.com"

#: 이 페이지가 답하는 질의. 제목·본문이 이 말들을 실제로 담고 있어야 한다.
TARGET_QUERIES = ("대량보유 공시 그 후", "5% 공시 주가", "대량보유상황보고서")

HORIZON_LABELS = {21: "+1개월", 63: "+3개월", 126: "+6개월"}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _pct(value: Any, *, suffix: str = "%") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:+.1f}{suffix}"


def _tone(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number > 0:
        return " up"
    return " down" if number < 0 else ""


def _checkpoint_cell(card: dict[str, Any], horizon: int) -> str:
    checkpoint = next(
        (c for c in card.get("checkpoints", []) if c.get("horizon") == horizon), None
    )
    if checkpoint is None:
        return '<td class="num">—</td>'
    if checkpoint.get("status") == "halted":
        return '<td class="num"><span class="score-halted">정지</span></td>'
    excess = checkpoint.get("excess")
    stock = checkpoint.get("stock_return")
    # 첫 줄이 지수 대비 초과(%p), 작은 줄이 종목 자체 수익률이다 — 강세장에선
    # 롱이 전부 맞아 보이므로 초과가 앞이다(DIRECTION §4 설계 원칙 2).
    main = _pct(excess, suffix="%p") if excess is not None else _pct(stock)
    small = f"<small>{_pct(stock)}</small>" if excess is not None else ""
    return f'<td class="num{_tone(excess if excess is not None else stock)}">{main}{small}</td>'


def _base_cell(card: dict[str, Any]) -> str:
    base = card.get("base") or {}
    if base.get("status") == "ok" and base.get("close"):
        close = f"{round(float(base['close'])):,}원"
        halted = ' <span class="score-halted">정지 중</span>' if base.get("halted") else ""
        return f'<td class="num">{close}<small>{_esc(base.get("date"))}</small>{halted}</td>'
    if base.get("status") == "no_data":
        return '<td class="num">가격 없음</td>'
    return '<td class="num">기준가 대기</td>'


def _live_cell(card: dict[str, Any]) -> str:
    live = card.get("live") or {}
    value = live.get("vs_base_percent")
    if value is None:
        return '<td class="num">—</td>'
    return (
        f'<td class="num{_tone(value)}">{_pct(value)}'
        f"<small>{_esc(live.get('as_of'))}</small></td>"
    )


def _row(card: dict[str, Any]) -> str:
    code = card.get("stock_code")
    name_cell = _esc(card.get("company"))
    if code:
        name_cell = f'<a href="/stock/{_esc(code)}">{name_cell}</a>'
    if card.get("is_new"):
        name_cell += ' <span class="score-new">신규</span>'

    report_date = _esc(card.get("report_date"))
    days = card.get("days_since")
    day_small = f"<small>D+{int(days)}</small>" if isinstance(days, (int, float)) else ""

    ratio = card.get("ratio")
    ratio_cell = "—"
    if isinstance(ratio, (int, float)):
        ratio_cell = f"{ratio:.2f}%"
        change = card.get("ratio_change")
        if isinstance(change, (int, float)) and change:
            ratio_cell += f"<small>{change:+.2f}%p</small>"

    reporter = _esc(card.get("reporter"))
    url = _esc(card.get("report_url"))
    reporter_cell = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{reporter}</a>' if url else reporter

    return (
        "<tr>"
        f"<th scope=\"row\">{name_cell}</th>"
        f"<td>{reporter_cell}</td>"
        f"<td class=\"num\">{report_date}{day_small}</td>"
        f"<td class=\"num\">{ratio_cell}</td>"
        f"{_base_cell(card)}"
        f"{_live_cell(card)}"
        f"{_checkpoint_cell(card, 21)}"
        f"{_checkpoint_cell(card, 63)}"
        f"{_checkpoint_cell(card, 126)}"
        "</tr>"
    )


def _aggregates_html(payload: dict[str, Any]) -> str:
    rows = payload.get("aggregates") or []
    if not rows:
        return (
            "<p>신규 진입 공시의 체크포인트가 아직 표본 수를 채우지 못했습니다. "
            "채점은 공시가 쌓이는 속도대로만 진행되고, 모자란 표본으로는 집계를 "
            "말하지 않습니다.</p>"
        )
    items = []
    for row in rows:
        label = HORIZON_LABELS.get(row.get("horizon"), f"+{row.get('horizon')}영업일")
        share = row.get("positive_share")
        share_text = f"{share * 100:.0f}%" if isinstance(share, (int, float)) else "—"
        items.append(
            f"<li><strong>{_esc(label)}</strong> — 표본 {int(row.get('samples') or 0)}건, "
            f"지수 대비 초과수익 중앙값 {_pct(row.get('median_excess'), suffix='%p')}, "
            f"양수 비율 {share_text}</li>"
        )
    return (
        "<ul class=\"score-agg-list\">" + "".join(items) + "</ul>"
        "<p><small>신규 진입 보고만 집계합니다. 통계이며 추천이 아닙니다.</small></p>"
    )


def _closed(reason: str) -> dict[str, str]:
    """값 없이도 페이지는 성립한다 — 설명이 이 페이지의 절반이기 때문이다."""
    return {
        "SUMMARY": _esc(reason),
        "ROWS": '<tr><td colspan="9" class="weekend-empty">' + _esc(reason) + "</td></tr>",
        "ASOF": "",
        "AGGREGATES": "<p>" + _esc(reason) + "</p>",
        "DISCLAIMER": "",
        "SOURCE": "",
    }


def render() -> dict[str, str]:
    """(요약, 표, 집계, 고지, 출처) — 템플릿이 그대로 끼워 넣는다."""
    try:
        payload = kr_scoring.get_board()
    except kr_scoring.KrScoringDisabled:
        return _closed("지금은 스코어보드를 표시하지 않습니다. 이 배포에서는 채점 lane이 닫혀 있습니다.")
    except DataUnavailable:
        return _closed("첫 채점 배치가 아직 돌지 않았습니다. 잠시 뒤 다시 봐 주세요.")
    except Exception:  # noqa: BLE001 - 색인용 본문 때문에 페이지가 죽으면 안 된다
        log.warning("score page SSR failed", exc_info=True)
        return _closed("지금은 값을 불러올 수 없습니다.")

    cards = [c for c in payload.get("cards") or [] if isinstance(c, dict)]
    rows = "".join(_row(card) for card in cards)
    if not rows:
        rows = ('<tr><td colspan="9" class="weekend-empty">'
                "추적 중인 공시가 아직 없습니다.</td></tr>")

    new_count = sum(1 for c in cards if c.get("is_new"))
    summary = (
        f"대량보유(5% 룰) 공시 {len(cards)}건을 추적 중입니다"
        + (f" — 그중 신규 진입 {new_count}건" if new_count else "")
        + ". 공시일 종가를 동결하고 1·3·6개월 뒤를 지수 대비로 자동 채점합니다. "
          "기록이며, 추천이 아닙니다."
    )

    as_of = f"· 기준 {_esc(payload.get('as_of'))}" if payload.get("as_of") else ""

    source = payload.get("source") or {}
    notices = [source.get("notice"), source.get("price_notice")]
    source_html = " · ".join(_esc(n) for n in notices if n)

    return {
        "SUMMARY": summary,
        "ROWS": rows,
        "ASOF": as_of,
        "AGGREGATES": _aggregates_html(payload),
        "DISCLAIMER": _esc(payload.get("basis_ko") or ""),
        "SOURCE": source_html,
    }


def json_ld() -> str:
    """schema.org FAQPage — 본문에 있는 말만 담는다(weekend와 같은 규칙)."""
    faq = [
        (
            "대량보유(5%) 공시란 무엇인가요?",
            "자본시장법의 5% 룰에 따라 상장회사 주식을 5% 이상 보유하게 되거나 1%p "
            "이상 변동이 생기면 제출하는 주식등의 대량보유 상황보고서입니다. 보고 "
            "기한이 5영업일이라 공시일은 실제 매매일보다 늦을 수 있습니다.",
        ),
        (
            "공시를 따라 사면 수익이 나나요?",
            "이 페이지는 의견이 아니라 기록으로 답합니다. 공시일 종가를 동결해 두고 "
            "1·3·6개월 뒤의 주가를 지수와 비교해 자동 채점한 결과를 그대로 보여줄 "
            "뿐, 특정 종목의 매수·매도를 권하지 않습니다. 과거의 기록은 미래를 "
            "보장하지 않습니다.",
        ),
        (
            "수익률은 어떻게 계산하나요?",
            "기준가는 공시일 이후 첫 거래일의 공식 종가로 고정하고, 일별 등락률을 "
            "이어 곱해 분할·권리락에 안전하게 계산한 뒤 같은 기간의 코스피·코스닥 "
            "지수 수익률을 빼 초과수익으로 표시합니다. 거래정지 구간은 0%가 아니라 "
            "정지로 표시합니다.",
        ),
    ]
    payload = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "@id": f"{SITE}/score",
        "url": f"{SITE}/score",
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
    return (config.STATIC_DIR / "score.html").read_text(encoding="utf-8")
