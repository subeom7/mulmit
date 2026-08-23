"""Bio section — ClinicalTrials.gov watchlist lane and openFDA approvals lane: parsing, refresh, serving, gates."""

from __future__ import annotations

import datetime as dt
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import bio, config, data_rights, ingest
from app.main import app
from app.providers import clinicaltrials as ct
from app.providers import openfda as fda
from app.providers.base import DataUnavailable, RateLimited

NOW = dt.datetime(2026, 8, 22, 6, 0, tzinfo=dt.UTC)


def _study(nct: str, *, status: str = "RECRUITING", phases: list[str] | None = None, study_type: str = "INTERVENTIONAL",
           updated: str = "2026-08-20", start: str = "2026-08-01", primary: str = "2027-02", why: str | None = None,
           results: str | None = None, sponsor: str = "Celltrion") -> dict[str, Any]:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": f"Study {nct}"},
            "statusModule": {
                "overallStatus": status, "whyStopped": why,
                "startDateStruct": {"date": start}, "primaryCompletionDateStruct": {"date": primary, "type": "ESTIMATED"},
                "lastUpdatePostDateStruct": {"date": updated}, "lastUpdateSubmitDate": updated, "statusVerifiedDate": "2026-08",
                **({"resultsFirstPostDateStruct": {"date": results}} if results else {}),
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
            "conditionsModule": {"conditions": ["Psoriasis", "Arthritis"]},
            "designModule": {"studyType": study_type, "phases": phases if phases is not None else ["PHASE3"], "enrollmentInfo": {"count": 225}},
            "armsInterventionsModule": {"interventions": [{"name": "CT-P51"}, {"name": "Keytruda"}]},
        }
    }


CT_RAW = {"totalCount": 84, "studies": [
    _study("NCT00000001", status="ACTIVE_NOT_RECRUITING", phases=["PHASE3"], updated="2026-08-20"),
    _study("NCT00000002", status="TERMINATED", phases=["PHASE2", "PHASE3"], updated="2026-08-15", why="Business decision"),
    _study("NCT00000003", status="COMPLETED", phases=["PHASE1"], updated="2026-08-21"),              # phase 1 → not in the recent table
    _study("NCT00000004", status="RECRUITING", phases=["PHASE3"], study_type="OBSERVATIONAL", updated="2026-08-21"),  # observational → excluded
    _study("NCT00000005", status="RECRUITING", phases=["PHASE2"], updated="2026-07-01"),             # too old
    _study("NCT00000006", status="COMPLETED", phases=["PHASE3"], updated="2026-08-18", results="2026-08-18"),
]}


class FakeCt:
    def __init__(self, *, fail: set[str] = frozenset(), rate_limit: set[str] = frozenset()) -> None:
        self.calls: list[str] = []
        self.fail = set(fail)
        self.rate_limit = set(rate_limit)

    def fetch_version(self) -> dict[str, Any]:
        return {"fetched_at": "2026-08-22T06:00:00Z", "api_version": "2.0.5", "data_timestamp": "2026-08-21T09:00:05"}

    def fetch_lead_sponsor(self, query: str, *, page_size: int | None = None) -> dict[str, Any]:
        self.calls.append(query)
        if query in self.rate_limit:
            raise RateLimited("slow down")
        if query in self.fail:
            raise DataUnavailable("down")
        parsed = ct.parse_studies(CT_RAW)
        parsed["fetched_at"] = "2026-08-22T06:00:00Z"
        return parsed


def _fda_app(number: str, sponsor: str, brand: str, *, approved: str, sub_type: str = "ORIG", status: str = "AP", priority: str = "STANDARD", klass: str | None = "TYPE 1 - NEW MOLECULAR ENTITY") -> dict[str, Any]:
    return {
        "application_number": number, "sponsor_name": sponsor,
        "openfda": {"brand_name": [brand], "generic_name": [f"{brand.lower()}ib"], "product_type": ["HUMAN PRESCRIPTION DRUG"]},
        "products": [{"brand_name": brand, "dosage_form": "TABLET", "route": "ORAL", "active_ingredients": [{"name": f"{brand.lower()}ib", "strength": "10MG"}]}],
        "submissions": [
            {"submission_type": sub_type, "submission_number": "1", "submission_status": status, "submission_status_date": approved, "review_priority": priority, "submission_class_code": "TYPE1" if klass else None, "submission_class_code_description": klass},
            {"submission_type": "SUPPL", "submission_number": "5", "submission_status": "AP", "submission_status_date": "20260820", "submission_class_code": "LABELING", "submission_class_code_description": "Labeling"},
        ],
    }


