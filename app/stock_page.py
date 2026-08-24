"""종목 허브의 서버 렌더 본문.

이 페이지를 만드는 이유의 절반이 색인이다. 사이트맵에 3,000여 개의 종목 URL을
올려 두었는데, 크롤러가 받아 가는 본문이 **214자**였다(2026-08-24 실측). 값은
전부 자바스크립트가 나중에 채우기 때문이다. 구글이 JS를 렌더하긴 하지만 대기열이
길고, 거의 똑같은 214자 껍데기 3,000개는 "크롤링됨 — 색인 생성되지 않음"으로
빠지는 전형적인 모양이다. `/news`와 `/glossary`에서 같은 이유로 같은 선택을 했다.

**요청 경로에서 상류를 부르지 않는다.** 저장된 것만 읽고, 없으면 그 조각을
빼고 나머지를 낸다. 크롤러 한 번에 DART·SEC를 두드리면 3,000페이지가 3,000번의
외부 호출이 된다. 값이 아직 안 모인 종목은 껍데기 그대로 나가고, 그건 지금과
같은 상태이니 나빠지지 않는다.

**값은 만들지 않는다.** 여기서 계산하는 것은 없다. 각 lane이 이미 조립해 둔
것을 배치만 한다 — 화면의 JS가 나중에 같은 값으로 다시 그린다.
"""

from __future__ import annotations

import html
import logging
from typing import Any

log = logging.getLogger(__name__)

MAX_ROWS = 12


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _number(value: Any) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "—"
    if parsed != parsed:  # NaN
        return "—"
    return f"{parsed:,.0f}" if abs(parsed) >= 1000 else f"{parsed:,.2f}".rstrip("0").rstrip(".")


def _table(caption: str, headers: list[str], rows: list[list[str]]) -> str:
    """크롤러가 읽는 표. 화면의 JS가 같은 자리를 다시 그리므로 구조만 맞춘다."""
    if not rows:
        return ""
    head = "".join(f"<th>{_esc(text)}</th>" for text in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        f'<section class="ssr-block"><h2>{_esc(caption)}</h2>'
        f'<table class="stock-table"><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></section>"
    )


def _link(text: Any, url: Any) -> str:
    """원문 링크. url이 없으면 링크로 만들지 않는다."""
    label = _esc(text)
    if not url:
        return label
    return f'<a href="{_esc(url)}" rel="noopener noreferrer">{label}</a>'


def _kr_body(code: str) -> str:
    from . import config, kr_events, kr_fundamentals, kr_insider, kr_pension, kr_stocks, store

    parts: list[str] = []

    # 시세 통계 — 저장된 종가만. 미수집 종목을 여기서 수집하지 않는다.
    try:
        analysis = kr_stocks.get_analysis(code)
    except Exception:  # noqa: BLE001 - 조각 하나의 실패가 페이지를 죽이지 않는다
        analysis = None
    if analysis:
        latest = analysis.get("latest") or {}
        mdd = analysis.get("mdd") or {}
        rows = [
            ["공식 종가", f'{_number(latest.get("value"))} ({_esc(latest.get("date"))})'],
            ["52주 범위", f'{_number(analysis.get("low_52w"))} ~ {_number(analysis.get("high_52w"))}'],
            ["전고점 대비", f'{_number(analysis.get("drawdown_current"))}%'],
            ["최대 낙폭", f'{_number(mdd.get("value"))}% ({_esc(mdd.get("trough_date"))})'],
            ["연 변동성", f'{_number(analysis.get("volatility_1y"))}%'],
        ]
        parts.append(_table("시세 요약", ["항목", "값"], [[_esc(a), b] for a, b in rows]))

    # 연간 재무제표
    try:
        fundamentals = kr_fundamentals.get_report(code)
    except Exception:  # noqa: BLE001
        fundamentals = None
    if fundamentals:
        rows = [
            [
                _link(row.get("year"), row.get("report_url")),
                _esc(_number(row.get("revenue"))),
                _esc(_number(row.get("operating_income"))),
                _esc(_number(row.get("net_income"))),
                _esc(f'{_number(row.get("roe"))}%'),
            ]
            for row in (fundamentals.get("annual") or [])[:6]
        ]
        parts.append(
            _table("연간 재무제표", ["연도", "매출", "영업이익", "순이익", "ROE"], rows)
        )

    # 임원·주요주주 소유보고 — 저장된 것만
    try:
        reports = (kr_insider.get_reports(code) or {}).get("reports") or []
    except Exception:  # noqa: BLE001
        reports = []
    rows = [
        [
            _link(row.get("report_date"), row.get("report_url")),
            _esc(row.get("reporter")),
            _esc(row.get("position") or row.get("main_shareholder")),
            _esc(_number(row.get("shares_owned"))),
        ]
        for row in reports[:MAX_ROWS]
    ]
    parts.append(_table("임원·주요주주 소유보고", ["보고일", "보고자", "직위·관계", "소유수량"], rows))

    # 주요사항보고 · 국민연금 5% — 저장된 피드에서 이 종목만
    for label, module, key, columns in (
        ("주요사항보고", kr_events, "events", ("filed_at", "report_name", "url")),
        ("국민연금 5% 공시", kr_pension, "filings", ("report_date", "reason", "report_url")),
    ):
        try:
            # TTL은 서빙 경로와 같은 값을 쓴다. 서빙하기에 낡은 것은 색인에 넣기에도
            # 낡은 것이고, 무엇보다 `None`을 넘기면 store가 float와 None을 비교하다
            # 터진다 — 아래 except가 삼켜서 블록이 조용히 사라진다(2026-08-24 실측).
            stored = store.load_report(module.CACHE_KEY, config.REPORT_TTL * 2) or {}
            items = [
                item for item in (stored.get(key) or []) if item.get("stock_code") == code
            ]
        except Exception:  # noqa: BLE001
            items = []
        date_field, text_field, url_field = columns
        rows = [
            [_link(item.get(date_field), item.get(url_field)), _esc(item.get(text_field))]
            for item in items[:8]
        ]
        parts.append(_table(label, ["날짜", "내용"], rows))

    return "".join(parts)


