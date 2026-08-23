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
    # 크립토 축 — 이 키워드가 없으면 크립토 헤드라인은 필터를 통과하지 못한다
    # (2026-08-22 실측: 저장된 뉴스 8건 중 크립토 0건).
    "bitcoin", "ethereum", "crypto", "stablecoin", "altcoin", "digital asset",
)

# 키워드는 **단어 경계**로 본다. 부분 문자열이던 시절 "iran"이 인도 정치인
# 이름 "Smriti Irani"를 잡아 국내 정치 기사를 시장 화면에 올렸다(실측
# 2026-08-24). 진짜 이란 기사는 그대로 통과한다.
#
# 경계만 두면 이번엔 복수형을 놓친다 — "tariff"가 "tariffs"를 못 잡아 관세
# 기사가 통째로 빠졌다. 그래서 흔한 어미만 허용한다. "Irani"는 여전히
# 걸리지 않는다("i"는 이 어미 목록에 없다).
_KEYWORD_PATTERNS = tuple(
    re.compile(rf"\b{re.escape(keyword)}(?:s|es|ed|ing|al|als)?\b", re.I)
    for keyword in TITLE_KEYWORDS
)

# 템플릿으로 찍어 내는 종목 기사. MarketBeat 계열 도메인이 수십 개라 도메인
# 목록보다 **제목 틀**이 오래간다. 실측 2026-08-24: 저장된 40건 중 7건이
# 이것이었고, 같은 배당 공시가 동사만 바꿔 세 번 실려 있었다("Declares" /
# "to Issue" / "Plans").
_GENERATED_TITLE = tuple(re.compile(pattern, re.I) for pattern in (
    r"^(critical\s+(review|contrast|comparison)|financial\s+(analysis|review|survey|comparison)|reviewing|comparing|contrasting|head[- ]to[- ]head)\b",
    r"\b(declares|to issue|plans|announces)\s+(a\s+)?(quarterly\s+)?dividend\s+of\s+\$",
    r"\bshort interest (update|down|up)\b",
    r"\b(shares|stake|position)\s+(sold|bought|acquired|purchased|raised|lowered|boosted|trimmed)\s+by\b",
    r"\bvs\.\s",
    r"\bhead to head (survey|contrast|review)\b",
))

# 회사 이름이 제목에 있다는 이유로 붙은 태그가, 시장과 무관한 기사를 시장
# 화면에 올린다. 실측: "Netflix's Outer Banks Finale Shatters An IMDb Series
# Record"[NFLX], "Disney Plus Fall 2026 Schedule"[DIS], "Amazon early Labor Day
# deals"[AMZN]. 태그를 느슨하게 두는 대신 여기서 명백한 것만 걷어 낸다 —
# 무태깅이 오태깅보다 낫다는 이 lane의 원칙과 같은 방향이다.
_OFF_TOPIC = tuple(re.compile(pattern, re.I) for pattern in (
    r"\b(season|episode|finale|cast|trailer|spoilers?|streaming guide)\b",
    r"\b(tv shows?|movies?|series)\s+(coming|premiere|release|schedule)",
    r"\bimdb\b",
    r"\b(labor day|black friday|prime day|cyber monday)\s+deals?\b",
    r"\bdeals on\b",
    r"\bbox office\b",
    r"\b(esports|worlds \d{4}|league of legends)\b",
))


