"""정부 보도자료 헤드라인 — 뉴스의 한국어 축.

기관이 구독·연동 목적으로 공표하는 RSS에서 **제목 + 기관명 + 원문 링크**만
전달한다. 본문·요약은 쓰지 않는다(피드의 description은 읽지도 않는다) —
GDELT lane과 같은 안전선이며, KOGL 유형 검토는 본문을 다루게 될 때의 일이다.
기재부 푸터의 "All rights reserved" 병기는 등록부 §6.1에 기록되어 있다.

날짜 정직성: 금융위 피드는 게시일을 주지 않는다. 그런 항목은 처음 본 수집
시각을 `first_seen` 기준으로 달고 그렇게 표기한다 — 게시 시각을 지어내지
않는다.
"""

from __future__ import annotations

import datetime as dt
import email.utils
import logging
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import config, store
from .providers.base import DataUnavailable

log = logging.getLogger(__name__)

CACHE_KEY = "kr_press_v1"
MAX_ITEMS = 40
_UA = "Mozilla/5.0 (compatible; Mulmit/1.0; +https://mulmit.com)"

FEEDS: tuple[dict[str, str], ...] = (
    {
        "agency": "금융위원회",
        "agency_en": "FSC",
        "url": "https://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111",
    },
    {
        "agency": "기획재정부",
        "agency_en": "MOEF",
        "url": "https://www.moef.go.kr/com/detailRssTagService.do?bbsId=MOSFBBS_000000000028",
    },
)

_ITEM = re.compile(r"<item>(.*?)</item>", re.S)
_TITLE = re.compile(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
_LINK = re.compile(r"<link>(?:<!\[CDATA\[)?(http[^\]<\s]+)", re.S)
_PUBDATE = re.compile(r"<pubDate>(.*?)</pubDate>", re.S)


class KrPressDisabled(RuntimeError):
    def __init__(self, reason: str = "disabled") -> None:
        super().__init__(reason)
        self.reason = reason


def _require_lane() -> None:
    if not config.KR_PRESS_ENABLED:
        raise KrPressDisabled("disabled")


def _fetch_xml(url: str) -> str:
    request = Request(url, headers={"User-Agent": _UA, "Accept": "application/rss+xml"})
    try:
        with urlopen(request, timeout=config.KR_PRESS_TIMEOUT) as response:  # noqa: S310
            return response.read().decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DataUnavailable(f"press feed unusable at {url}") from exc


def _pub_iso(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        moment = email.utils.parsedate_to_datetime(raw.strip())
    except (TypeError, ValueError):
        # 기재부는 "2026-08-19 13:00" 꼴도 쓴다.
        try:
            moment = dt.datetime.fromisoformat(raw.strip()).replace(
                tzinfo=dt.timezone(dt.timedelta(hours=9))
            )
        except ValueError:
            return None
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def refresh(fetch_xml=None) -> dict:
    """피드들을 걷어 링크 기준 병합·최신순 저장. 실패한 기관은 그 기관만 빠진다."""
    _require_lane()
    fetch = fetch_xml or _fetch_xml
    now_iso = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")

    previous = store.load_report(CACHE_KEY, config.REPORT_TTL * 2) or {}
    by_link: dict[str, dict[str, Any]] = {
        item["url"]: item for item in previous.get("items", [])
    }
    fetched = 0
    for feed in FEEDS:
        try:
            xml = fetch(feed["url"])
        except DataUnavailable as exc:
            log.warning("보도자료 피드 실패 %s: %s", feed["agency"], exc)
            continue
        for block in _ITEM.findall(xml):
            title_match = _TITLE.search(block)
            link_match = _LINK.search(block)
            if not title_match or not link_match:
                continue
            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
            url = link_match.group(1).strip()
            if not title or url in by_link:
                # 이미 본 항목은 first_seen을 보존한다.
                continue
            published = _pub_iso(
                _PUBDATE.search(block).group(1) if _PUBDATE.search(block) else None
            )
            fetched += 1
            by_link[url] = {
                "title": title,
                "url": url,
                "agency": feed["agency"],
                "agency_en": feed["agency_en"],
                # 게시일이 없으면 수집 시각을 쓰되, 그 사실을 basis로 남긴다.
                "at": published or now_iso,
                "date_basis": "published" if published else "first_seen",
            }

    items = sorted(by_link.values(), key=lambda item: item["at"], reverse=True)[:MAX_ITEMS]
    payload = {
        "generated_at": now_iso,
        "items": items,
        "count": len(items),
        "basis_ko": (
            "각 기관이 공표하는 보도자료 RSS의 제목·기관명·원문 링크만 전달합니다. "
            "본문은 다루지 않습니다. 게시일이 없는 피드(금융위)는 수집 시각 기준으로 "
            "표기합니다. 수집 주기 갱신 — 실시간이 아닙니다."
        ),
        "basis_en": (
            "Titles, agency names and links from official press-release RSS feeds; "
            "no bodies are relayed. Feeds without publish dates (FSC) are stamped by "
            "first collection time and labeled as such. Collection-cycle cadence."
        ),
        "source": {
            "provider": "kr_press",
            "feeds": [
                {"agency": feed["agency"], "url": feed["url"]} for feed in FEEDS
            ],
        },
        "rights": {
            "status": "approved",
            "notice": "기관 공표 RSS의 구독·연동 용도 내 사용 (제목·출처·링크)",
        },
    }
    store.save_report(CACHE_KEY, payload)
    return {"fetched": fetched, "kept": len(items)}


def get_press() -> dict:
    _require_lane()
    cached = store.load_report(CACHE_KEY, config.REPORT_TTL * 2)
    if cached is None:
        raise DataUnavailable("press releases not collected yet")
    return cached
