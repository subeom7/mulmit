"""NCBI E-utilities (PubMed) — publications linked to a ClinicalTrials.gov id, metadata only.

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.25): PubMed citation metadata
(title, journal, dates, publication types, identifiers) is relayed with a link
to the PubMed record; abstracts are never requested because NCBI notes that
"abstracts in PubMed may incorporate material that may be protected by U.S. and
foreign copyright laws".  NCBI's usage guidelines ask for no more than three
requests per second without an API key (ten with one), the ``tool`` and
``email`` parameters on every request, and large jobs on weekends or between
9 PM and 5 AM Eastern — the ingest lane paces itself and honours that window.
Search uses the secondary-source-id field (``NCT01234567[si]``), which is how
PubMed indexes ClinicalTrials.gov registration numbers.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import DataUnavailable, RateLimited

PROVIDER_ID = "pubmed"
PUBLISHER = "PubMed (U.S. National Library of Medicine, NCBI)"
ATTRIBUTION = "Source: PubMed (NCBI / NLM)"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
ARTICLE_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
SEARCH_URL = "https://pubmed.ncbi.nlm.nih.gov/?term={term}"
SITE_URL = "https://pubmed.ncbi.nlm.nih.gov/"
POLICY_URL = "https://www.ncbi.nlm.nih.gov/books/NBK25497/"
POLICY_QUOTE = (
    "post no more than three URL requests per second … limit large jobs to either weekends or between "
    "9:00 PM and 5:00 AM Eastern time during weekdays … abstracts in PubMed may incorporate material that "
    "may be protected by U.S. and foreign copyright laws (E-utilities usage guidelines, NBK25497)"
)
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
DEFAULT_TOOL = "mulmit"
MAX_SUMMARY_IDS = 50
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

Transport = Callable[[str, dict[str, str], float], Any]


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def nct_search_term(nct_id: str) -> str:
    return f"{nct_id}[si]"


def search_page_url(nct_id: str) -> str:
    return SEARCH_URL.format(term=urllib.parse.quote(nct_search_term(nct_id), safe=""))


def parse_esearch(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DataUnavailable("PubMed esearch returned a non-object payload")
    if "error" in raw and isinstance(raw.get("error"), str):
        raise DataUnavailable(f"PubMed esearch error: {raw['error']}")
    result = raw.get("esearchresult") if isinstance(raw.get("esearchresult"), dict) else None
    if result is None:
        raise DataUnavailable("PubMed esearch returned no esearchresult")
    try:
        count = int(result.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    ids = [str(i) for i in (result.get("idlist") or []) if str(i).isdigit()]
    return {"count": count, "pmids": ids}


def _doi(article_ids: Any) -> str | None:
    for entry in article_ids if isinstance(article_ids, list) else []:
        if isinstance(entry, dict) and entry.get("idtype") == "doi" and entry.get("value"):
            return str(entry["value"])
    return None


def parse_esummary(raw: Any) -> list[dict[str, Any]]:
    """Citation metadata only — no abstract is present in esummary output."""
    if not isinstance(raw, dict):
        raise DataUnavailable("PubMed esummary returned a non-object payload")
    result = raw.get("result") if isinstance(raw.get("result"), dict) else None
    if result is None:
        if isinstance(raw.get("error"), str):
            raise DataUnavailable(f"PubMed esummary error: {raw['error']}")
        return []
    articles: list[dict[str, Any]] = []
    for uid in result.get("uids") or []:
        item = result.get(str(uid))
        if not isinstance(item, dict) or item.get("error"):
            continue
        pmid = str(item.get("uid") or uid)
        articles.append({
            "pmid": pmid,
            "title": (item.get("title") or "").strip() or None,
            "journal": item.get("fulljournalname") or item.get("source"),
            "pubdate": item.get("pubdate"),
            "epubdate": item.get("epubdate") or None,
            "sort_date": item.get("sortpubdate"),
            "pubtypes": [str(p) for p in (item.get("pubtype") or [])][:6],
            "doi": _doi(item.get("articleids")),
            "url": ARTICLE_URL.format(pmid=pmid),
        })
    return articles


class PubMedProvider:
    """Paced, identified E-utilities calls; the key (if any) never leaves the ingest process."""

    name = PROVIDER_ID

    def __init__(
        self,
        *,
        tool: str = DEFAULT_TOOL,
        email: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.tool = (tool or DEFAULT_TOOL).strip()
        self.email = (email or "").strip() or None
        self._api_key = (api_key or "").strip() or None
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep

    def _identity(self) -> dict[str, str]:
        params = {"tool": self.tool, "retmode": "json"}
        if self.email:
            params["email"] = self.email
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def search_nct(self, nct_id: str, *, retmax: int = 5) -> dict[str, Any]:
        params = {"db": "pubmed", "term": nct_search_term(nct_id), "retmax": str(max(1, min(100, int(retmax)))), "sort": "pub_date", **self._identity()}
        raw = self._request(f"{ESEARCH_URL}?{urllib.parse.urlencode(params)}")
        parsed = parse_esearch(raw)
        parsed["nct_id"] = nct_id
        parsed["fetched_at"] = _utc_iso(self._wall_clock())
        return parsed

    def summaries(self, pmids: list[str]) -> list[dict[str, Any]]:
        ids = [str(p) for p in pmids if str(p).isdigit()]
        if not ids:
            return []
        if len(ids) > MAX_SUMMARY_IDS:
            raise ValueError(f"at most {MAX_SUMMARY_IDS} ids per esummary call")
        params = {"db": "pubmed", "id": ",".join(ids), **self._identity()}
        raw = self._request(f"{ESUMMARY_URL}?{urllib.parse.urlencode(params)}")
        return parse_esummary(raw)

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
                        raise RateLimited("NCBI E-utilities rate limit reached") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(f"NCBI E-utilities rejected the request with HTTP {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("NCBI E-utilities returned an unreadable response") from exc
            if attempt < self.retries:
                self._sleep(min(0.5 * (2**attempt), 2.0))
        raise DataUnavailable("NCBI E-utilities are unavailable") from last_error
