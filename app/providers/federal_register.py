"""Federal Register API — FDA advisory committee meeting notices.

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.24): the Federal Register is a
U.S. Government publication (Office of the Federal Register, NARA, printed by
GPO) — a government work with no copyright (17 U.S.C. §105).  FederalRegister.gov
states "No API keys are needed; all you need is an HTTP client or browser" and
one usage restriction: "Republishers of Federal Register material are not
permitted to use official NARA or OFR logos or seals."  Mulmit shows titles,
dates and links, never logos.  FDA's own calendar page sits behind bot
detection, so this structured public source is used instead of scraping.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import DataUnavailable, RateLimited

PROVIDER_ID = "federal_register"
PUBLISHER = "Federal Register (Office of the Federal Register, NARA)"
ATTRIBUTION = "Source: Federal Register (Office of the Federal Register, NARA)"
API_URL = "https://www.federalregister.gov/api/v1/documents.json"
SITE_URL = "https://www.federalregister.gov/"
DEVELOPER_URL = "https://www.federalregister.gov/reader-aids/developer-resources/rest-api"
USAGE_QUOTE = (
    "No API keys are needed; all you need is an HTTP client or browser. … Usage Restrictions: Republishers of "
    "Federal Register material are not permitted to use official NARA or OFR logos or seals (Developer Resources, "
    "accessed 2026-08-22)"
)
FDA_AGENCY_SLUG = "food-and-drug-administration"
SEARCH_TERM = '"advisory committee"'
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
DEFAULT_PER_PAGE = 100
FIELDS = ("title", "publication_date", "html_url", "dates", "action", "document_number", "abstract", "type")
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})",
    re.IGNORECASE,
)
_MEETING_KEYWORDS = ("notice of meeting", "amendment of notice", "notice of public meeting", "meeting announcement")

Transport = Callable[[str, dict[str, str], float], Any]


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def extract_dates(text: Any) -> list[str]:
    """All ``Month D, YYYY`` dates in a DATES paragraph, ISO formatted, in order of appearance."""
    if not isinstance(text, str) or not text:
        return []
    out: list[str] = []
    for month, day, year in _DATE_RE.findall(text):
        try:
            out.append(dt.date(int(year), _MONTHS[month.lower()], int(day)).isoformat())
        except ValueError:
            continue
    return out


def is_meeting_notice(title: Any) -> bool:
    lowered = str(title or "").lower()
    return "advisory committee" in lowered and any(key in lowered for key in _MEETING_KEYWORDS)


def committee_name(title: Any) -> str | None:
    head = str(title or "").split(";")[0].strip()
    return head or None


def parse_documents(raw: Any) -> dict[str, Any]:
    """Flatten the documents.json page to meeting notices only."""
    if not isinstance(raw, dict):
        raise DataUnavailable("Federal Register returned a non-object payload")
    if isinstance(raw.get("errors"), (dict, list)):
        raise DataUnavailable(f"Federal Register error: {raw.get('errors')}")
    notices: list[dict[str, Any]] = []
    for item in raw.get("results") or []:
        if not isinstance(item, dict) or not is_meeting_notice(item.get("title")):
            continue
        dates = extract_dates(item.get("dates"))
        abstract = item.get("abstract")
        notices.append({
            "document_number": item.get("document_number"),
            "title": item.get("title"),
            "committee": committee_name(item.get("title")),
            "publication_date": item.get("publication_date"),
            "action": item.get("action"),
            "meeting_dates": dates,
            "meeting_start": dates[0] if dates else None,
            "meeting_end": dates[-1] if dates else None,
            "dates_text": item.get("dates") or None,
            "summary": (abstract[:320].rstrip() + ("…" if len(abstract) > 320 else "")) if isinstance(abstract, str) and abstract else None,
            "url": item.get("html_url"),
            "amendment": "amendment" in str(item.get("title") or "").lower(),
        })
    return {
        "count": raw.get("count"),
        "total_pages": raw.get("total_pages"),
        "notices": notices,
    }


class FederalRegisterProvider:
    """Unkeyed GETs against documents.json; one or two pages per refresh."""

    name = PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep

    def fetch_fda_meeting_notices(self, *, since: dt.date, per_page: int = DEFAULT_PER_PAGE, page: int = 1) -> dict[str, Any]:
        params: list[tuple[str, str]] = [
            ("conditions[agencies][]", FDA_AGENCY_SLUG),
            ("conditions[type][]", "NOTICE"),
            ("conditions[term]", SEARCH_TERM),
            ("conditions[publication_date][gte]", since.isoformat()),
            ("order", "newest"),
            ("per_page", str(max(1, min(1000, int(per_page))))),
            ("page", str(max(1, int(page)))),
        ] + [("fields[]", field) for field in FIELDS]
        raw = self._request(f"{API_URL}?{urllib.parse.urlencode(params)}")
        parsed = parse_documents(raw)
        parsed["fetched_at"] = _utc_iso(self._wall_clock())
        parsed["since"] = since.isoformat()
        return parsed

    def _request(self, url: str) -> Any:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._transport(url, headers, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    if attempt >= self.retries:
                        raise RateLimited("Federal Register rate limit reached") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(f"Federal Register rejected the request with HTTP {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("Federal Register returned an unreadable response") from exc
            if attempt < self.retries:
                self._sleep(min(0.5 * (2**attempt), 2.0))
        raise DataUnavailable("Federal Register is unavailable") from last_error
