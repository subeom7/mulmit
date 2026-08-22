"""Bio section — clinical pipeline watchlist (ClinicalTrials.gov) and recent FDA original approvals (openFDA).

Both lanes are ingest-stored blobs read by the request path; both sources are
U.S. federal public data (docs/DATA_SOURCE_REGISTER.md §3.22, §3.23).  The
ClinicalTrials.gov Terms attach four display duties to any distribution —
attribution, currency, the date ClinicalTrials.gov processed the data, and a
statement of modifications — and every trials payload carries all four.  The
sponsor↔listing labels are Mulmit's own reference labels, stated as such.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from typing import Any
from zoneinfo import ZoneInfo

from . import config, data_rights, store
from .providers import clinicaltrials as ct
from .providers import federal_register as fr
from .providers import mfds as mf
from .providers import openfda as fda
from .providers import pubmed as pm
from .providers.base import DataUnavailable, RateLimited

log = logging.getLogger(__name__)

TRIALS_CACHE_KEY = "bio_trials_v1"
FDA_CACHE_KEY = "bio_fda_approvals_v1"
SERVE_TTL_SECONDS = 60 * 60 * 48
TRIALS_STALE_AFTER_SECONDS = 60 * 60 * 12
FDA_STALE_AFTER_SECONDS = 60 * 60 * 36
LOAD_CACHE_SECONDS = 60.0
# Refreshes read their own previous blob back regardless of age (carry-over of unchanged entries).
HISTORY_READ_TTL_SECONDS = 10 * 365 * 24 * 3600
RECENT_DAYS = 14
RESULTS_RECENT_DAYS = 30
NEW_START_DAYS = 30
RECENT_LIMIT = 150
PER_SPONSOR_CAP = 8  # newest first, so the cap keeps the freshest rows of each sponsor
# openFDA's search matches applications where *some* submission satisfies each clause, so the result set is
# wider than the ORIG-approval subset we keep; page through all of it (≈7 pages of 100 at 60 days).
FDA_MAX_PAGES = 12
WATCH_PHASES = {"PHASE2", "PHASE3"}
RECRUITING_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"}
STOPPED_STATUSES = {"TERMINATED", "WITHDRAWN", "SUSPENDED"}

# Lead-sponsor search terms for ClinicalTrials.gov plus Mulmit's own display
# labels. Listing labels are reference labels added by Mulmit (checked
# 2026-08-22) — the database itself carries no ticker.
WATCHLIST: list[dict[str, Any]] = [
    {"id": "pfizer", "query": "Pfizer", "name": {"ko": "화이자", "en": "Pfizer"}, "country": "US", "listing": {"exchange": "NYSE", "ticker": "PFE"}},
    {"id": "merck", "query": "Merck Sharp & Dohme", "name": {"ko": "머크(MSD)", "en": "Merck (MSD)"}, "country": "US", "listing": {"exchange": "NYSE", "ticker": "MRK"}},
    {"id": "lilly", "query": "Eli Lilly", "name": {"ko": "일라이 릴리", "en": "Eli Lilly"}, "country": "US", "listing": {"exchange": "NYSE", "ticker": "LLY"}},
    {"id": "novo", "query": "Novo Nordisk", "name": {"ko": "노보 노디스크", "en": "Novo Nordisk"}, "country": "DK", "listing": {"exchange": "NYSE", "ticker": "NVO"}},
    {"id": "astrazeneca", "query": "AstraZeneca", "name": {"ko": "아스트라제네카", "en": "AstraZeneca"}, "country": "GB", "listing": {"exchange": "NASDAQ", "ticker": "AZN"}},
    {"id": "janssen", "query": "Janssen", "name": {"ko": "얀센(J&J)", "en": "Janssen (J&J)"}, "country": "US", "listing": {"exchange": "NYSE", "ticker": "JNJ"}, "note": {"ko": "모회사 존슨앤드존슨", "en": "parent: Johnson & Johnson"}},
    {"id": "roche", "query": "Hoffmann-La Roche", "name": {"ko": "로슈", "en": "Roche"}, "country": "CH", "listing": {"exchange": "SIX", "ticker": "ROG"}},
    {"id": "novartis", "query": "Novartis", "name": {"ko": "노바티스", "en": "Novartis"}, "country": "CH", "listing": {"exchange": "NYSE", "ticker": "NVS"}},
    {"id": "abbvie", "query": "AbbVie", "name": {"ko": "애브비", "en": "AbbVie"}, "country": "US", "listing": {"exchange": "NYSE", "ticker": "ABBV"}},
    {"id": "bms", "query": "Bristol-Myers Squibb", "name": {"ko": "BMS", "en": "Bristol Myers Squibb"}, "country": "US", "listing": {"exchange": "NYSE", "ticker": "BMY"}},
    {"id": "amgen", "query": "Amgen", "name": {"ko": "암젠", "en": "Amgen"}, "country": "US", "listing": {"exchange": "NASDAQ", "ticker": "AMGN"}},
    {"id": "gilead", "query": "Gilead Sciences", "name": {"ko": "길리어드", "en": "Gilead"}, "country": "US", "listing": {"exchange": "NASDAQ", "ticker": "GILD"}},
    {"id": "regeneron", "query": "Regeneron", "name": {"ko": "리제네론", "en": "Regeneron"}, "country": "US", "listing": {"exchange": "NASDAQ", "ticker": "REGN"}},
    {"id": "vertex", "query": "Vertex Pharmaceuticals", "name": {"ko": "버텍스", "en": "Vertex"}, "country": "US", "listing": {"exchange": "NASDAQ", "ticker": "VRTX"}},
    {"id": "moderna", "query": "ModernaTX", "name": {"ko": "모더나", "en": "Moderna"}, "country": "US", "listing": {"exchange": "NASDAQ", "ticker": "MRNA"}},
    {"id": "sanofi", "query": "Sanofi", "name": {"ko": "사노피", "en": "Sanofi"}, "country": "FR", "listing": {"exchange": "NASDAQ", "ticker": "SNY"}},
    {"id": "gsk", "query": "GlaxoSmithKline", "name": {"ko": "GSK", "en": "GSK"}, "country": "GB", "listing": {"exchange": "NYSE", "ticker": "GSK"}},
    {"id": "bayer", "query": "Bayer", "name": {"ko": "바이엘", "en": "Bayer"}, "country": "DE", "listing": {"exchange": "XETRA", "ticker": "BAYN"}},
    {"id": "daiichi", "query": "Daiichi Sankyo", "name": {"ko": "다이이찌산쿄", "en": "Daiichi Sankyo"}, "country": "JP", "listing": {"exchange": "TSE", "ticker": "4568"}},
    {"id": "takeda", "query": "Takeda", "name": {"ko": "다케다", "en": "Takeda"}, "country": "JP", "listing": {"exchange": "NYSE", "ticker": "TAK"}},
    {"id": "celltrion", "query": "Celltrion", "name": {"ko": "셀트리온", "en": "Celltrion"}, "country": "KR", "listing": {"exchange": "KOSPI", "ticker": "068270"}},
    {"id": "samsung_bioepis", "query": "Samsung Bioepis", "name": {"ko": "삼성바이오에피스", "en": "Samsung Bioepis"}, "country": "KR", "listing": None, "note": {"ko": "삼성바이오로직스(207940) 자회사", "en": "subsidiary of Samsung Biologics (207940)"}},
    {"id": "hanmi", "query": "Hanmi Pharmaceutical", "name": {"ko": "한미약품", "en": "Hanmi Pharmaceutical"}, "country": "KR", "listing": {"exchange": "KOSPI", "ticker": "128940"}},
    {"id": "yuhan", "query": "Yuhan", "name": {"ko": "유한양행", "en": "Yuhan"}, "country": "KR", "listing": {"exchange": "KOSPI", "ticker": "000100"}},
    {"id": "skbp", "query": "SK Life Science", "name": {"ko": "SK바이오팜", "en": "SK Biopharmaceuticals"}, "country": "KR", "listing": {"exchange": "KOSPI", "ticker": "326030"}, "note": {"ko": "미국 자회사 SK Life Science 명의 등록", "en": "registered by U.S. subsidiary SK Life Science"}},
    {"id": "alteogen", "query": "Alteogen", "name": {"ko": "알테오젠", "en": "Alteogen"}, "country": "KR", "listing": {"exchange": "KOSDAQ", "ticker": "196170"}},
    {"id": "ablbio", "query": "ABL Bio", "name": {"ko": "에이비엘바이오", "en": "ABL Bio"}, "country": "KR", "listing": {"exchange": "KOSDAQ", "ticker": "298380"}},
    {"id": "legochem", "query": "LigaChem", "name": {"ko": "리가켐바이오", "en": "LigaChem Biosciences"}, "country": "KR", "listing": {"exchange": "KOSDAQ", "ticker": "141080"}},
    {"id": "daewoong", "query": "Daewoong", "name": {"ko": "대웅제약", "en": "Daewoong Pharmaceutical"}, "country": "KR", "listing": {"exchange": "KOSPI", "ticker": "069620"}},
    {"id": "ckd", "query": "Chong Kun Dang", "name": {"ko": "종근당", "en": "Chong Kun Dang"}, "country": "KR", "listing": {"exchange": "KOSPI", "ticker": "185750"}},
    {"id": "gcbio", "query": "GC Biopharma", "name": {"ko": "GC녹십자", "en": "GC Biopharma"}, "country": "KR", "listing": {"exchange": "KOSPI", "ticker": "006280"}},
    {"id": "hlb", "query": "HLB", "name": {"ko": "HLB", "en": "HLB"}, "country": "KR", "listing": {"exchange": "KOSDAQ", "ticker": "028300"}},
    {"id": "elevar", "query": "Elevar", "name": {"ko": "엘레바(HLB 자회사)", "en": "Elevar Therapeutics (HLB)"}, "country": "KR", "listing": None, "note": {"ko": "HLB(028300) 미국 자회사", "en": "U.S. subsidiary of HLB (028300)"}},
    {"id": "hugel", "query": "Hugel", "name": {"ko": "휴젤", "en": "Hugel"}, "country": "KR", "listing": {"exchange": "KOSDAQ", "ticker": "145020"}},
]
WATCHLIST_BY_ID = {spec["id"]: spec for spec in WATCHLIST}

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_sleep = time.sleep


class BioUnavailable(Exception):
    """``reason`` is ``disabled`` or ``collecting``; the route maps it to a 503 contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _parse_date(value: Any) -> dt.date | None:
    """ClinicalTrials.gov dates may be partial (``2027-02``, ``2027``); the first day stands in."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    try:
        if len(text) == 4:
            return dt.date(int(text), 1, 1)
        if len(text) == 7:
            return dt.date(int(text[:4]), int(text[5:7]), 1)
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _within(value: Any, today: dt.date, days: int) -> bool:
    day = _parse_date(value)
    return day is not None and 0 <= (today - day).days <= days


def _load_cached(key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    blob = store.load_report(key, SERVE_TTL_SECONDS)
    with _lock:
        _cache[key] = (now + LOAD_CACHE_SECONDS, blob)
    return blob


# --- ClinicalTrials.gov lane --------------------------------------------------

def refresh_bio_trials(*, force: bool = False, provider: Any | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Ingest lane: one paced GET per watchlist sponsor plus the data-version stamp. Zero calls while off."""
    if not data_rights.clinicaltrials_ingest_enabled():
        return {"skipped": "disabled"}
    if not force and store.load_report(TRIALS_CACHE_KEY, config.CLINICALTRIALS_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or ct.ClinicalTrialsProvider(
        timeout=config.CLINICALTRIALS_TIMEOUT,
        retries=config.CLINICALTRIALS_RETRIES,
        page_size=config.CLINICALTRIALS_PAGE_SIZE,
    )
    try:
        version = client.fetch_version()
    except (DataUnavailable, RateLimited) as exc:
        log.warning("ClinicalTrials.gov version stamp unavailable: %s", exc)
        version = {"api_version": None, "data_timestamp": None}
    sponsors: list[dict[str, Any]] = []
    failed = 0
    for index, spec in enumerate(WATCHLIST):
        if index and config.CLINICALTRIALS_PACE_SECONDS > 0:
            _sleep(config.CLINICALTRIALS_PACE_SECONDS)
        entry: dict[str, Any] = {"id": spec["id"], "query": spec["query"], "total_count": None, "studies": [], "fetched_at": None, "error": None}
        try:
            result = client.fetch_lead_sponsor(spec["query"])
            entry.update(total_count=result.get("total_count"), studies=result.get("studies") or [], fetched_at=result.get("fetched_at"))
        except RateLimited:
            entry["error"] = "rate_limited"
            failed += 1
            sponsors.append(entry)
            log.warning("ClinicalTrials.gov rate limit — stopping this pass after %d sponsors", index)
            break
        except DataUnavailable as exc:
            entry["error"] = "unavailable"
            failed += 1
            log.warning("ClinicalTrials.gov sponsor %s failed: %s", spec["query"], exc)
        sponsors.append(entry)
    if failed >= len(sponsors):
        raise DataUnavailable("ClinicalTrials.gov refresh produced no sponsor data")
    moment = now or dt.datetime.now(dt.UTC)
    store.save_report(
        TRIALS_CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
            "version": version,
            "sponsors": sponsors,
        },
    )
    clear_cache()
    return {"updated": len(sponsors) - failed, "failed": failed, "data_timestamp": version.get("data_timestamp")}