def _us_body(ticker: str) -> str:
    from . import insider_filings, us_events, us_fundamentals, us_ptr

    parts: list[str] = []

    try:
        fundamentals = us_fundamentals.build_report(ticker)
    except Exception:  # noqa: BLE001
        fundamentals = None
    if fundamentals:
        rows = [
            [
                _esc(row.get("end")),
                _esc(_number(row.get("revenue"))),
                _esc(_number(row.get("operating_income"))),
                _esc(_number(row.get("net_income"))),
                _esc(_number(row.get("eps_diluted"))),
            ]
            for row in (fundamentals.get("annual") or [])[:6]
        ]
        parts.append(
            _table("Annual financials", ["Period", "Revenue", "Operating income", "Net income", "EPS"], rows)
        )

    try:
        payload = insider_filings.build_insider_report(ticker, limit=MAX_ROWS)
        transactions = payload.get("transactions") or []
    except Exception:  # noqa: BLE001
        transactions = []
    rows = []
    for row in transactions[:MAX_ROWS]:
        owner = row.get("owner") or {}
        rows.append([
            _link(row.get("transaction_date") or row.get("filing_date"), row.get("filing_url")),
            _esc(owner.get("name")),
            _esc(owner.get("title")),
            _esc(_number(row.get("shares"))),
        ])
    parts.append(_table("Insider filings (Forms 3/4/5)", ["Date", "Owner", "Title", "Shares"], rows))

    try:
        events = (us_events.build_events_feed(ticker=ticker) or {}).get("events") or []
    except Exception:  # noqa: BLE001
        events = []
    rows = [
        [
            _link(event.get("filed_at"), event.get("url")),
            _esc(" · ".join(item.get("label", {}).get("en", "") for item in (event.get("items") or []))),
        ]
        for event in events[:8]
    ]
    parts.append(_table("8-K events", ["Filed", "Items"], rows))

    try:
        filings = (us_ptr.get_filings(ticker=ticker) or {}).get("filings") or []
    except Exception:  # noqa: BLE001
        filings = []
    rows = [
        [_link(filing.get("name"), filing.get("pdf_url")), _esc(filing.get("filed_date"))]
        for filing in filings[:8]
    ]
    parts.append(_table("Congressional trades (PTR)", ["Member", "Filed"], rows))

    return "".join(parts)


def render(symbol: str, *, korean: bool) -> str:
    """크롤러가 읽을 본문. 실패는 빈 문자열이지 500이 아니다.

    이 블록은 화면에서 보이지 않는다 — JS가 같은 값을 자기 자리에 다시 그리고,
    이쪽은 `hidden`으로 접힌다. 숨긴다고 색인에서 빠지지는 않는다: 구글은
    `display:none` 안의 텍스트도 읽되 가중치를 낮출 뿐이고, 지금 문제는 가중치가
    아니라 **읽을 것이 214자뿐**이라는 것이다.
    """
    try:
        return _kr_body(symbol) if korean else _us_body(symbol)
    except Exception:  # noqa: BLE001 - 색인용 본문 때문에 페이지가 죽으면 안 된다
        log.warning("stock page SSR failed for %s", symbol, exc_info=True)
        return ""