FDA_RAW = {
    "meta": {"disclaimer": "Do not rely on openFDA …", "last_updated": "2026-08-21", "results": {"skip": 0, "limit": 100, "total": 3}},
    "results": [
        _fda_app("NDA219001", "ACME PHARMA", "Acmezia", approved="20260818", priority="PRIORITY"),
        _fda_app("BLA761999", "BIOCO", "Biocomab", approved="20260805", klass="BLA"),
        _fda_app("ANDA219555", "GENERIX", "Rosuvastatin", approved="20260810", klass=None),
        _fda_app("NDA200000", "OLD CO", "Oldrug", approved="20150101"),  # ORIG approval outside the window → dropped
    ],
}


class FakeFda:
    def __init__(self, *, total: int | None = 3) -> None:
        self.calls: list[tuple[int, int]] = []
        self.total = total

    def fetch_original_approvals(self, start: dt.date, end: dt.date, *, limit: int = 100, skip: int = 0) -> dict[str, Any]:
        self.calls.append((limit, skip))
        parsed = fda.parse_applications(FDA_RAW, start=start, end=end)
        parsed["total"] = self.total
        parsed["fetched_at"] = "2026-08-22T06:00:00Z"
        return parsed


@pytest.fixture
def bio_on(db, monkeypatch):
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CLINICALTRIALS_ENABLED", True)
    monkeypatch.setattr(config, "OPENFDA_ENABLED", True)
    monkeypatch.setattr(config, "CLINICALTRIALS_PACE_SECONDS", 0.0)
    small = [spec for spec in bio.WATCHLIST if spec["id"] in ("celltrion", "pfizer", "samsung_bioepis")]
    monkeypatch.setattr(bio, "WATCHLIST", small)
    monkeypatch.setattr(bio, "WATCHLIST_BY_ID", {spec["id"]: spec for spec in small})
    bio.clear_cache()
    yield
    bio.clear_cache()


# --- providers ----------------------------------------------------------------

def test_parse_study_flattens_structured_fields_and_partial_dates():
    row = ct.parse_study(CT_RAW["studies"][1])
    assert row["nct_id"] == "NCT00000002" and row["status"] == "TERMINATED" and row["why_stopped"] == "Business decision"
    assert row["phases"] == ["PHASE2", "PHASE3"] and row["primary_completion"] == "2027-02" and row["enrollment"] == 225
    assert row["interventions"] == ["CT-P51", "Keytruda"] and row["url"] == "https://clinicaltrials.gov/study/NCT00000002"
    assert "briefSummary" not in row and "description" not in row
    parsed = ct.parse_studies(CT_RAW)
    assert parsed["total_count"] == 84 and len(parsed["studies"]) == 6
    assert ct.parse_study({"protocolSection": {"identificationModule": {}}}) is None


def test_ct_provider_queries_lead_sponsor_and_maps_rate_limit():
    seen: list[str] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        seen.append(url)
        if "version" in url:
            return {"apiVersion": "2.0.5", "dataTimestamp": "2026-08-21T09:00:05"}
        if "Throttled" in url:
            raise urllib.error.HTTPError(url, 429, "Too Many", hdrs=None, fp=None)  # type: ignore[arg-type]
        return CT_RAW

    provider = ct.ClinicalTrialsProvider(transport=transport, retries=0, page_size=25)
    assert provider.fetch_version()["data_timestamp"] == "2026-08-21T09:00:05"
    parsed = provider.fetch_lead_sponsor("Merck Sharp & Dohme")
    assert parsed["total_count"] == 84 and parsed["query"] == "Merck Sharp & Dohme"
    assert seen[1].startswith(ct.API_URL + "?") and "query.lead=Merck+Sharp+%26+Dohme" in seen[1] and "pageSize=25" in seen[1]
    assert "BriefSummary" not in seen[1]
    with pytest.raises(RateLimited):
        provider.fetch_lead_sponsor("Throttled")


def test_openfda_parse_keeps_original_approvals_inside_window_and_handles_not_found():
    parsed = fda.parse_applications(FDA_RAW, start=dt.date(2026, 6, 23), end=dt.date(2026, 8, 22))
    numbers = [row["application_number"] for row in parsed["applications"]]
    assert numbers == ["NDA219001", "ANDA219555", "BLA761999"]  # newest first; NDA200000 (2015) dropped
    nda = parsed["applications"][0]
    assert nda["application_type"] == "NDA" and nda["brand_name"] == "Acmezia" and nda["generic_name"] == "acmeziaib"
    assert nda["approved_on"] == "2026-08-18" and nda["review_priority"] == "PRIORITY" and nda["approvals"][0]["class_description"].startswith("TYPE 1")
    assert nda["url"].endswith("ApplNo=219001") and parsed["last_updated"] == "2026-08-21" and parsed["total"] == 3
    empty = fda.parse_applications({"error": {"code": "NOT_FOUND", "message": "No matches found!"}})
    assert empty["applications"] == [] and empty["total"] == 0
    with pytest.raises(DataUnavailable):
        fda.parse_applications({"error": {"code": "BAD_REQUEST", "message": "x"}})


