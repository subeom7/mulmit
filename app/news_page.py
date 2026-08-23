"""전용 신호 피드 `/news`.

홈의 피드 위젯은 30건짜리 요약이다. 이 페이지는 같은 레인을 길게 펴서 보여
준다. 그리고 **서버에서 렌더한다** — 이 페이지를 만드는 이유의 절반이 색인이고,
JS로 채우면 크롤러가 빈 화면을 읽는다(`/glossary`에서 같은 이유로 같은 선택을
했다).

값은 만들지 않는다. `signal_feed`가 이미 조립해 둔 항목을 배치만 한다 —
제목·시각·출처는 각 레인이 원문에서 가져온 것 그대로다.
"""

from __future__ import annotations

import html
from typing import Any

from . import config, signal_feed

SITE = "https://mulmit.com"
PAGE_ITEMS = 120

# 화면의 배지와 같은 말을 쓴다. 여기서 새로 지으면 홈 피드와 이 페이지가 같은
# 항목을 다르게 부르게 된다.
KIND_LABELS: dict[str, tuple[str, str, str]] = {
    "us_8k": ("8-K", "8-K", "us"),
    "kr_material": ("주요사항", "Material", "kr"),
    "us_ptr": ("의원거래", "Congress", "us"),
    "kr_pension": ("국민연금", "NPS", "kr"),
    "index_move": ("지수 급변", "Index move", "kr"),
    "news": ("뉴스", "News", "news"),
    "kr_press": ("보도자료", "Press", "kr"),
    "kr_holdings": ("대량보유", "5% filing", "kr"),
}
REGION_LABELS = {"kr": ("한국", "Korea"), "us": ("미국·해외", "US & Global")}


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _bilingual(ko: str, en: str) -> str:
    """같은 문자열이면 한 번만 쓴다 — 뉴스 제목은 대개 두 언어가 같다."""
    if ko == en:
        return _esc(ko)
    return f'<span class="lang-ko">{_esc(ko)}</span><span class="lang-en">{_esc(en)}</span>'


def _item_html(item: dict[str, Any]) -> str:
    kind = str(item.get("kind") or "")
    ko_label, en_label, cls = KIND_LABELS.get(kind, (kind, kind, ""))
    region = str(item.get("region") or "")
    title = item.get("title") or {}
    title_ko = str(title.get("ko") or title.get("en") or "")
    title_en = str(title.get("en") or title.get("ko") or "")

    url = str(item.get("url") or "")
    # 원문이 없으면 링크로 만들지 않는다. 빈 href는 눌리기만 하고 아무 데도
    # 가지 않아서, 링크처럼 보이는 것이 링크가 아닌 상태가 된다.
    headline = (
        f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{_bilingual(title_ko, title_en)}</a>'
        if url else f"<span>{_bilingual(title_ko, title_en)}</span>"
    )

    meta = [f'<time datetime="{_esc(item.get("at"))}">{_esc(item.get("date"))}</time>']
    if region in REGION_LABELS:
        ko_region, en_region = REGION_LABELS[region]
        meta.append(f'<span class="news-region">{_bilingual(ko_region, en_region)}</span>')
    if item.get("domain"):
        meta.append(f'<span class="news-domain">{_esc(item["domain"])}</span>')

    hub = item.get("hub")
    if hub and item.get("symbol"):
        meta.append(f'<a class="news-hub" href="{_esc(hub)}">{_esc(item["symbol"])}</a>')

    return (
        f'<li class="news-row" data-kind="{_esc(kind)}" data-region="{_esc(region)}">'
        f'<span class="feed-kind {_esc(cls)}">{_bilingual(ko_label, en_label)}</span>'
        f'<div class="news-body"><p class="news-title">{headline}</p>'
        f'<p class="news-meta">{"".join(meta)}</p></div>'
        f"</li>"
    )


def _filter_html(counts: dict[str, int]) -> str:
    """분류 칩. 실제로 항목이 있는 종류만 낸다 — 눌러도 빈 목록이 되는 칩은 두지 않는다."""
    chips = [
        '<button type="button" class="active" data-news-kind="all">'
        '<span class="lang-ko">전체</span><span class="lang-en">All</span>'
        f' <b>{sum(counts.values())}</b></button>'
    ]
    for kind, count in sorted(counts.items(), key=lambda row: -row[1]):
        ko_label, en_label, _cls = KIND_LABELS.get(kind, (kind, kind, ""))
        chips.append(
            f'<button type="button" data-news-kind="{_esc(kind)}">'
            f"{_bilingual(ko_label, en_label)} <b>{count}</b></button>"
        )
    return "".join(chips)


def render() -> dict[str, str]:
    """(필터, 항목, 근거, 출처 표기) — 템플릿이 그대로 끼워 넣는다."""
    # 이 페이지는 기록을 다 보여 주는 곳이라 홈의 7일 문을 통과하지 않는다.
    payload = signal_feed.build_feed(limit=PAGE_ITEMS, max_age_days=None)
    items = [item for item in payload.get("items") or [] if isinstance(item, dict)]

    counts: dict[str, int] = {}
    for item in items:
        kind = str(item.get("kind") or "")
        if kind:
            counts[kind] = counts.get(kind, 0) + 1

    if items:
        body = "".join(_item_html(item) for item in items)
    else:
        # 레인이 전부 비어 있을 수 있다(수집 전, 게이트 닫힘). 그때는 빈 목록을
        # 그대로 보여 준다 — 없는 항목을 지어내지 않는다.
        body = (
            '<li class="news-empty">'
            '<span class="lang-ko">아직 모인 항목이 없습니다.</span>'
            '<span class="lang-en">Nothing collected yet.</span></li>'
        )

    attribution = payload.get("attribution") or {}
    source_html = ""
    if attribution.get("url"):
        source_html = (
            f'<a href="{_esc(attribution["url"])}" target="_blank" rel="noopener noreferrer">'
            f'<span class="lang-ko">{_esc(attribution.get("text_ko") or attribution.get("text"))}</span>'
            f'<span class="lang-en">{_esc(attribution.get("text"))}</span></a>'
        )

    return {
        "FILTERS": _filter_html(counts),
        "ITEMS": body,
        "BASIS": (
            f'<span class="lang-ko">{_esc(payload.get("basis_ko"))}</span>'
            f'<span class="lang-en">{_esc(payload.get("basis_en") or payload.get("basis_ko"))}</span>'
        ),
        "SOURCE": source_html,
        "COUNT": str(len(items)),
    }


def json_ld() -> str:
    """schema.org CollectionPage. 항목은 싣지 않는다 — 원문이 남의 것이다."""
    import json

    payload = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "@id": f"{SITE}/news",
        "url": f"{SITE}/news",
        "name": "지금 일어나는 일 — 공시·일정·뉴스",
        "inLanguage": "ko",
        "isPartOf": {"@type": "WebSite", "name": "Mulmit", "url": SITE},
    }
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def template() -> str:
    return (config.STATIC_DIR / "news.html").read_text(encoding="utf-8")