# 태그 하나로는 기사를 들여보내지 않는다.
#
# 회사 이름이 제목에 있으면 태그가 붙는데, 그것만으로 통과시키면 연예·잡학
# 기사가 종목 뉴스로 둔갑한다(실측 2026-08-24: "Alfonso Herrera leads Netflix
# Action Thriller"[NFLX], "An ultra-rare piece of Microsoft history could be
# hiding on your shelf"[MSFT]).
#
# 그렇다고 거시 키워드를 요구하면 정작 필요한 것이 빠진다 — "Tesla recalls
# nearly 3M vehicles"에는 거시 키워드가 하나도 없다. 그래서 **업무 맥락**을
# 따로 둔다: 태그가 붙은 기사는 실적·리콜·소송·인수처럼 회사에 일어난 일을
# 가리키는 말이 하나는 있어야 한다. 연예 금지어를 끝없이 늘리는 것보다,
# 통과 조건을 말하는 편이 오래간다.
_BUSINESS_CONTEXT = (
    "earnings", "revenue", "profit", "loss", "shares", "stock", "stake", "dividend",
    "recall", "lawsuit", "sue", "settlement", "ceo", "cfo", "layoff", "job cut",
    "acquisition", "acquire", "merger", "buyout", "ipo", "guidance", "results",
    "forecast", "sales", "demand", "supply", "factory", "plant", "chip",
    "semiconductor", "cash flow", "valuation", "market cap", "investor", "funding",
    "antitrust", "regulator", "fine", "probe", "investigation", "outage", "strike",
    "contract", "launch", "price cut", "buyback", "bankruptcy", "downgrade", "upgrade",
    # 실적·주가 움직임을 말하는 표현. 처음에 빠뜨렸다가 기존 테스트에 잡혔다 —
    # "Samsung Electronics beats estimates"와 "Nvidia and Microsoft rally"가
    # 걸러지고 있었다. 둘 다 명백한 시장 뉴스다.
    "beat", "miss", "estimate", "rally", "surge", "plunge", "slump", "soar",
    "tumble", "outlook", "target", "analyst", "quarterly", "quarter", "margin",
    "order", "backlog", "export", "import", "output", "shipment", "yield",
)
_BUSINESS_PATTERNS = tuple(
    re.compile(rf"\b{re.escape(word)}(?:s|es|ed|ing)?\b", re.I) for word in _BUSINESS_CONTEXT
)


def _has_business_context(title: str) -> bool:
    return any(pattern.search(title) for pattern in _BUSINESS_PATTERNS)


def admits(title: str, tags: object) -> bool:
    """이 기사를 남기는가 — 수집할 때와 이어받을 때가 같은 규칙을 쓰도록.

    이 판정이 수집 경로에만 있으면, 이미 저장된 기사는 필터를 통과한 적 없이
    계속 실려 온다(블롭은 이전 기사를 URL로 이어받아 병합한다). 필터를 켠 날
    화면이 그대로인 이유가 그것이다.
    """
    if _is_generated(title) or _is_off_topic(title):
        return False
    return bool(_matches_keyword(title) or (tags and _has_business_context(title)))


def _is_generated(title: str) -> bool:
    return any(pattern.search(title) for pattern in _GENERATED_TITLE)


def _is_off_topic(title: str) -> bool:
    return any(pattern.search(title) for pattern in _OFF_TOPIC)


def _matches_keyword(title: str) -> bool:
    return any(pattern.search(title) for pattern in _KEYWORD_PATTERNS)


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

# 코인 이름 사전 — 같은 규칙(닫힌 사전 + 단어 경계)이지만 허브가 코인 페이지다.
# 영어 단어와 겹치는 티커는 넣지 않는다: SOL(스페인어 "해"), LINK, SUI, HYPE,
# ETH(취리히 공대), 그리고 DOGE(미 정부효율부)는 2025년 이후 뉴스에서 코인보다
# 그쪽을 더 자주 뜻한다. 오태깅보다 무태깅이 낫다.
COIN_NAMES: tuple[tuple[str, str, str], ...] = (
    ("Bitcoin", "BTC", "비트코인"),
    ("BTC", "BTC", "비트코인"),
    ("Ethereum", "ETH", "이더리움"),
    ("Solana", "SOL", "솔라나"),
    ("XRP", "XRP", "리플 (XRP)"),
    ("Dogecoin", "DOGE", "도지코인"),
    ("Hyperliquid", "HYPE", "하이퍼리퀴드 (HYPE)"),
    ("Chainlink", "LINK", "체인링크"),
    ("AVAX", "AVAX", "아발란체"),
    ("BNB", "BNB", "BNB"),
)

