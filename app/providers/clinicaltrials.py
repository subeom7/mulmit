"""ClinicalTrials.gov API v2 — lead-sponsor pipeline for a curated watchlist.

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.22): a U.S. Government database,
"available to all requesters, both within and outside the United States, at no
charge".  The Terms and Conditions (last updated 2023-01-31) attach four display
duties to any publication or distribution — attribute the source as
ClinicalTrials.gov, keep the data current, clearly display the date the data
were processed by ClinicalTrials.gov, and state any modifications made.  The
serving layer carries all four.  Narrative text (summaries, descriptions) may be
third-party copyrighted and is not requested at all — only identifiers, status,
phase, dates, conditions and intervention names.
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

PROVIDER_ID = "clinicaltrials"
PUBLISHER = "ClinicalTrials.gov (U.S. National Library of Medicine)"
ATTRIBUTION = "ClinicalTrials.gov"
API_URL = "https://clinicaltrials.gov/api/v2/studies"
VERSION_URL = "https://clinicaltrials.gov/api/v2/version"
STUDY_URL = "https://clinicaltrials.gov/study/{nct_id}"
SITE_URL = "https://clinicaltrials.gov/"
TERMS_URL = "https://clinicaltrials.gov/about-site/terms-conditions"
TERMS_QUOTE = (
    "In any publication or distribution of these data, you should: Attribute the source of the "
    "data as ClinicalTrials.gov; Update the data such that they are current at all times; Clearly "
    "display the date the data were processed by ClinicalTrials.gov; State any modifications made "
    "to the content of the data (Terms and Conditions, last updated 2023-01-31)"
)
# Only structured fields — no narrative text.
FIELDS = (
    "NCTId,BriefTitle,OverallStatus,Phase,StudyType,LastUpdatePostDate,LastUpdateSubmitDate,"
    "StatusVerifiedDate,StartDate,PrimaryCompletionDate,CompletionDate,Condition,"
    "LeadSponsorName,WhyStopped,ResultsFirstPostDate,InterventionName,EnrollmentCount"
)
DEFAULT_PAGE_SIZE = 25
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
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


def _date(struct: Any) -> str | None:
    """Date structs look like ``{"date": "2027-02", "type": "ESTIMATED"}``; partial dates are kept as given."""
    if isinstance(struct, dict):
        value = struct.get("date")
        return str(value) if value else None
    return str(struct) if isinstance(struct, str) and struct else None


def _names(items: Any) -> list[str]:
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def parse_study(raw: Any) -> dict[str, Any] | None:
    """Flatten one v2 study record to the structured subset Mulmit shows."""
    if not isinstance(raw, dict):
        return None
    protocol = raw.get("protocolSection") if isinstance(raw.get("protocolSection"), dict) else {}
    ident = protocol.get("identificationModule") or {}
    status = protocol.get("statusModule") or {}
    design = protocol.get("designModule") or {}
    sponsors = protocol.get("sponsorCollaboratorsModule") or {}
    conditions = protocol.get("conditionsModule") or {}
    arms = protocol.get("armsInterventionsModule") or {}
    nct_id = ident.get("nctId")
    if not isinstance(nct_id, str) or not nct_id:
        return None
    lead = sponsors.get("leadSponsor") if isinstance(sponsors.get("leadSponsor"), dict) else {}
    enrollment = design.get("enrollmentInfo") if isinstance(design.get("enrollmentInfo"), dict) else {}
    phases = [str(p) for p in (design.get("phases") or []) if p]
    return {
        "nct_id": nct_id,
        "title": ident.get("briefTitle"),
        "status": status.get("overallStatus"),
        "why_stopped": status.get("whyStopped"),
        "phases": phases,
        "study_type": design.get("studyType"),
        "last_update_post": _date(status.get("lastUpdatePostDateStruct")),
        "last_update_submit": status.get("lastUpdateSubmitDate"),
        "status_verified": status.get("statusVerifiedDate"),
        "start": _date(status.get("startDateStruct")),
        "primary_completion": _date(status.get("primaryCompletionDateStruct")),
        "completion": _date(status.get("completionDateStruct")),
        "results_first_post": _date(status.get("resultsFirstPostDateStruct")),
        "conditions": [str(c) for c in (conditions.get("conditions") or []) if c][:6],
        "interventions": _names(arms.get("interventions"))[:6],
        "lead_sponsor": lead.get("name"),
        "enrollment": enrollment.get("count"),
        "url": STUDY_URL.format(nct_id=nct_id),
    }


def parse_studies(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DataUnavailable("ClinicalTrials.gov returned a non-object payload")
    studies = [row for row in (parse_study(item) for item in raw.get("studies") or []) if row]
    total = raw.get("totalCount")
    return {"total_count": int(total) if isinstance(total, int) else None, "studies": studies}


class ClinicalTrialsProvider:
    """Unkeyed GETs against the public v2 API, paced by the caller."""

    name = PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        page_size: int = DEFAULT_PAGE_SIZE,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self.page_size = max(1, min(1000, int(page_size)))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep

    def fetch_version(self) -> dict[str, Any]:
        raw = self._request(VERSION_URL)
        if not isinstance(raw, dict):
            raise DataUnavailable("ClinicalTrials.gov version endpoint returned a non-object payload")
        return {
            "fetched_at": _utc_iso(self._wall_clock()),
            "api_version": raw.get("apiVersion"),
            "data_timestamp": raw.get("dataTimestamp"),
        }

    def fetch_lead_sponsor(self, query: str, *, page_size: int | None = None) -> dict[str, Any]:
        """Studies whose lead sponsor matches ``query``, most recently updated first."""
        if not query or not query.strip():
            raise ValueError("a lead-sponsor query is required")
        params = {
            "query.lead": query.strip(),
            "sort": "LastUpdatePostDate:desc",
            "pageSize": str(page_size or self.page_size),
            "fields": FIELDS,
            "countTotal": "true",
        }
        raw = self._request(f"{API_URL}?{urllib.parse.urlencode(params)}")
        parsed = parse_studies(raw)
        parsed["fetched_at"] = _utc_iso(self._wall_clock())
        parsed["query"] = query.strip()
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
                        raise RateLimited("ClinicalTrials.gov rate limit reached") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(f"ClinicalTrials.gov rejected the request with HTTP {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("ClinicalTrials.gov returned an unreadable response") from exc
            if attempt < self.retries:
                self._sleep(min(0.5 * (2**attempt), 2.0))
        raise DataUnavailable("ClinicalTrials.gov is unavailable") from last_error