_TRIALS_MODIFICATIONS = {
    "ko": (
        "ClinicalTrials.gov 원본에서 ① 워치리스트 34개 주 스폰서(lead sponsor) 검색 결과만, ② 스폰서당 최근 갱신 25건, ③ 최근 동향 표는 "
        "그중 중재(interventional) 2·3상에 최근 14일 내 갱신 건만(스폰서당 최대 8건), ④ 필드는 식별자·제목·상태·단계·일자·조건명·중재명·등록 인원만(요약문 등 "
        "서술 텍스트 미수집)으로 한정했습니다. 한국어 표시명·상장 라벨(거래소·종목코드)은 Mulmit이 붙인 참고 라벨(2026-08-22 확인)입니다."
    ),
    "en": (
        "From the ClinicalTrials.gov source Mulmit keeps only: ① studies whose lead sponsor matches one of 34 watchlist sponsors, ② the 25 "
        "most recently updated studies per sponsor, ③ for the recent-activity table, interventional Phase 2/3 studies updated in the last "
        "14 days (at most 8 per sponsor), ④ a field subset (identifiers, title, status, phase, dates, condition and intervention names, enrollment — no narrative "
        "text). Korean display names and listing labels (exchange, ticker) are Mulmit's own reference labels (checked 2026-08-22)."
    ),
}