_COIN_PATTERNS = tuple(
    (re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE), symbol, label)
    for name, symbol, label in COIN_NAMES
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


def _coin_tags_for(title: str) -> list[dict[str, Any]]:
    """Coin tags carry the coin hub; no price rides along (the page has the live one)."""
    tags: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern, symbol, label in _COIN_PATTERNS:
        if symbol in seen or not pattern.search(title):
            continue
        seen.add(symbol)
        tags.append({"symbol": symbol, "kind": "crypto", "name": label, "hub": f"/crypto/{symbol}"})
    return tags


def _tags_for(title: str) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern, symbol, korean in _PATTERNS:
        if symbol in seen or not pattern.search(title):
            continue
        seen.add(symbol)
        tag: dict[str, Any] = {"symbol": symbol, "kind": "equity", "hub": f"/stock/{symbol}"}
        if korean:
            listing = store.get_kr_listing(symbol)
            if listing is not None:
                change = listing.get("flt_rt")
                if change is not None:
                    tag["change_percent"] = float(change)
                    tag["change_basis"] = "t1_close"  # 전일 확정 종가 기준
                tag["name"] = listing.get("itms_nm")
        tags.append(tag)
    return [*tags, *_coin_tags_for(title)]


def refresh(provider: GdeltProvider | None = None) -> dict:
    """쿼리들을 걷어 URL 중복 제거·최신순 병합으로 블롭을 갈아끼운다."""
    _require_lane()
    provider = provider or GdeltProvider(
        timeout=config.GDELT_TIMEOUT, retries=config.GDELT_RETRIES
    )

    previous = store.load_report(CACHE_KEY, config.REPORT_TTL * 2) or {}
    by_url: dict[str, dict[str, Any]] = {
        article["url"]: article
        for article in previous.get("articles", [])
        # 저장된 기사도 같은 문을 통과해야 한다 — 규칙이 바뀌면 이미 실린 것도
        # 다음 갱신에서 걸러진다.
        if admits(article.get("title") or "", article.get("tags"))
    }
    # 벌크 채널: 15분 GKG 파일 하나에서 제목을 뽑아 키워드·종목 사전으로 거른다.
    # (DOC API는 AWS IP에서 지속 차단 — 등록부 §6.1, GDELT의 벌크 전환 권고 준수)
    fetched = 0
    for article in provider.fetch_latest_gkg_titles():
        title = article["title"]
        tags = _tags_for(title)
        if not admits(title, tags):
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


def crypto_articles(symbol: str | None = None, *, limit: int = 20) -> dict[str, Any]:
    """Stored headlines that carry a coin tag, optionally for one coin."""
    payload = get_news()
    wanted = symbol.strip().upper() if symbol else None
    articles = []
    for article in payload.get("articles") or []:
        coins = [tag for tag in article.get("tags") or [] if tag.get("kind") == "crypto"]
        if not coins or (wanted and all(tag["symbol"] != wanted for tag in coins)):
            continue
        articles.append({**article, "coins": coins})
        if len(articles) >= max(1, min(50, limit)):
            break
    return {
        "generated_at": payload.get("generated_at"),
        "symbol": wanted,
        "count": len(articles),
        "articles": articles,
        "attribution": payload.get("attribution"),
        "source": payload.get("source"),
        "rights": payload.get("rights"),
        "basis_ko": payload.get("basis_ko"),
        "basis_en": payload.get("basis_en"),
        "coins_tagged": [{"symbol": s, "name": label} for _p, s, label in _COIN_PATTERNS],
    }


def get_news() -> dict:
    """저장된 결과만 읽는다. 요청 경로에서 GDELT를 호출하지 않는다."""
    _require_lane()
    from .providers.base import DataUnavailable

    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("news headlines not collected yet")
    return cached
