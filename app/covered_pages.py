"""지금 볼 것이 있는 페이지 목록 — 사이트맵과 크롤 경로가 같은 목록을 쓴다.

**왜 한 군데에 모으는가.** 사이트맵과 화면의 목록이 갈라지면, 구글에는 있다고
말해 놓고 사이트 안에는 그리로 가는 길이 없는 상태가 된다. 2026-08-25에 실제로
그랬다 — 사이트맵에 405개를 올려 두고, 크롤러가 링크로 닿을 수 있는 종목
페이지는 42개였다.

**그게 왜 문제인가.** 구글 Search Console이 그날 이렇게 말했다:

    Discovered — currently not indexed   2,954
    Crawled — currently not indexed          2
    Indexed                                  5

"Discovered"는 **찾았지만 한 번도 가져가지 않았다**는 뜻이다. 얇아서 버린 게
아니라 아예 안 읽었다. 사이트맵에만 있는 URL은 크롤 우선순위가 가장 낮고, 새
도메인은 크롤 예산 자체가 적다. 페이지를 두껍게 만든 것(서버 렌더)은 필요한
일이었지만 **그것만으로는 읽히지도 않는다** — 먼저 길이 있어야 한다.

그래서 `/analytics`가 이 목록을 그대로 렌더한다. 홈에서 한 번, 거기서 한 번 —
두 걸음이면 모든 종목 페이지에 링크로 닿는다.
"""

from __future__ import annotations

from typing import Any

SITE = "https://mulmit.com"


def _kr() -> list[tuple[str, str]]:
    from . import store

    with_data = set(store.list_kr_codes_with_series())
    return [
        (code, name or code)
        for code, name in store.list_kr_codes()
        if code in with_data
    ]


def _us() -> list[tuple[str, str]]:
    from . import store

    return [
        (str(row["ticker"]), str(row.get("name") or row["ticker"]))
        for row in store.list_insider_companies(status="ok")
    ]


def _coins() -> list[tuple[str, str]]:
    from . import crypto_coin, data_rights

    if not data_rights.crypto_section_enabled():
        return []
    out: list[tuple[str, str]] = []
    for symbol in crypto_coin.curated_symbols():
        try:
            spec = crypto_coin.coin_spec(symbol)
            out.append((symbol, spec.label_ko or symbol))
        except Exception:  # noqa: BLE001 - 이름이 없어도 링크는 살린다
            out.append((symbol, symbol))
    return out


def groups() -> list[dict[str, Any]]:
    """(제목, 경로 접두, 항목들). 사이트맵과 `/analytics`가 같은 것을 읽는다."""
    return [
        {"key": "kr", "ko": "국내 종목", "en": "Korean stocks", "prefix": "/stock/", "items": _kr()},
        {"key": "us", "ko": "미국 종목", "en": "US stocks", "prefix": "/stock/", "items": _us()},
        {"key": "coin", "ko": "암호화폐", "en": "Crypto", "prefix": "/crypto/", "items": _coins()},
    ]


def urls() -> list[str]:
    """사이트맵용 절대 URL."""
    return [
        f"{SITE}{group['prefix']}{symbol}"
        for group in groups()
        for symbol, _name in group["items"]
    ]


def render_index(*, max_per_group: int | None = None) -> str:
    """`/analytics`가 싣는 목록. 크롤러가 따라갈 수 있는 평범한 `<a>`들이다.

    자바스크립트로 그리면 아무 소용이 없다 — 크롤러가 링크를 못 보면 길이 없는
    것과 같고, 길이 없는 것이 지금 문제다.
    """
    import html

    parts: list[str] = []
    for group in groups():
        items = group["items"]
        if not items:
            continue
        if max_per_group is not None:
            items = items[:max_per_group]
        links = "".join(
            '<li><a href="{}{}">{}<span class="covered-sym">{}</span></a></li>'.format(
                group["prefix"],
                html.escape(symbol, quote=True),
                html.escape(name),
                html.escape(symbol),
            )
            for symbol, name in items
        )
        parts.append(
            '<section class="covered-group">'
            f'<h3><span class="lang-ko">{html.escape(group["ko"])}</span>'
            f'<span class="lang-en">{html.escape(group["en"])}</span>'
            f' <b>{len(items)}</b></h3>'
            f'<ul class="covered-list">{links}</ul></section>'
        )
    return "".join(parts)


def render_examples(limit: int = 6) -> str:
    """찾기 상자 아래의 예시 칩.

    손으로 적어 두면 수집이 안 된 종목을 가리킬 수 있다 — 사람에게는 그럭저럭
    이지만 크롤러에게는 빈 페이지로 가는 길이다. 실제로 값이 있는 것에서 뽑는다.
    """
    import html

    picks: list[tuple[str, str, str]] = []
    for group in groups():
        for symbol, name in group["items"][: max(1, limit // 3)]:
            picks.append((group["prefix"], symbol, name))
    return "".join(
        f'<a href="{prefix}{html.escape(symbol, quote=True)}">{html.escape(name)}</a>'
        for prefix, symbol, name in picks[:limit]
    )