_TRIALS_METHOD = {
    "ko": (
        "상태·단계·일자는 ClinicalTrials.gov 등록값 그대로입니다. 배지: '결과 게시' = 결과 최초 게시일 30일 내, '중단' = TERMINATED·WITHDRAWN·"
        "SUSPENDED(등록된 사유 병기), '완료' = COMPLETED, '신규' = 시작일 30일 내이며 모집 중. 부분 날짜(예: 2027-02)는 그대로 표시합니다."
    ),
    "en": (
        "Status, phase and dates are the registered ClinicalTrials.gov values. Badges: 'results posted' = results first posted within 30 days, "
        "'stopped' = TERMINATED/WITHDRAWN/SUSPENDED (registered reason shown), 'completed' = COMPLETED, 'new' = started within 30 days and "
        "recruiting. Partial dates (e.g. 2027-02) are shown as registered."
    ),
}

_TRIALS_DISCLAIMER = {
    "ko": (
        "임상 등록 정보이며 결과의 성패·승인 가능성·주가와의 관계를 말하지 않습니다. 스폰서가 직접 등록한 내용으로 ClinicalTrials.gov도 "
        "정확성을 보증하지 않습니다. 투자 권유가 아닙니다."
    ),
    "en": (
        "Registry information only; it says nothing about trial outcomes, approval odds or share prices. Sponsors register these records "
        "themselves and ClinicalTrials.gov makes no warranty as to accuracy. Not a recommendation."
    ),
}


def _sponsor_meta(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": spec["id"],
        "name": spec["name"],
        "country": spec.get("country"),
        "listing": spec.get("listing"),
        "note": spec.get("note"),
    }


def build_bio_trials(now: dt.datetime | None = None) -> dict[str, Any]:
    if not data_rights.clinicaltrials_serving_enabled():
        raise BioUnavailable("disabled")
    blob = _load_cached(TRIALS_CACHE_KEY)
    sponsors = blob.get("sponsors") if isinstance(blob, dict) else None
    if not isinstance(sponsors, list) or not sponsors:
        raise BioUnavailable("collecting")
    moment = now or dt.datetime.now(dt.UTC)
    today = moment.astimezone(dt.UTC).date()
    fetched_at = _parse_iso(blob.get("fetched_at"))
    age = (moment - fetched_at).total_seconds() if fetched_at else None
    version = blob.get("version") if isinstance(blob.get("version"), dict) else {}
    processed_at = version.get("data_timestamp")

    watchlist: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    errors = 0
    for entry in sponsors:
        if not isinstance(entry, dict):
            continue
        spec = WATCHLIST_BY_ID.get(entry.get("id"))
        if spec is None:
            continue
        studies = [s for s in (entry.get("studies") or []) if isinstance(s, dict)]
        interventional = [s for s in studies if s.get("study_type") == "INTERVENTIONAL"]
        watched = [s for s in interventional if set(s.get("phases") or []) & WATCH_PHASES]
        if entry.get("error"):
            errors += 1
        watchlist.append({
            **_sponsor_meta(spec),
            "query": spec["query"],
            "error": entry.get("error"),
            "latest_update": studies[0].get("last_update_post") if studies else None,
            "counts": {
                "registered_total": entry.get("total_count"),
                "sample": len(studies),
                "phase3_in_sample": sum(1 for s in interventional if "PHASE3" in (s.get("phases") or [])),
                "recruiting_in_sample": sum(1 for s in interventional if s.get("status") in RECRUITING_STATUSES),
                "recent_watched": 0,
            },
        })
        for study in watched:
            if watchlist[-1]["counts"]["recent_watched"] >= PER_SPONSOR_CAP:
                break
            if not _within(study.get("last_update_post"), today, RECENT_DAYS):
                continue
            status = study.get("status")
            flags = {
                "results_posted": _within(study.get("results_first_post"), today, RESULTS_RECENT_DAYS),
                "stopped": status in STOPPED_STATUSES,
                "completed": status == "COMPLETED",
                "new_start": status in RECRUITING_STATUSES and _within(study.get("start"), today, NEW_START_DAYS),
            }
            recent.append({**study, "sponsor": _sponsor_meta(spec), "flags": flags})
            watchlist[-1]["counts"]["recent_watched"] += 1
    recent.sort(key=lambda row: (row.get("last_update_post") or "", row.get("nct_id") or ""), reverse=True)
    pubmed_blob = _load_cached(PUBMED_CACHE_KEY) if data_rights.pubmed_serving_enabled() else None
    for row in recent:
        row["publications"] = _publications_for(pubmed_blob, row.get("nct_id"))

    return {
        "generated_at": _iso_utc(),
        "as_of": blob.get("fetched_at"),
        "processed_at": processed_at,
        "processed_date": str(processed_at)[:10] if processed_at else None,
        "api_version": version.get("api_version"),
        "window_days": RECENT_DAYS,
        "limits": {"per_sponsor": PER_SPONSOR_CAP, "total": RECENT_LIMIT, "sample_per_sponsor": config.CLINICALTRIALS_PAGE_SIZE},
        "watchlist": watchlist,
        "recent": recent[:RECENT_LIMIT],
        "totals": {"sponsors": len(watchlist), "recent": len(recent), "sponsors_with_errors": errors},
        "pubmed": _pubmed_block(pubmed_blob),
        "freshness": {
            "status": "stale" if age is None or age > TRIALS_STALE_AFTER_SECONDS else "fresh",
            "fetched_at": blob.get("fetched_at"),
            "age_seconds": round(age, 1) if age is not None else None,
            "cadence": f"ingest refresh every {config.CLINICALTRIALS_MAX_AGE}s; ClinicalTrials.gov updates daily",
            "stale_after_seconds": TRIALS_STALE_AFTER_SECONDS,
        },
        "attribution": {
            "text": f"Source: {ct.ATTRIBUTION}",
            "url": ct.SITE_URL,
            "processed_date": str(processed_at)[:10] if processed_at else None,
            "placement": "adjacent_to_value",
            "required": True,
            "terms_url": ct.TERMS_URL,
        },
        "modifications": _TRIALS_MODIFICATIONS,
        "source": {
            "provider": ct.PROVIDER_ID,
            "provider_name": ct.ATTRIBUTION,
            "publisher": ct.PUBLISHER,
            "url": ct.SITE_URL,
            "api_url": ct.API_URL,
            "read_path": "stored_blob",
        },
        "rights": {
            "status": "public_us_government_database",
            "evidence": ct.TERMS_QUOTE,
            "terms_url": ct.TERMS_URL,
            "notice": (
                "Attributed to ClinicalTrials.gov, refreshed on a fixed cadence, shown with the date ClinicalTrials.gov "
                "processed the data, and with Mulmit's modifications stated; no proprietary right is asserted."
            ),
        },
        "methodology": _TRIALS_METHOD,
        "disclaimer": _TRIALS_DISCLAIMER,
    }