def test_openfda_provider_builds_search_and_treats_404_as_empty():
    seen: list[str] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        seen.append(url)
        if "skip=100" in url:
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)  # type: ignore[arg-type]
        return FDA_RAW

    provider = fda.OpenFdaProvider("k e y", transport=transport, retries=0)
    first = provider.fetch_original_approvals(dt.date(2026, 6, 23), dt.date(2026, 8, 22))
    assert seen[0].startswith(fda.API_URL + "?api_key=k%20e%20y&search=submissions.submission_status:AP+AND+submissions.submission_type:ORIG+AND+submissions.submission_status_date:[20260623+TO+20260822]&limit=100&skip=0")
    assert len(first["applications"]) == 3 and first["window"] == {"start": "2026-06-23", "end": "2026-08-22"}
    second = provider.fetch_original_approvals(dt.date(2026, 6, 23), dt.date(2026, 8, 22), skip=100)
    assert second["applications"] == []


# --- lanes ---------------------------------------------------------------------

def test_trials_refresh_then_build_reports_recent_watched_studies_with_flags(bio_on):
    fake = FakeCt(fail={"Samsung Bioepis"})
    result = bio.refresh_bio_trials(provider=fake, now=NOW)
    assert result == {"updated": 2, "failed": 1, "data_timestamp": "2026-08-21T09:00:05"}
    assert fake.calls == ["Pfizer", "Celltrion", "Samsung Bioepis"]
    assert bio.refresh_bio_trials(provider=fake, now=NOW) == {"skipped": "fresh"}

    payload = bio.build_bio_trials(now=NOW)
    assert payload["processed_date"] == "2026-08-21" and payload["attribution"]["text"] == "Source: ClinicalTrials.gov"
    assert payload["attribution"]["required"] is True and "수정" not in payload["attribution"]["text"]
    assert payload["totals"] == {"sponsors": 3, "recent": 6, "sponsors_with_errors": 1}
    bioepis = next(w for w in payload["watchlist"] if w["id"] == "samsung_bioepis")
    assert bioepis["error"] == "unavailable" and bioepis["listing"] is None and bioepis["note"]["ko"].startswith("삼성바이오로직스")
    celltrion = next(w for w in payload["watchlist"] if w["id"] == "celltrion")
    assert celltrion["listing"] == {"exchange": "KOSPI", "ticker": "068270"}
    assert celltrion["counts"] == {"registered_total": 84, "sample": 6, "phase3_in_sample": 3, "recruiting_in_sample": 1, "recent_watched": 3}
    recent = [row for row in payload["recent"] if row["sponsor"]["id"] == "celltrion"]
    assert [row["nct_id"] for row in recent] == ["NCT00000001", "NCT00000006", "NCT00000002"]  # phase 1, observational and stale rows excluded
    flags = {row["nct_id"]: row["flags"] for row in recent}
    assert flags["NCT00000002"]["stopped"] is True and recent[2]["why_stopped"] == "Business decision"
    assert flags["NCT00000006"]["results_posted"] is True and flags["NCT00000006"]["completed"] is True
    assert flags["NCT00000001"] == {"results_posted": False, "stopped": False, "completed": False, "new_start": False}
    assert payload["modifications"]["ko"].startswith("ClinicalTrials.gov 원본에서")
    assert payload["freshness"]["status"] == "fresh"


def test_trials_refresh_stops_on_rate_limit_and_fails_when_nothing_came_back(bio_on):
    fake = FakeCt(rate_limit={"Celltrion"})
    result = bio.refresh_bio_trials(provider=fake, now=NOW)
    assert result["updated"] == 1 and result["failed"] == 1 and fake.calls == ["Pfizer", "Celltrion"]  # Samsung Bioepis never requested
    with pytest.raises(DataUnavailable):
        bio.refresh_bio_trials(provider=FakeCt(fail={"Pfizer", "Celltrion", "Samsung Bioepis"}), now=NOW, force=True)


