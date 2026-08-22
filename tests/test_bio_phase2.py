"""Bio Phase 2 — PubMed citations merged into the trials lane, FDA advisory-committee notices from the Federal Register."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_bio import FakeCt  # tests/ is on sys.path under pytest's default import mode

from app import bio, config, ingest, store
from app.main import app
from app.providers import federal_register as fr
from app.providers import pubmed as pm
from app.providers.base import DataUnavailable, RateLimited

NOW = dt.datetime(2026, 8, 22, 6, 0, tzinfo=dt.UTC)  # 02:00 ET (Saturday) → inside the off-peak window


@pytest.fixture
def phase2_on(db, monkeypatch):
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CLINICALTRIALS_ENABLED", True)
    monkeypatch.setattr(config, "OPENFDA_ENABLED", True)
    monkeypatch.setattr(config, "PUBMED_ENABLED", True)
    monkeypatch.setattr(config, "FEDERAL_REGISTER_ENABLED", True)
    monkeypatch.setattr(config, "CLINICALTRIALS_PACE_SECONDS", 0.0)
    monkeypatch.setattr(config, "PUBMED_PACE_SECONDS", 0.0)
    small = [spec for spec in bio.WATCHLIST if spec["id"] in ("celltrion", "pfizer")]
    monkeypatch.setattr(bio, "WATCHLIST", small)
    monkeypatch.setattr(bio, "WATCHLIST_BY_ID", {spec["id"]: spec for spec in small})
    bio.clear_cache()
    yield
    bio.clear_cache()


# --- PubMed provider ------------------------------------------------------------

ESEARCH_HIT = {"esearchresult": {"count": "2", "idlist": ["40396505", "33301246"]}}
ESEARCH_MISS = {"esearchresult": {"count": "0", "idlist": []}}
ESUMMARY = {"result": {"uids": ["40396505", "33301246"],
                       "40396505": {"uid": "40396505", "title": "Long-term follow-up of trial X.", "fulljournalname": "The Lancet", "pubdate": "2026 May 2", "epubdate": "", "sortpubdate": "2026/05/02 00:00", "pubtype": ["Journal Article", "Clinical Trial, Phase III"], "articleids": [{"idtype": "doi", "value": "10.1000/x"}]},
                       "33301246": {"uid": "33301246", "title": "Primary results of trial X.", "fulljournalname": "The New England journal of medicine", "pubdate": "2020 Dec 31", "pubtype": ["Journal Article"], "articleids": []}}}


def test_pubmed_parsers_and_provider_identify_requests():
    assert pm.parse_esearch(ESEARCH_HIT) == {"count": 2, "pmids": ["40396505", "33301246"]}
    assert pm.parse_esearch(ESEARCH_MISS) == {"count": 0, "pmids": []}
    with pytest.raises(DataUnavailable):
        pm.parse_esearch({"error": "API rate limit exceeded"})
    articles = pm.parse_esummary(ESUMMARY)
    assert [a["pmid"] for a in articles] == ["40396505", "33301246"]
    assert articles[0]["doi"] == "10.1000/x" and articles[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/40396505/"
    assert "abstract" not in articles[0]
    assert pm.search_page_url("NCT00000001") == "https://pubmed.ncbi.nlm.nih.gov/?term=NCT00000001%5Bsi%5D"

    seen: list[str] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        seen.append(url)
        return ESEARCH_HIT if "esearch" in url else ESUMMARY

    provider = pm.PubMedProvider(tool="mulmit", email="ops@example.org", api_key="k", transport=transport, retries=0)
    result = provider.search_nct("NCT00000001", retmax=3)
    assert result["count"] == 2 and "term=NCT00000001%5Bsi%5D" in seen[0] and "tool=mulmit" in seen[0] and "email=ops%40example.org" in seen[0] and "api_key=k" in seen[0] and "retmax=3" in seen[0]
    assert len(provider.summaries(["40396505", "33301246"])) == 2 and "id=40396505%2C33301246" in seen[1]
    with pytest.raises(ValueError):
        provider.summaries([str(i) for i in range(51)])


def test_pubmed_offpeak_window_follows_eastern_time():
    assert bio.pubmed_window_open(dt.datetime(2026, 8, 19, 19, 0, tzinfo=dt.UTC)) is False   # Wed 15:00 ET
    assert bio.pubmed_window_open(dt.datetime(2026, 8, 20, 2, 30, tzinfo=dt.UTC)) is True    # Wed 22:30 ET
    assert bio.pubmed_window_open(dt.datetime(2026, 8, 20, 8, 30, tzinfo=dt.UTC)) is True    # Thu 04:30 ET
    assert bio.pubmed_window_open(dt.datetime(2026, 8, 22, 16, 0, tzinfo=dt.UTC)) is True    # Saturday noon ET


class FakePubMed:
    def __init__(self, *, hits: set[str] = frozenset(), fail: set[str] = frozenset(), rate_limit: set[str] = frozenset()) -> None:
        self.searches: list[str] = []
        self.summary_calls: list[list[str]] = []
        self.hits, self.fail, self.rate_limit = set(hits), set(fail), set(rate_limit)

    def search_nct(self, nct_id: str, *, retmax: int = 5) -> dict[str, Any]:
        self.searches.append(nct_id)
        if nct_id in self.rate_limit:
            raise RateLimited("slow")
        if nct_id in self.fail:
            raise DataUnavailable("down")
        parsed = pm.parse_esearch(ESEARCH_HIT if nct_id in self.hits else ESEARCH_MISS)
        parsed.update(nct_id=nct_id, fetched_at="2026-08-22T06:00:00Z")
        return parsed

    def summaries(self, pmids: list[str]) -> list[dict[str, Any]]:
        self.summary_calls.append(list(pmids))
        return pm.parse_esummary(ESUMMARY)


def test_pubmed_refresh_merges_citations_into_recent_rows_and_carries_over(phase2_on, monkeypatch):
    bio.refresh_bio_trials(provider=FakeCt(), now=NOW)
    fake = FakePubMed(hits={"NCT00000001"}, fail={"NCT00000006"})
    result = bio.refresh_bio_pubmed(provider=fake, now=NOW)
    # watched rows: NCT1, NCT6, NCT2 per sponsor (two sponsors share the fixture → 3 unique NCTs)
    assert sorted(fake.searches) == ["NCT00000001", "NCT00000002", "NCT00000006"]
    assert result == {"updated": 2, "failed": 1, "hits": 1, "carried": 0}
    assert fake.summary_calls == [["33301246", "40396505"]]
    assert bio.refresh_bio_pubmed(provider=fake, now=NOW) == {"skipped": "fresh"}

    payload = bio.build_bio_trials(now=NOW)
    assert payload["pubmed"]["status"] == "ok" and payload["pubmed"]["hits"] == 1 and payload["pubmed"]["attribution"]["text"] == "Source: PubMed (NCBI / NLM)"
    row = next(r for r in payload["recent"] if r["nct_id"] == "NCT00000001")
    assert row["publications"]["count"] == 2 and row["publications"]["search_url"].endswith("NCT00000001%5Bsi%5D")
    assert [a["pmid"] for a in row["publications"]["articles"]] == ["40396505", "33301246"]
    assert "abstract" not in row["publications"]["articles"][0]
    miss = next(r for r in payload["recent"] if r["nct_id"] == "NCT00000002")
    assert miss["publications"]["count"] == 0 and miss["publications"]["articles"] == []
    failed = next(r for r in payload["recent"] if r["nct_id"] == "NCT00000006")
    assert failed["publications"] is None

    # Off-peak guard: a weekday-afternoon pass is skipped unless forced; forced pass carries over the earlier entries.
    afternoon = dt.datetime(2026, 8, 25, 18, 0, tzinfo=dt.UTC)  # Tue 14:00 ET
    store.save_report(bio.PUBMED_CACHE_KEY, {"generated_at": "x", "fetched_at": "2026-08-20T06:00:00Z", "queried": 1, "failed": 0, "hits": 1,
                                             "studies": {"NCT12345678": {"count": 2, "pmids": ["40396505"], "articles": [], "as_of": "2026-08-20T06:00:00Z"},
                                                         "NCT99999999": {"count": 1, "pmids": ["1"], "articles": [], "as_of": "2026-05-01T00:00:00Z"}}})
    bio.clear_cache()
    monkeypatch.setattr(config, "PUBMED_MAX_AGE", 0)
    assert bio.refresh_bio_pubmed(provider=fake, now=afternoon) == {"skipped": "offpeak_window"}
    forced = bio.refresh_bio_pubmed(provider=FakePubMed(), now=afternoon, force=True)
    assert forced["updated"] == 3 and forced["failed"] == 0
    assert forced["carried"] == 1  # NCT12345678 carried (2 days old, not re-queried); NCT99999999 dropped (older than 60 days)
    with pytest.raises(DataUnavailable):
        bio.refresh_bio_pubmed(provider=FakePubMed(rate_limit={"NCT00000001", "NCT00000002", "NCT00000006"}), now=afternoon, force=True)


def test_pubmed_lane_off_means_no_merge_and_no_calls(db, monkeypatch):
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CLINICALTRIALS_ENABLED", True)
    monkeypatch.setattr(config, "PUBMED_ENABLED", False)
    monkeypatch.setattr(config, "CLINICALTRIALS_PACE_SECONDS", 0.0)
    bio.clear_cache()
    assert bio.refresh_bio_pubmed(provider=FakePubMed()) == {"skipped": "disabled"}
    assert ingest.refresh_bio_pubmed() == {"skipped": "disabled"}
    monkeypatch.setattr(bio, "WATCHLIST", [bio.WATCHLIST_BY_ID["celltrion"]])
    bio.refresh_bio_trials(provider=FakeCt(), now=NOW)
    payload = bio.build_bio_trials(now=NOW)
    assert payload["pubmed"]["status"] == "disabled" and all(r["publications"] is None for r in payload["recent"])


# --- Federal Register -----------------------------------------------------------

FR_RAW = {"count": 4, "total_pages": 1, "results": [
    {"document_number": "2026-16245", "title": "Molecular and Clinical Genetics Panel of the Medical Devices Advisory Committee; Notice of Meeting; Establishment of a Public Docket", "publication_date": "2026-08-10", "html_url": "https://www.federalregister.gov/d/2026-16245", "dates": "The meeting will be held on September 23, 2026, from 9 a.m. to 6 p.m. Eastern Time.", "action": "Notice; establishment of a public docket", "abstract": "The Food and Drug Administration (FDA) announces a forthcoming public advisory committee meeting " + "x" * 400, "type": "Notice"},
    {"document_number": "2026-15017", "title": "Cellular, Tissue, and Gene Therapies Advisory Committee; Amendment of Notice", "publication_date": "2026-07-24", "html_url": "https://www.federalregister.gov/d/2026-15017", "dates": "", "action": "Notice.", "abstract": None, "type": "Notice"},
    {"document_number": "2026-14000", "title": "Pharmacy Compounding Advisory Committee; Notice of Meeting", "publication_date": "2026-04-16", "html_url": "https://www.federalregister.gov/d/2026-14000", "dates": "The meeting will be held on July 23, 2026, from 8:00 a.m. to 4:30 p.m. Eastern Time and July 24, 2026, from 8:00 a.m. to 12:30 p.m.", "action": "Notice", "abstract": "Two-day meeting.", "type": "Notice"},
    {"document_number": "2026-13000", "title": "ChemoCentryx, Inc.; Proposal To Withdraw Approval of New Drug Application", "publication_date": "2026-04-30", "html_url": "https://www.federalregister.gov/d/2026-13000", "dates": "by June 1, 2026", "action": "Notice", "abstract": "", "type": "Notice"},
]}


class FakeFr:
    def __init__(self, *, total_pages: int = 1) -> None:
        self.calls: list[tuple[str, int]] = []
        self.total_pages = total_pages

    def fetch_fda_meeting_notices(self, *, since: dt.date, per_page: int = 100, page: int = 1) -> dict[str, Any]:
        self.calls.append((since.isoformat(), page))
        parsed = fr.parse_documents(FR_RAW)
        parsed.update(total_pages=self.total_pages, fetched_at="2026-08-22T06:00:00Z", since=since.isoformat())
        return parsed


def test_federal_register_parser_keeps_meeting_notices_and_extracts_dates():
    assert fr.extract_dates("held on July 23, 2026, … and July 24, 2026, from") == ["2026-07-23", "2026-07-24"]
    assert fr.extract_dates("") == [] and fr.extract_dates("February 30, 2026") == []
    assert fr.is_meeting_notice("Oncologic Drugs Advisory Committee; Notice of Meeting") is True
    assert fr.is_meeting_notice("Advisory Committee; Oncologic Drugs Advisory Committee; Renewal") is False
    parsed = fr.parse_documents(FR_RAW)
    numbers = [n["document_number"] for n in parsed["notices"]]
    assert numbers == ["2026-16245", "2026-15017", "2026-14000"]  # the withdrawal notice is not a committee meeting
    first = parsed["notices"][0]
    assert first["committee"] == "Molecular and Clinical Genetics Panel of the Medical Devices Advisory Committee"
    assert first["meeting_start"] == "2026-09-23" and first["amendment"] is False and first["summary"].endswith("…") and len(first["summary"]) <= 321
    assert parsed["notices"][1]["meeting_start"] is None and parsed["notices"][1]["amendment"] is True
    assert parsed["notices"][2]["meeting_dates"] == ["2026-07-23", "2026-07-24"]
    with pytest.raises(DataUnavailable):
        fr.parse_documents({"errors": {"term": ["bad"]}})

    seen: list[str] = []

    def transport(url: str, headers: dict[str, str], timeout: float) -> Any:
        seen.append(url)
        return FR_RAW

    fr.FederalRegisterProvider(transport=transport, retries=0).fetch_fda_meeting_notices(since=dt.date(2025, 12, 25), page=2)
    assert "conditions%5Bagencies%5D%5B%5D=food-and-drug-administration" in seen[0] and "conditions%5Btype%5D%5B%5D=NOTICE" in seen[0]
    assert "conditions%5Bpublication_date%5D%5Bgte%5D=2025-12-25" in seen[0] and "page=2" in seen[0] and "fields%5B%5D=dates" in seen[0]


def test_adcomm_refresh_and_build_classify_meetings(phase2_on):
    fake = FakeFr(total_pages=2)
    result = bio.refresh_bio_adcomm(provider=fake, now=NOW)
    assert result["updated"] == 3 and result["pages"] == 2 and [c[1] for c in fake.calls] == [1, 2]
    assert bio.refresh_bio_adcomm(provider=fake, now=NOW) == {"skipped": "fresh"}
    payload = bio.build_bio_adcomm(now=NOW)
    assert [r["document_number"] for r in payload["upcoming"]] == ["2026-16245"]
    assert payload["upcoming"][0]["days_until"] == 32 and payload["next_meeting"]["meeting_start"] == "2026-09-23"
    assert [r["document_number"] for r in payload["recent_past"]] == ["2026-14000"]  # ended 2026-07-24, 29 days ago → inside the 30-day window
    assert payload["totals"]["undated"] == 1 and payload["undated"][0]["document_number"] == "2026-15017"
    assert payload["rights"]["status"] == "us_government_work_public_domain" and payload["attribution"]["restriction"].startswith("no official")


def test_adcomm_recent_past_window(phase2_on):
    bio.refresh_bio_adcomm(provider=FakeFr(), now=NOW)
    payload = bio.build_bio_adcomm(now=dt.datetime(2026, 8, 20, 6, 0, tzinfo=dt.UTC))  # 27 days after July 24 → still listed as recently ended
    assert [r["document_number"] for r in payload["recent_past"]] == ["2026-14000"] and payload["recent_past"][0]["status"] == "past"


def test_phase2_routes_follow_gate_contracts(db, monkeypatch):
    monkeypatch.setattr(config, "CLINICALTRIALS_PACE_SECONDS", 0.0)
    bio.clear_cache()
    client = TestClient(app)
    assert client.get("/api/bio/adcomm").json()["detail"]["code"] == "bio_section_disabled"
    monkeypatch.setattr(config, "BIO_SECTION_ENABLED", True)
    assert client.get("/api/bio/adcomm").json()["detail"]["code"] == "bio_adcomm_disabled"
    assert bio.refresh_bio_adcomm(provider=FakeFr()) == {"skipped": "disabled"} and ingest.refresh_bio_adcomm() == {"skipped": "disabled"}
    monkeypatch.setattr(config, "FEDERAL_REGISTER_ENABLED", True)
    assert client.get("/api/bio/adcomm").json()["detail"]["code"] == "bio_adcomm_collecting"
    bio.refresh_bio_adcomm(provider=FakeFr(), now=NOW)
    response = client.get("/api/bio/adcomm")
    assert response.status_code == 200 and response.headers["x-data-source"] == "Federal Register"
    assert 'id="bio-adcomm"' in client.get("/bio").text