# --- openFDA lane --------------------------------------------------------------

def refresh_bio_fda(*, force: bool = False, provider: Any | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Ingest lane: ORIG approvals inside the trailing window, a page or few per day."""
    if not data_rights.openfda_ingest_enabled():
        return {"skipped": "disabled"}
    if not force and store.load_report(FDA_CACHE_KEY, config.OPENFDA_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or fda.OpenFdaProvider(
        config.OPENFDA_API_KEY or None, timeout=config.OPENFDA_TIMEOUT, retries=config.OPENFDA_RETRIES
    )
    moment = now or dt.datetime.now(dt.UTC)
    end = moment.astimezone(dt.UTC).date()
    start = end - dt.timedelta(days=max(1, config.OPENFDA_WINDOW_DAYS))
    applications: list[dict[str, Any]] = []
    first = client.fetch_original_approvals(start, end, limit=fda.DEFAULT_LIMIT)
    applications.extend(first.get("applications") or [])
    total = first.get("total") if isinstance(first.get("total"), int) else None
    pages = 1
    while total is not None and pages * fda.DEFAULT_LIMIT < total and pages < FDA_MAX_PAGES:
        page = client.fetch_original_approvals(start, end, limit=fda.DEFAULT_LIMIT, skip=pages * fda.DEFAULT_LIMIT)
        applications.extend(page.get("applications") or [])
        pages += 1
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in applications:
        number = row.get("application_number")
        if number in seen:
            continue
        seen.add(number)
        unique.append(row)
    unique.sort(key=lambda row: (row.get("approved_on") or "", row.get("application_number") or ""), reverse=True)
    store.save_report(
        FDA_CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": first.get("fetched_at") or moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "publisher_last_updated": first.get("last_updated"),
            "publisher_total": total,
            "publisher_disclaimer": first.get("disclaimer"),
            "applications": unique,
        },
    )
    clear_cache()
    return {"updated": len(unique), "pages": pages, "publisher_last_updated": first.get("last_updated")}


_FDA_METHOD = {
    "ko": (
        "openFDA drug/drugsfda에서 제출 유형 ORIG·상태 AP(원 신청 승인)인 건만, 승인일이 최근 창 안인 신청을 모았습니다. 신청번호 접두로 "
        "NDA(신약)·BLA(바이오의약품)·ANDA(제네릭)를 나누고, 표에는 NDA·BLA만, 제네릭은 건수만 표시합니다. 브랜드명·성분명은 openFDA 라벨 "
        "필드 → 제품 필드 순으로 채웁니다. 제출 분류(예: TYPE 1 - NEW MOLECULAR ENTITY)와 우선심사 여부는 등록값 그대로입니다."
    ),
    "en": (
        "From openFDA drug/drugsfda: applications with an ORIG submission approved (AP) inside the trailing window. Application-number "
        "prefixes split NDA (new drugs), BLA (biologics) and ANDA (generics); the table lists NDA/BLA, generics as a count. Brand and "
        "generic names come from the openFDA label fields, then the product fields. Submission class (e.g. TYPE 1 - NEW MOLECULAR ENTITY) "
        "and review priority are the registered values."
    ),
}

_FDA_DISCLAIMER = {
    "ko": (
        "openFDA 고지: \"Do not rely on openFDA to make decisions regarding medical care … you should assume all results are unvalidated.\" "
        "승인 목록은 규제 기록이며 매출·주가와의 관계를 말하지 않습니다. 투자 권유가 아닙니다."
    ),
    "en": (
        "openFDA notice: \"Do not rely on openFDA to make decisions regarding medical care … you should assume all results are unvalidated.\" "
        "An approval list is a regulatory record; it says nothing about sales or share prices. Not a recommendation."
    ),
}


def build_bio_fda(now: dt.datetime | None = None) -> dict[str, Any]:
    if not data_rights.openfda_serving_enabled():
        raise BioUnavailable("disabled")
    blob = _load_cached(FDA_CACHE_KEY)
    applications = blob.get("applications") if isinstance(blob, dict) else None
    if not isinstance(applications, list):
        raise BioUnavailable("collecting")
    moment = now or dt.datetime.now(dt.UTC)
    fetched_at = _parse_iso(blob.get("fetched_at"))
    age = (moment - fetched_at).total_seconds() if fetched_at else None
    rows = [row for row in applications if isinstance(row, dict)]
    novel = [row for row in rows if row.get("application_type") in ("NDA", "BLA")]
    counts = {
        "nda": sum(1 for row in rows if row.get("application_type") == "NDA"),
        "bla": sum(1 for row in rows if row.get("application_type") == "BLA"),
        "anda": sum(1 for row in rows if row.get("application_type") == "ANDA"),
        "other": sum(1 for row in rows if row.get("application_type") not in ("NDA", "BLA", "ANDA")),
        "priority_review": sum(1 for row in novel if str(row.get("review_priority") or "").upper() == "PRIORITY"),
        "new_molecular_entity": sum(1 for row in novel if "NEW MOLECULAR ENTITY" in str(row.get("class_description") or "").upper()),
    }
    return {
        "generated_at": _iso_utc(),
        "as_of": blob.get("fetched_at"),
        "publisher_last_updated": blob.get("publisher_last_updated"),
        "window": blob.get("window"),
        "approvals": novel,
        "generics": {"count": counts["anda"], "basis": "ANDA original approvals in the same window (not listed individually)"},
        "counts": counts,
        "totals": {"applications": len(rows), "publisher_total": blob.get("publisher_total")},
        "freshness": {
            "status": "stale" if age is None or age > FDA_STALE_AFTER_SECONDS else "fresh",
            "fetched_at": blob.get("fetched_at"),
            "age_seconds": round(age, 1) if age is not None else None,
            "cadence": f"ingest refresh every {config.OPENFDA_MAX_AGE}s; openFDA updates the dataset periodically",
            "stale_after_seconds": FDA_STALE_AFTER_SECONDS,
        },
        "attribution": {
            "text": fda.ATTRIBUTION,
            "url": fda.SITE_URL,
            "license_url": fda.LICENSE_URL,
            "placement": "adjacent_to_value",
            "required": False,
            "publisher_disclaimer": blob.get("publisher_disclaimer"),
        },
        "source": {
            "provider": fda.PROVIDER_ID,
            "provider_name": "openFDA",
            "publisher": fda.PUBLISHER,
            "url": fda.SITE_URL,
            "api_url": fda.API_URL,
            "read_path": "stored_blob",
        },
        "rights": {
            "status": "public_domain_cc0",
            "evidence": fda.LICENSE_QUOTE,
            "terms_url": fda.TERMS_URL,
            "license_url": fda.LICENSE_URL,
            "notice": "Public domain (CC0 1.0); credit given as openFDA asks; the publisher's disclaimer is relayed with the values.",
        },
        "methodology": _FDA_METHOD,
        "disclaimer": _FDA_DISCLAIMER,
    }


# --- PubMed lane (publications linked to watched trials) -------------------------

PUBMED_CACHE_KEY = "bio_pubmed_v1"
PUBMED_KEEP_DAYS = 60
PUBMED_TOP = 3
ADCOMM_CACHE_KEY = "bio_adcomm_v1"
ADCOMM_LOOKBACK_DAYS = 240
ADCOMM_PAST_DAYS = 30
ADCOMM_MAX_PAGES = 3
ADCOMM_STALE_AFTER_SECONDS = 60 * 60 * 24
NEW_YORK = ZoneInfo("America/New_York")


def pubmed_window_open(now: dt.datetime | None = None) -> bool:
    """NCBI asks that large jobs run on weekends or between 9 PM and 5 AM Eastern; the daily pass honours that."""
    moment = (now or dt.datetime.now(dt.UTC)).astimezone(NEW_YORK)
    return moment.weekday() >= 5 or moment.hour >= 21 or moment.hour < 5


def _watched_recent_ncts(trials_blob: dict[str, Any], today: dt.date) -> list[str]:
    """The same rows the trials table shows (interventional Phase 2/3, last 14 days, per-sponsor cap), newest first."""
    rows: list[tuple[str, str]] = []
    for entry in trials_blob.get("sponsors") or []:
        if not isinstance(entry, dict) or entry.get("id") not in WATCHLIST_BY_ID:
            continue
        kept = 0
        for study in entry.get("studies") or []:
            if kept >= PER_SPONSOR_CAP:
                break
            if not isinstance(study, dict) or study.get("study_type") != "INTERVENTIONAL":
                continue
            if not set(study.get("phases") or []) & WATCH_PHASES:
                continue
            if not _within(study.get("last_update_post"), today, RECENT_DAYS):
                continue
            nct = study.get("nct_id")
            if isinstance(nct, str) and nct:
                rows.append((study.get("last_update_post") or "", nct))
                kept += 1
    rows.sort(reverse=True)
    seen: set[str] = set()
    ordered: list[str] = []
    for _, nct in rows:
        if nct not in seen:
            seen.add(nct)
            ordered.append(nct)
    return ordered[:RECENT_LIMIT]


def refresh_bio_pubmed(*, force: bool = False, provider: Any | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Ingest lane: one paced esearch per watched trial plus batched esummary calls — daily, in NCBI's off-peak window."""
    if not data_rights.pubmed_ingest_enabled():
        return {"skipped": "disabled"}
    moment = now or dt.datetime.now(dt.UTC)
    if not force and store.load_report(PUBMED_CACHE_KEY, config.PUBMED_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    if not force and config.PUBMED_OFFPEAK_ONLY and not pubmed_window_open(moment):
        return {"skipped": "offpeak_window"}
    trials = store.load_report(TRIALS_CACHE_KEY, SERVE_TTL_SECONDS)
    if not isinstance(trials, dict) or not trials.get("sponsors"):
        return {"skipped": "no_trials_blob"}
    today = moment.astimezone(dt.UTC).date()
    ncts = _watched_recent_ncts(trials, today)
    client = provider or pm.PubMedProvider(
        tool=config.NCBI_TOOL,
        email=config.NCBI_EMAIL or None,
        api_key=config.NCBI_API_KEY or None,
        timeout=config.PUBMED_TIMEOUT,
        retries=config.PUBMED_RETRIES,
    )
    previous = store.load_report(PUBMED_CACHE_KEY, HISTORY_READ_TTL_SECONDS) or {}
    previous_studies = previous.get("studies") if isinstance(previous.get("studies"), dict) else {}
    studies: dict[str, dict[str, Any]] = {}
    queried = failed = 0
    needed: set[str] = set()
    for index, nct in enumerate(ncts):
        if index and config.PUBMED_PACE_SECONDS > 0:
            _sleep(config.PUBMED_PACE_SECONDS)
        try:
            result = client.search_nct(nct, retmax=PUBMED_TOP)
        except RateLimited:
            failed += 1
            log.warning("PubMed rate limit — stopping this pass after %d searches", index)
            break
        except DataUnavailable as exc:
            failed += 1
            log.warning("PubMed search for %s failed: %s", nct, exc)
            continue
        queried += 1
        studies[nct] = {"count": result.get("count", 0), "pmids": list(result.get("pmids") or []), "articles": [], "as_of": result.get("fetched_at")}
        needed.update(studies[nct]["pmids"])
    articles: dict[str, dict[str, Any]] = {}
    batch = sorted(needed)
    for start in range(0, len(batch), pm.MAX_SUMMARY_IDS):
        if config.PUBMED_PACE_SECONDS > 0:
            _sleep(config.PUBMED_PACE_SECONDS)
        try:
            for article in client.summaries(batch[start:start + pm.MAX_SUMMARY_IDS]):
                articles[article["pmid"]] = article
        except (RateLimited, DataUnavailable) as exc:
            log.warning("PubMed summaries failed: %s", exc)
            break
    for entry in studies.values():
        entry["articles"] = [articles[p] for p in entry["pmids"] if p in articles]
    cutoff = (moment - dt.timedelta(days=PUBMED_KEEP_DAYS)).astimezone(dt.UTC).isoformat().replace("+00:00", "Z")
    carried = 0
    for nct, entry in previous_studies.items():
        if nct not in studies and isinstance(entry, dict) and str(entry.get("as_of") or "") >= cutoff:
            studies[nct] = entry
            carried += 1
    if ncts and queried == 0:
        raise DataUnavailable("PubMed refresh produced no results")
    hits = sum(1 for entry in studies.values() if entry.get("count"))
    store.save_report(
        PUBMED_CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
            "queried": queried,
            "failed": failed,
            "hits": hits,
            "studies": studies,
        },
    )
    clear_cache()
    return {"updated": queried, "failed": failed, "hits": hits, "carried": carried}


_PUBMED_NOTICE = {
    "ko": "PubMed 서지 정보(제목·저널·일자·PMID)만 보여주고 초록은 저작권 문제로 표시하지 않습니다. 등록번호(NCT) 기준 검색이라 누락이 있을 수 있습니다.",
    "en": "PubMed citation metadata only (title, journal, date, PMID); abstracts are not shown for copyright reasons. Matching is by registration number (NCT), so some publications may be missed.",
}


def _pubmed_block(blob: dict[str, Any] | None) -> dict[str, Any]:
    enabled = data_rights.pubmed_serving_enabled()
    block: dict[str, Any] = {
        "status": "disabled" if not enabled else ("ok" if isinstance(blob, dict) and isinstance(blob.get("studies"), dict) else "collecting"),
        "as_of": blob.get("fetched_at") if isinstance(blob, dict) else None,
        "queried": blob.get("queried") if isinstance(blob, dict) else None,
        "hits": blob.get("hits") if isinstance(blob, dict) else None,
        "attribution": {"text": pm.ATTRIBUTION, "url": pm.SITE_URL, "policy_url": pm.POLICY_URL, "placement": "adjacent_to_value"},
        "notice": _PUBMED_NOTICE,
        "rights": {"status": "public_metadata_with_usage_policy", "evidence": pm.POLICY_QUOTE, "policy_url": pm.POLICY_URL,
                    "notice": "Citation metadata only; abstracts never requested; requests identified with tool/email and paced per NCBI guidelines."},
    }
    return block


def _publications_for(blob: dict[str, Any] | None, nct_id: Any) -> dict[str, Any] | None:
    studies = blob.get("studies") if isinstance(blob, dict) else None
    entry = studies.get(nct_id) if isinstance(studies, dict) and isinstance(nct_id, str) else None
    if not isinstance(entry, dict):
        return None
    return {
        "count": entry.get("count"),
        "articles": [a for a in (entry.get("articles") or []) if isinstance(a, dict)][:PUBMED_TOP],
        "search_url": pm.search_page_url(nct_id),
        "as_of": entry.get("as_of"),
    }


# --- FDA advisory committee notices (Federal Register) ----------------------------

def refresh_bio_adcomm(*, force: bool = False, provider: Any | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Ingest lane: FDA advisory-committee meeting notices from the Federal Register API (public domain, unkeyed)."""
    if not data_rights.federal_register_ingest_enabled():
        return {"skipped": "disabled"}
    if not force and store.load_report(ADCOMM_CACHE_KEY, config.ADCOMM_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or fr.FederalRegisterProvider(timeout=config.FEDERAL_REGISTER_TIMEOUT, retries=config.FEDERAL_REGISTER_RETRIES)
    moment = now or dt.datetime.now(dt.UTC)
    since = moment.astimezone(dt.UTC).date() - dt.timedelta(days=ADCOMM_LOOKBACK_DAYS)
    first = client.fetch_fda_meeting_notices(since=since)
    notices = list(first.get("notices") or [])
    total_pages = first.get("total_pages") if isinstance(first.get("total_pages"), int) else 1
    page = 2
    while page <= min(total_pages, ADCOMM_MAX_PAGES):
        notices.extend(client.fetch_fda_meeting_notices(since=since, page=page).get("notices") or [])
        page += 1
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in notices:
        key = str(row.get("document_number") or row.get("url") or row.get("title"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    store.save_report(
        ADCOMM_CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": first.get("fetched_at") or moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
            "since": since.isoformat(),
            "publisher_count": first.get("count"),
            "notices": unique,
        },
    )
    clear_cache()
    return {"updated": len(unique), "pages": page - 1, "publisher_count": first.get("count")}


_ADCOMM_METHOD = {
    "ko": (
        "Federal Register API에서 FDA(기관)·Notice(문서 유형)·\"advisory committee\" 검색으로 최근 240일 공고를 받아 제목에 위원회명과 회의 공고(Notice of "
        "Meeting/Amendment of Notice 등)가 있는 건만 남깁니다. 회의일은 공고의 DATES 단락에서 '월 일, 연도' 패턴을 추출한 값이며, 날짜가 없는 공고(정정·서류 "
        "안내)는 별도로 둡니다. 위원회명은 제목의 첫 구절입니다."
    ),
    "en": (
        "From the Federal Register API (agency FDA, type Notice, term \"advisory committee\", last 240 days) Mulmit keeps notices whose title names a "
        "committee and announces or amends a meeting. Meeting dates are extracted from the notice's DATES paragraph ('Month D, YYYY'); notices without "
        "a date (amendments, docket notes) are listed separately. The committee name is the first clause of the title."
    ),
}

_ADCOMM_DISCLAIMER = {
    "ko": "회의 공고는 일정이며 자문위 결론·승인 여부·주가와의 관계를 말하지 않습니다. 최종 일정·의제는 링크된 공고와 FDA 안내를 따릅니다. 투자 권유가 아닙니다.",
    "en": "A meeting notice is a schedule; it says nothing about the committee's conclusion, approval or share prices. The linked notice and FDA's own page govern the final agenda. Not a recommendation.",
}


def build_bio_adcomm(now: dt.datetime | None = None) -> dict[str, Any]:
    if not data_rights.federal_register_serving_enabled():
        raise BioUnavailable("disabled")
    blob = _load_cached(ADCOMM_CACHE_KEY)
    notices = blob.get("notices") if isinstance(blob, dict) else None
    if not isinstance(notices, list):
        raise BioUnavailable("collecting")
    moment = now or dt.datetime.now(dt.UTC)
    today = moment.astimezone(dt.UTC).date()
    fetched_at = _parse_iso(blob.get("fetched_at"))
    age = (moment - fetched_at).total_seconds() if fetched_at else None
    upcoming: list[dict[str, Any]] = []
    past: list[dict[str, Any]] = []
    undated: list[dict[str, Any]] = []
    for row in notices:
        if not isinstance(row, dict):
            continue
        start = _parse_date(row.get("meeting_start"))
        end = _parse_date(row.get("meeting_end")) or start
        if start is None:
            undated.append({**row, "status": "undated"})
        elif end is not None and end < today:
            if (today - end).days <= ADCOMM_PAST_DAYS:
                past.append({**row, "status": "past"})
        else:
            upcoming.append({**row, "status": "upcoming", "days_until": (start - today).days})
    upcoming.sort(key=lambda r: (r.get("meeting_start") or "", r.get("publication_date") or ""))
    past.sort(key=lambda r: (r.get("meeting_start") or "", r.get("publication_date") or ""), reverse=True)
    undated.sort(key=lambda r: r.get("publication_date") or "", reverse=True)
    return {
        "generated_at": _iso_utc(),
        "as_of": blob.get("fetched_at"),
        "since": blob.get("since"),
        "upcoming": upcoming,
        "recent_past": past,
        "undated": undated[:10],
        "next_meeting": upcoming[0] if upcoming else None,
        "totals": {"upcoming": len(upcoming), "recent_past": len(past), "undated": len(undated), "publisher_count": blob.get("publisher_count")},
        "freshness": {
            "status": "stale" if age is None or age > ADCOMM_STALE_AFTER_SECONDS else "fresh",
            "fetched_at": blob.get("fetched_at"),
            "age_seconds": round(age, 1) if age is not None else None,
            "cadence": f"ingest refresh every {config.ADCOMM_MAX_AGE}s; the Federal Register publishes each business day",
            "stale_after_seconds": ADCOMM_STALE_AFTER_SECONDS,
        },
        "attribution": {
            "text": fr.ATTRIBUTION,
            "url": fr.SITE_URL,
            "developer_url": fr.DEVELOPER_URL,
            "placement": "adjacent_to_value",
            "required": False,
            "restriction": "no official NARA or OFR logos or seals",
        },
        "source": {
            "provider": fr.PROVIDER_ID,
            "provider_name": "Federal Register",
            "publisher": fr.PUBLISHER,
            "url": fr.SITE_URL,
            "api_url": fr.API_URL,
            "read_path": "stored_blob",
        },
        "rights": {
            "status": "us_government_work_public_domain",
            "evidence": fr.USAGE_QUOTE,
            "terms_url": fr.DEVELOPER_URL,
            "notice": "U.S. Government publication (17 U.S.C. §105); titles, dates and links relayed with attribution; no logos or seals.",
        },
        "methodology": _ADCOMM_METHOD,
        "disclaimer": _ADCOMM_DISCLAIMER,
    }


# --- MFDS drug product permits (data.go.kr) --------------------------------------

MFDS_CACHE_KEY = "bio_mfds_permits_v1"
MFDS_STALE_AFTER_SECONDS = 60 * 60 * 36
MFDS_ROW_LIMIT = 300
MFDS_NOTABLE_LIMIT = 80
MFDS_MAX_PAGES_PER_DAY = 5
SEOUL = ZoneInfo("Asia/Seoul")


def refresh_bio_mfds(*, force: bool = False, provider: Any | None = None, now: dt.datetime | None = None) -> dict[str, Any]:
    """Ingest lane: one keyed call per KST day of the trailing window (plus paging on busy days), daily."""
    if not data_rights.mfds_serving_enabled():
        return {"skipped": "disabled"}
    if not data_rights.mfds_ingest_enabled():
        return {"skipped": "not_configured"}
    if not force and store.load_report(MFDS_CACHE_KEY, config.MFDS_MAX_AGE) is not None:
        return {"skipped": "fresh"}
    client = provider or mf.MfdsProvider(config.MFDS_API_KEY, timeout=config.MFDS_TIMEOUT, retries=config.MFDS_RETRIES)
    moment = now or dt.datetime.now(dt.UTC)
    today = moment.astimezone(SEOUL).date()
    days = [today - dt.timedelta(days=offset) for offset in range(max(1, config.MFDS_WINDOW_DAYS))]
    permits: list[dict[str, Any]] = []
    per_day: dict[str, int] = {}
    failed = 0
    stopped = False
    for index, day in enumerate(days):
        if index and config.MFDS_PACE_SECONDS > 0:
            _sleep(config.MFDS_PACE_SECONDS)
        try:
            page = client.fetch_permits_on(day)
            rows = list(page.get("permits") or [])
            total = page.get("total_count")
            page_no = 2
            while isinstance(total, int) and len(rows) < total and page_no <= MFDS_MAX_PAGES_PER_DAY:
                if config.MFDS_PACE_SECONDS > 0:
                    _sleep(config.MFDS_PACE_SECONDS)
                rows.extend(client.fetch_permits_on(day, page=page_no).get("permits") or [])
                page_no += 1
        except RateLimited:
            failed += 1
            stopped = True
            log.warning("MFDS API rate limit — stopping this pass after %d days", index)
            break
        except DataUnavailable as exc:
            failed += 1
            log.warning("MFDS permits for %s failed: %s", day.isoformat(), exc)
            continue
        per_day[day.isoformat()] = len(rows)
        permits.extend(rows)
    if not per_day:
        raise DataUnavailable("MFDS refresh produced no days")
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in permits:
        seq = str(row.get("item_seq") or "")
        if seq in seen:
            continue
        seen.add(seq)
        unique.append(row)
    unique.sort(key=lambda r: (r.get("permit_date") or "", r.get("item_seq") or ""), reverse=True)
    store.save_report(
        MFDS_CACHE_KEY,
        {
            "generated_at": _iso_utc(),
            "fetched_at": moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
            "window": {"start": days[-1].isoformat(), "end": days[0].isoformat()},
            "days": per_day,
            "failed_days": failed,
            "stopped_early": stopped,
            "permits": unique,
        },
    )
    clear_cache()
    return {"updated": len(unique), "days": len(per_day), "failed_days": failed}


_MFDS_METHOD = {
    "ko": (
        "공공데이터포털 식품의약품안전처 의약품 제품 허가정보(getDrugPrdtPrmsnDtlInq06)를 허가일자(item_permit_date)별로 최근 30일(한국시간) 하루씩 조회해 "
        "모았습니다. 허가/신고·전문/일반·신약 구분·희귀의약품 여부·주성분은 등록값 그대로이며, '주목'은 허가(신고 제외)된 전문의약품 또는 신약·희귀의약품입니다. "
        "주성분의 성분코드([M…])는 표시에서 제거했습니다."
    ),
    "en": (
        "Drug product permits from the Ministry of Food and Drug Safety dataset on data.go.kr (getDrugPrdtPrmsnDtlInq06), queried one KST day at a time "
        "over the trailing 30 days by permit date. Permit/notification, prescription/OTC, new-drug class, orphan flag and main ingredients are the registered "
        "values; 'notable' means a prescription product granted a permit (not a notification) or a new or orphan drug. Ingredient codes ([M…]) are dropped."
    ),
}

_MFDS_DISCLAIMER = {
    "ko": "품목허가 목록은 규제 기록이며 매출·주가와의 관계를 말하지 않습니다. 제네릭·보충 허가가 대부분이고, 신약 여부는 식약처 구분을 따릅니다. 투자 권유가 아닙니다.",
    "en": "A permit list is a regulatory record; it says nothing about sales or share prices. Most entries are generics or supplements; new-drug status follows the MFDS classification. Not a recommendation.",
}


def build_bio_mfds(now: dt.datetime | None = None) -> dict[str, Any]:
    if not data_rights.mfds_serving_enabled():
        raise BioUnavailable("disabled")
    blob = _load_cached(MFDS_CACHE_KEY)
    permits = blob.get("permits") if isinstance(blob, dict) else None
    if not isinstance(permits, list):
        raise BioUnavailable("collecting")
    moment = now or dt.datetime.now(dt.UTC)
    fetched_at = _parse_iso(blob.get("fetched_at"))
    age = (moment - fetched_at).total_seconds() if fetched_at else None
    rows = [row for row in permits if isinstance(row, dict)]
    counts = {
        "total": len(rows),
        "permit": sum(1 for r in rows if r.get("permit_kind") == "허가"),
        "report": sum(1 for r in rows if r.get("permit_kind") == "신고"),
        "rx": sum(1 for r in rows if r.get("etc_otc") == "전문의약품"),
        "otc": sum(1 for r in rows if r.get("etc_otc") == "일반의약품"),
        "new_drug": sum(1 for r in rows if r.get("newdrug_class")),
        "rare": sum(1 for r in rows if r.get("rare")),
    }
    notable = [
        r for r in rows
        if r.get("newdrug_class") or r.get("rare") or (r.get("permit_kind") == "허가" and r.get("etc_otc") == "전문의약품")
    ]
    return {
        "generated_at": _iso_utc(),
        "as_of": blob.get("fetched_at"),
        "window": blob.get("window"),
        "days": blob.get("days"),
        "counts": counts,
        "permits": rows[:MFDS_ROW_LIMIT],
        "notable": notable[:MFDS_NOTABLE_LIMIT],
        "totals": {"permits": len(rows), "days": len(blob.get("days") or {}), "failed_days": blob.get("failed_days"), "stopped_early": blob.get("stopped_early")},
        "freshness": {
            "status": "stale" if age is None or age > MFDS_STALE_AFTER_SECONDS else "fresh",
            "fetched_at": blob.get("fetched_at"),
            "age_seconds": round(age, 1) if age is not None else None,
            "cadence": f"ingest refresh every {config.MFDS_MAX_AGE}s; one call per day of the {config.MFDS_WINDOW_DAYS}-day window",
            "stale_after_seconds": MFDS_STALE_AFTER_SECONDS,
        },
        "attribution": {
            "text": mf.ATTRIBUTION,
            "text_en": mf.ATTRIBUTION_EN,
            "url": mf.DATASET_URL,
            "placement": "adjacent_to_value",
            "required": True,
        },
        "source": {
            "provider": mf.PROVIDER_ID,
            "provider_name": "식품의약품안전처 (공공데이터포털)",
            "publisher": mf.PUBLISHER,
            "url": mf.DATASET_URL,
            "api_url": f"{mf.API_BASE}/{mf.DETAIL_ENDPOINT}",
            "read_path": "stored_blob",
        },
        "rights": {
            "status": "public_data_portal_unrestricted",
            "evidence": mf.LICENSE_QUOTE,
            "terms_url": mf.DATASET_URL,
            "notice": "data.go.kr dataset with 이용허락범위 제한 없음; source shown with the values; registered values relayed without interpretation.",
        },
        "methodology": _MFDS_METHOD,
        "disclaimer": _MFDS_DISCLAIMER,
    }
