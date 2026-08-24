"""코인 상세의 서버 렌더 본문.

`/stock/{code}`에서 한 것과 같은 이유다. 크롤러가 받아 가는 본문이 **677자**였고
(2026-08-24 실측), 값은 전부 자바스크립트가 나중에 채웠다. 게다가 코인 페이지는
사이트맵에 **아예 없었다** — 구글이 존재를 모르는 상태였다.

종목 페이지와 다른 점이 하나 있다. 코인은 10개뿐이라 유입의 크기는 작지만,
비트코인·이더리움은 검색량이 큰 키워드다. 페이지 수가 아니라 키워드의 무게로
값이 정해지는 쪽이다.

**요청 경로에서 상류를 부르지 않는다.** 저장된 것만 읽는다 — 하이퍼리퀴드 일별
이력 블롭과 저장된 청산 집계. 없으면 그 조각을 뺀다.
"""

from __future__ import annotations

import html
import logging
from typing import Any

log = logging.getLogger(__name__)

HISTORY_DAYS = 90


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _usd(value: Any, *, digits: int = 2) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "—"
    if parsed != parsed:
        return "—"
    if abs(parsed) >= 1_000_000:
        return f"${parsed / 1_000_000:,.1f}M"
    return f"${parsed:,.{digits}f}"


def _rows_table(caption: str, rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    body = "".join(
        f"<tr><td>{_esc(label)}</td><td>{value}</td></tr>" for label, value in rows
    )
    return (
        f'<section class="ssr-block"><h2>{_esc(caption)}</h2>'
        f'<table class="stock-table"><thead><tr><th>항목</th><th>값</th></tr></thead>'
        f"<tbody>{body}</tbody></table></section>"
    )


def render(symbol: str, *, label: str = "") -> str:
    """크롤러가 읽을 본문. 실패는 빈 문자열이지 500이 아니다."""
    try:
        return _body(symbol, label)
    except Exception:  # noqa: BLE001 - 색인용 본문 때문에 페이지가 죽으면 안 된다
        log.warning("crypto coin page SSR failed for %s", symbol, exc_info=True)
        return ""


def _body(symbol: str, label: str) -> str:
    from . import crypto_liquidations, hip3_history, store

    parts: list[str] = []
    name = label or symbol

    # 일별 종가 — 저장된 블롭에서만 읽는다. 이 경로는 상류를 부르지 않는다.
    try:
        blob = hip3_history.load()
        rows, _available = hip3_history.observations_for(
            blob, symbol, days=HISTORY_DAYS, limit=HISTORY_DAYS
        )
    except Exception:  # noqa: BLE001
        rows = []
    values = [float(row["value"]) for row in rows if row.get("value") is not None]
    if values:
        parts.append(_rows_table(f"{name} 최근 {HISTORY_DAYS}일", [
            ("마지막 종가", _esc(_usd(values[-1]))),
            ("기간 최고", _esc(_usd(max(values)))),
            ("기간 최저", _esc(_usd(min(values)))),
            ("관측 일수", _esc(str(len(values)))),
        ]))

    # 청산 집계 — ingest가 저장해 둔 것만.
    try:
        # 서빙 경로와 같은 TTL. `None`을 넘기면 store가 터지고 except가 삼켜서
        # 블록이 조용히 사라진다.
        payload = store.load_report(
            crypto_liquidations.CACHE_KEY, crypto_liquidations.CACHE_TTL
        ) or {}
        coin = next(
            (row for row in (payload.get("coins") or [])
             if str(row.get("symbol") or "").upper() == symbol.upper()),
            None,
        )
    except Exception:  # noqa: BLE001
        coin = None
    if coin:
        liquidations = coin.get("liquidations") or {}
        interest = coin.get("open_interest") or {}
        window = liquidations.get("window_hours")
        parts.append(_rows_table(f"{name} 청산·미결제약정", [
            (f"청산 롱 ({window}시간)", _esc(_usd(liquidations.get("long_usd")))),
            (f"청산 숏 ({window}시간)", _esc(_usd(liquidations.get("short_usd")))),
            ("청산 합계", _esc(_usd(liquidations.get("total_usd")))),
            ("미결제약정", _esc(_usd(interest.get("usd")))),
        ]))

    if not parts:
        return ""
    # 값이 무엇인지 밝히지 않으면 현물 가격으로 읽힌다.
    parts.append(
        '<p class="ssr-note">하이퍼리퀴드 무기한선물 기준값이며 현물 거래소 가격이 '
        "아닙니다. 청산·미결제약정은 Coinalyze 집계이고 틱 피드가 아닙니다.</p>"
    )
    return "".join(parts)