def test_fda_refresh_pages_and_build_counts(bio_on):
    fake = FakeFda(total=150)
    result = bio.refresh_bio_fda(provider=fake, now=NOW)
    assert result["updated"] == 3 and result["pages"] == 2 and fake.calls == [(100, 0), (100, 100)]
    payload = bio.build_bio_fda(now=NOW)
    assert [row["application_number"] for row in payload["approvals"]] == ["NDA219001", "BLA761999"]  # generics counted, not listed
    assert payload["generics"]["count"] == 1
    assert payload["counts"] == {"nda": 1, "bla": 1, "anda": 1, "other": 0, "priority_review": 1, "new_molecular_entity": 1}
    assert payload["window"] == {"start": "2026-06-23", "end": "2026-08-22"} and payload["publisher_last_updated"] == "2026-08-21"
    assert payload["rights"]["status"] == "public_domain_cc0" and payload["attribution"]["publisher_disclaimer"].startswith("Do not rely")
    assert bio.refresh_bio_fda(provider=fake, now=NOW) == {"skipped": "fresh"}


def test_lanes_off_make_no_calls_and_routes_follow_the_gate_contracts(db, monkeypatch):
    monkeypatch.setattr(config, "CLINICALTRIALS_PACE_SECONDS", 0.0)
    bio.clear_cache()
    client = TestClient(app)
    assert client.get("/api/bio/trials").json()["detail"]["code"] == "bio_section_disabled"
    assert client.get("/api/bio/fda").json()["detail"]["code"] == "bio_section_disabled"
    assert bio.refresh_bio_trials() == {"skipped": "disabled"} and bio.refresh_bio_fda() == {"skipped": "disabled"}
    assert ingest.refresh_bio_trials() == {"skipped": "disabled"} and ingest.refresh_bio_fda() == {"skipped": "disabled"}

    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    assert client.get("/api/bio/trials").json()["detail"]["code"] == "bio_trials_disabled"
    assert client.get("/api/bio/fda").json()["detail"]["code"] == "bio_fda_disabled"
    assert 'id="bio-trials"' in client.get("/bio").text

    monkeypatch.setattr(config, "CLINICALTRIALS_ENABLED", True)
    monkeypatch.setattr(config, "OPENFDA_ENABLED", True)
    assert client.get("/api/bio/trials").json()["detail"]["code"] == "bio_trials_collecting"
    assert client.get("/api/bio/fda").json()["detail"]["code"] == "bio_fda_collecting"

    monkeypatch.setattr(bio, "WATCHLIST", [bio.WATCHLIST_BY_ID["celltrion"]])
    bio.refresh_bio_trials(provider=FakeCt(), now=NOW)
    bio.refresh_bio_fda(provider=FakeFda(), now=NOW)
    trials = client.get("/api/bio/trials")
    assert trials.status_code == 200 and trials.headers["x-data-source"] == "ClinicalTrials.gov"
    assert trials.json()["watchlist"][0]["id"] == "celltrion"
    approvals = client.get("/api/bio/fda")
    assert approvals.status_code == 200 and approvals.headers["x-data-source"] == "openFDA"
    report = data_rights.lane_report()
    assert report["bio"]["status"] == "enabled" and report["clinicaltrials"]["status"] == "enabled" and report["openfda"]["status"] == "enabled"


# --- 도달 가능성 -------------------------------------------------------------


def test_bio_is_reachable_even_though_it_left_the_tab_row():
    """탭에서 내렸지 페이지를 버린 게 아니다.

    2026-08-23 판단: /bio는 기록 열람이라 값이 움직이지 않고(테이프·보드·타일
    어휘가 하나도 맞지 않는다) 신호 피드에도 합류하지 않아, 시장 화면들과
    나란히 탭을 차지할 자리가 아니다. 대신 랜딩 존 카드와 전 페이지 푸터로
    간다 — 링크가 끊기면 고아 페이지가 되므로 여기서 못을 박는다.
    """
    static = Path(config.STATIC_DIR)
    landing = (static / "landing.html").read_text(encoding="utf-8")
    assert 'class="zone-link-card" href="/bio"' in landing, "랜딩 존 카드에서 사라졌다"

    consoles = ["landing.html", "kr.html", "us.html", "crypto.html", "index.html", "glossary.html"]
    for name in consoles:
        page = (static / name).read_text(encoding="utf-8")
        assert '<a href="/bio"' in page, f"{name} 푸터에 /bio 링크가 없다"

    client = TestClient(app)
    assert client.get("/bio").status_code == 200
    assert "https://mulmit.com/bio" in client.get("/sitemap-pages.xml").text


def test_bio_is_not_in_the_tab_row():
    """탭 줄은 '지금 얼마'에 답하는 화면들의 자리다."""
    static = Path(config.STATIC_DIR)
    for page in static.glob("*.html"):
        markup = page.read_text(encoding="utf-8")
        assert 'class="view-tab" href="/bio"' not in markup, f"{page.name}에 바이오 탭이 돌아왔다"
        assert 'class="view-tab active" href="/bio"' not in markup, f"{page.name}에 바이오 탭이 돌아왔다"
