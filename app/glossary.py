"""용어 사전 — `/glossary`.

화면 곳곳의 용어 팝오버와 **같은 파일**(`static/terms.json`)을 읽는다. 사전이
두 벌이 되면 같은 말이 화면마다 다르게 설명되기 때문이다. 팝오버는 클릭한
용어 하나를, 이 페이지는 전부를 보여준다.

서버에서 렌더한다. 이 페이지의 존재 이유가 "펀딩비 뜻" 같은 검색 유입인데,
JS로 채우면 크롤러가 읽지 못해 만드는 의미가 없다.
"""

from __future__ import annotations

import html
import json
from functools import lru_cache
from typing import Any

from . import config

SITE = "https://mulmit.com"


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    path = config.STATIC_DIR / "terms.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def grouped_terms() -> list[tuple[str, dict[str, str], list[tuple[str, dict[str, Any]]]]]:
    """(묶음 id, 묶음 라벨, [(용어 id, 용어)]) — terms.json에 적힌 순서 그대로.

    사전 파일의 순서가 곧 화면의 순서다. 알파벳순으로 다시 정렬하지 않는다 —
    같은 갈래의 용어가 이어서 나오도록 손으로 배열해 둔 것이기 때문이다.
    """
    data = _load()
    labels = data.get("groups", {})
    buckets: dict[str, list[tuple[str, dict[str, Any]]]] = {key: [] for key in labels}
    for term_id, entry in data.get("terms", {}).items():
        buckets.setdefault(entry.get("group", "etc"), []).append((term_id, entry))
    return [
        (group_id, labels.get(group_id, {"ko": group_id, "en": group_id}), terms)
        for group_id, terms in buckets.items()
        if terms
    ]


def _entry_html(term_id: str, entry: dict[str, Any]) -> str:
    """한 용어. KO/EN을 함께 담고 CSS가 고른다 — 스크립트 없이도 읽힌다."""
    blocks = []
    for lang, read_label, caution_label in (
        ("ko", "어떻게 읽나", "흔한 오해"),
        ("en", "How to read it", "Common mistake"),
    ):
        text = entry.get(lang) or {}
        rows = "".join(
            f"<dt>{_esc(label)}</dt><dd>{_esc(text.get(field))}</dd>"
            for label, field in ((read_label, "read"), (caution_label, "caution"))
            if text.get(field)
        )
        blocks.append(
            f'<div class="lang-{lang}">'
            f"<h3>{_esc(text.get('title', term_id))}</h3>"
            f'<p class="term-def">{_esc(text.get("def"))}</p>'
            f"<dl>{rows}</dl>"
            f"</div>"
        )
    body = "".join(blocks)
    return (
        f'<article class="term-entry" id="{_esc(term_id)}">{body}'
        f'<a class="term-anchor" href="#{_esc(term_id)}" aria-label="{_esc(term_id)}">#</a>'
        f"</article>"
    )


def terms_html() -> str:
    sections = []
    for group_id, label, terms in grouped_terms():
        entries = "".join(_entry_html(term_id, entry) for term_id, entry in terms)
        title = (
            f'<span class="lang-ko">{_esc(label.get("ko", group_id))}</span>'
            f'<span class="lang-en">{_esc(label.get("en", group_id))}</span>'
        )
        sections.append(
            f'<section class="console-section glossary-group" id="group-{_esc(group_id)}"'
            f' aria-labelledby="group-{_esc(group_id)}-title">'
            f'<header><h2 id="group-{_esc(group_id)}-title">{title}</h2></header>'
            f'<div class="term-list">{entries}</div>'
            f"</section>"
        )
    return "".join(sections)


def index_html() -> str:
    """맨 위 목차. 긴 페이지에서 원하는 용어로 바로 내려가게 한다."""
    chips = []
    for _group_id, _label, terms in grouped_terms():
        for term_id, entry in terms:
            for lang in ("ko", "en"):
                title = (entry.get(lang) or {}).get("title", term_id)
                chips.append(
                    f'<a class="glossary-chip lang-{lang}" href="#{_esc(term_id)}">{_esc(title)}</a>'
                )
    return "".join(chips)


def json_ld() -> str:
    """schema.org DefinedTermSet.

    한국어만 싣는다 — 이 문서의 canonical 언어가 한국어이고, 한 URL에 두 언어의
    정의를 같은 이름으로 넣으면 무엇이 이 용어의 정의인지 흐려진다.
    """
    data = _load()
    terms = []
    for term_id, entry in data.get("terms", {}).items():
        text = entry.get("ko") or {}
        if not text.get("def"):
            continue
        terms.append(
            {
                "@type": "DefinedTerm",
                "@id": f"{SITE}/glossary#{term_id}",
                "name": text.get("title", term_id),
                "description": text["def"],
                "termCode": term_id,
                "url": f"{SITE}/glossary#{term_id}",
            }
        )
    payload = {
        "@context": "https://schema.org",
        "@type": "DefinedTermSet",
        "@id": f"{SITE}/glossary",
        "name": "물밑 용어 사전",
        "url": f"{SITE}/glossary",
        "inLanguage": "ko",
        "hasDefinedTerm": terms,
    }
    # `</script>`가 문자열 안에 들어가 태그를 닫아 버리는 일만 막으면 된다.
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def term_count() -> int:
    return len(_load().get("terms", {}))
