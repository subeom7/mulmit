"""GDELT 뉴스 헤드라인 lane — "연관 종목 등락 태그"가 붙는 글로벌 뉴스.

표시는 우리 안전선 그대로다: **제목 + 출처 도메인 + 원문 링크**까지. 본문·요약
재게시는 없다(GDELT가 본문을 주지도 않는다). 종목 태그는 제목과 닫힌 이름
사전의 단어 경계 매칭으로만 붙이고, 태그의 등락률은 뉴스 벤더가 아니라 **우리
데이터**에서 온다 — 국내 코드는 금융위 로스터의 전일 확정 등락률(flt_rt),
미국 티커는 가격 lane이 없으므로 링크만.

수집은 ingest 배치 전용(쿼리 2개, 6초 간격)이고 web은 저장 블롭만 읽는다.
GDELT 약관의 조건(인용+링크)은 payload의 attribution으로 항상 동반한다.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from . import config, store
from .providers.gdelt import (
    GDELT_ATTRIBUTION,
    GDELT_ATTRIBUTION_KO,
    GDELT_PROVIDER_ID,
    GDELT_PUBLISHER,
    GDELT_PUBLISHER_URL,
    GDELT_TERMS_URL,
    GdeltProvider,
)

log = logging.getLogger(__name__)

CACHE_KEY = "gdelt_news_v1"
MAX_ARTICLES = 40

# GKG 15분 파일에서 제목으로 거르는 키워드 — 시장 축 + 한국 노출 축.
# 여기 걸리거나 종목 사전에 매칭되는 제목만 남는다.
TITLE_KEYWORDS = (
    "federal reserve", "s&p 500", "nasdaq", "inflation", "interest rate",
    "stock market", "wall street", "treasury yield",
    "samsung", "sk hynix", "bank of korea", "kospi", "korea",
    # 지정학·제재·거시 축 (등록부 §6.1 2026-08-20 — 텔레그램 스쿽 기각의 합법
    # 대체). 부분 문자열 매칭이므로 짧은 일반어("oil", "won")는 넣지 않는다.
    "sanction", "embargo", "tariff", "trade deal", "trade war", "opec",
    "crude oil", "oil price", "rate cut", "rate hike", "recession",
    "central bank", "ecb", "fomc", "gdp", "geopolitic", "iran",
)

# 닫힌 이름 사전 — 제목의 단어 경계 매칭으로만 태깅한다. 여기 없는 회사는
# 태그가 없을 뿐이다(오태깅보다 무태깅이 낫다). KR 값은 종목코드, US는 티커.
TICKER_NAMES: tuple[tuple[str, str, bool], ...] = (
    ("Samsung Electronics", "005930", True),
    ("SK Hynix", "000660", True),
    ("Hyundai Motor", "005380", True),
    ("Apple", "AAPL", False),
    ("Nvidia", "NVDA", False),
    ("Microsoft", "MSFT", False),
    ("Alphabet", "GOOGL", False),
    ("Google", "GOOGL", False),
    ("Amazon", "AMZN", False),
    ("Meta Platforms", "META", False),
    ("Tesla", "TSLA", False),
    ("Netflix", "NFLX", False),
    ("Broadcom", "AVGO", False),
    ("Intel", "INTC", False),
    ("AMD", "AMD", False),
    ("Micron", "MU", False),
    ("Qualcomm", "QCOM", False),
    ("Palantir", "PLTR", False),
    ("Coinbase", "COIN", False),
    ("JPMorgan", "JPM", False),
    ("Goldman Sachs", "GS", False),
    ("Boeing", "BA", False),
    ("Disney", "DIS", False),
)

_PATTERNS = tuple(
    (re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE), symbol, korean)
    for name, symbol, korean in TICKER_NAMES
)


class NewsFeedDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    if not config.GDELT_ENABLED:
        raise NewsFeedDisabled("disabled")


def _tags_for(title: str) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern, symbol, korean in _PATTERNS:
        if symbol in seen or not pattern.search(title):
            continue
        seen.add(symbol)
        tag: dict[str, Any] = {"symbol": symbol, "hub": f"/stock/{symbol}"}
        if korean:
            listing = store.get_kr_listing(symbol)
            if listing is not None:
                change = listing.get("flt_rt")
                if change is not None:
                    tag["change_percent"] = float(change)
                    tag["change_basis"] = "t1_close"  # 전일 확정 종가 기준
                tag["name"] = listing.get("itms_nm")
        tags.append(tag)
    return tags


def refresh(provider: GdeltProvider | None = None) -> dict:
    """쿼리들을 걷어 URL 중복 제거·최신순 병합으로 블롭을 갈아끼운다."""
    _require_lane()
    provider = provider or GdeltProvider(
        timeout=config.GDELT_TIMEOUT, retries=config.GDELT_RETRIES
    )

    previous = store.load_report(CACHE_KEY, config.REPORT_TTL * 2) or {}
    by_url: dict[str, dict[str, Any]] = {
        article["url"]: article for article in previous.get("articles", [])
    }
    # 벌크 채널: 15분 GKG 파일 하나에서 제목을 뽑아 키워드·종목 사전으로 거른다.
    # (DOC API는 AWS IP에서 지속 차단 — 등록부 §6.1, GDELT의 벌크 전환 권고 준수)
    fetched = 0
    for article in provider.fetch_latest_gkg_titles():
        title_lower = article["title"].lower()
        tags = _tags_for(article["title"])
        if not tags and not any(keyword in title_lower for keyword in TITLE_KEYWORDS):
            continue
        fetched += 1
        by_url[article["url"]] = {**article, "tags": tags}

    # 폴리시: 같은 제목이 여러 매체에 실리면 한 행으로 접고 매체 수를 남긴다.
    by_title: dict[str, dict[str, Any]] = {}
    for article in sorted(by_url.values(), key=lambda a: a["seendate"], reverse=True):
        key = re.sub(r"\s+", " ", article["title"].casefold()).strip()
        kept = by_title.get(key)
        if kept is None:
            by_title[key] = {**article, "also_on": 0}
        else:
            kept["also_on"] = int(kept.get("also_on", 0)) + 1
    merged = list(by_title.values())[:MAX_ARTICLES]
    payload = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "articles": merged,
        "count": len(merged),
        "basis_ko": (
            "GDELT가 수집한 글로벌 기사 메타데이터(제목·출처·링크)입니다. 본문은 "
            "전달하지 않으며, 내용 판단은 원문 링크의 몫입니다. 종목 태그는 제목의 "
            "닫힌 이름 매칭이고, 태그의 등락률은 뉴스가 아니라 금융위 전일 확정 "
            "종가 기준입니다. 수집 주기 갱신 — 실시간 속보가 아닙니다."
        ),
        "basis_en": (
            "Global article metadata (title, source, link) collected by GDELT. No "
            "article bodies are relayed; read the source for substance. Ticker tags "
            "come from closed name matching on titles, and their move percentages "
            "are our own T+1 official-close data, not the news vendor's. Refreshed "
            "on the collection cycle — not a live wire."
        ),
        "attribution": {
            "required": True,
            "text": GDELT_ATTRIBUTION,
            "text_ko": GDELT_ATTRIBUTION_KO,
            "url": GDELT_PUBLISHER_URL,
        },
        "source": {
            "provider": GDELT_PROVIDER_ID,
            "publisher": GDELT_PUBLISHER,
            "publisher_url": GDELT_PUBLISHER_URL,
            "terms_url": GDELT_TERMS_URL,
        },
        "rights": {"status": "approved", "notice": GDELT_ATTRIBUTION},
    }
    store.save_report(CACHE_KEY, payload)
    return {"fetched": fetched, "kept": len(merged)}


def get_news() -> dict:
    """저장된 결과만 읽는다. 요청 경로에서 GDELT를 호출하지 않는다."""
    _require_lane()
    from .providers.base import DataUnavailable

    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("news headlines not collected yet")
    return cached
