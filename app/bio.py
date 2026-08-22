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

from . import config, data_rights, store
from .providers import clinicaltrials as ct
from .providers import openfda as fda
from .providers.base import DataUnavailable, RateLimited

log = logging.getLogger(__name__)

TRIALS_CACHE_KEY = "bio_trials_v1"
FDA_CACHE_KEY = "bio_fda_approvals_v1"
SERVE_TTL_SECONDS = 60 * 60 * 48
TRIALS_STALE_AFTER_SECONDS = 60 * 60 * 12
FDA_STALE_AFTER_SECONDS = 60 * 60 * 36
LOAD_CACHE_SECONDS = 60.0
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
