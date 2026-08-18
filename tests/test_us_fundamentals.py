"""미국 재무제표 — EDGAR XBRL companyconcept lane.

무엇을 고정하는가: 분기/연간은 보고 기간 길이로 나뉘고 YTD는 어느 쪽에도 들어가지
않는다, 같은 기간의 정정 공시는 최신 제출분이 이긴다, 태그 사다리는 404에서만
다음 태그로 넘어가며 실제 사용 태그가 응답에 남는다, 마진은 같은 보고서 두 값의
나눗셈뿐이다, 매출 없는 티커는 캐시되지 않는다, 요청 경로는 저장소만 읽고 미수집
티커를 내부자 큐에 태운다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config, ingest, us_fundamentals
from app.main import app
from app.providers.base import DataUnavailable
from app.providers.sec_edgar import EdgarNotFound


@pytest.fixture
def edgar_lane(db, monkeypatch):
    monkeypatch.setattr(config, "SEC_EDGAR_ENABLED", True)
    monkeypatch.setattr(config, "SEC_EDGAR_USER_AGENT", "Mulmit test contact@example.com")


def _flow(start, end, val, *, fy=2026, fp="FY", form="10-K", filed="2026-08-01"):
    return {"start": start, "end": end, "val": val, "fy": fy, "fp": fp,
            "form": form, "filed": filed}


def _instant(end, val, *, filed="2026-08-01"):
    return {"end": end, "val": val, "fy": 2026, "fp": "FY", "form": "10-K", "filed": filed}


class FakeProvider:
    def __init__(self, concepts):
        self.concepts = concepts
        self.calls: list[str] = []

    def fetch_company_concept(self, cik, tag, *, taxonomy="us-gaap"):
        self.calls.append(tag)
        if tag not in self.concepts:
            raise EdgarNotFound(tag)
        return {"units": self.concepts[tag]}


def _seed_provider():
    """AAPL형 실데이터 축소본: 연간 1 + 분기 2 + YTD 1 + 정정 중복 1."""
    return FakeProvider({
        # 첫 태그는 없는 회사 — 사다리가 Revenues로 넘어간다.
        "Revenues": {"USD": [
            _flow("2024-09-29", "2025-09-27", 400_000_000_000.0),           # 연간(363d)
            _flow("2025-12-28", "2026-03-28", 111_184_000_000.0, fp="Q2", form="10-Q"),  # 분기(90d)
            _flow("2025-09-28", "2026-06-27", 364_357_000_000.0, fp="Q3", form="10-Q"),  # YTD(272d) — 제외돼야 함
            _flow("2026-03-29", "2026-06-27", 100_000_000_000.0, fp="Q3", form="10-Q", filed="2026-07-31"),
            # 같은 분기의 정정 공시 — 더 늦게 제출된 이 값이 이겨야 한다.
            _flow("2026-03-29", "2026-06-27", 109_417_000_000.0, fp="Q3", form="10-Q/A", filed="2026-08-05"),
        ]},
        "OperatingIncomeLoss": {"USD": [
            _flow("2026-03-29", "2026-06-27", 32_000_000_000.0, fp="Q3", form="10-Q"),
        ]},
        "NetIncomeLoss": {"USD": [
            _flow("2024-09-29", "2025-09-27", 110_000_000_000.0),
            _flow("2026-03-29", "2026-06-27", 29_789_000_000.0, fp="Q3", form="10-Q"),
        ]},
        "EarningsPerShareDiluted": {"USD/shares": [
            _flow("2026-03-29", "2026-06-27", 2.02, fp="Q3", form="10-Q"),
        ]},
        "Assets": {"USD": [
            _instant("2026-06-27", 383_266_000_000.0),
            _instant("2025-09-27", 360_000_000_000.0),
        ]},
        "StockholdersEquity": {"USD": [
            _instant("2026-06-27", 70_000_000_000.0),
        ]},
    })


def test_refresh_classifies_periods_and_prefers_the_latest_filing(db, edgar_lane):
    provider = _seed_provider()

    stats = us_fundamentals.refresh_for(provider, "AAPL", "0000320193", "Apple Inc.")

    assert stats == {"annual": 1, "quarterly": 2}
    # 사다리: 첫 태그 404 → Revenues 사용, 응답에 기록된다.
    assert provider.calls[0] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    payload = us_fundamentals.build_report("AAPL")
    assert payload["status"] == "collected"
    assert payload["concepts_used"]["revenue"] == "Revenues"

    annual = payload["annual"][0]
    assert annual["end"] == "2025-09-27"
    assert annual["revenue"] == 400_000_000_000.0
    assert annual["net_margin"] == 27.5  # 110/400
    assert annual["assets"] == 360_000_000_000.0  # 시점값은 잔액일로 매칭

    latest_q = payload["quarterly"][0]
    assert latest_q["end"] == "2026-06-27"
    # YTD(272일)는 분기에 섞이지 않고, 정정 공시 값이 이긴다.
    assert latest_q["revenue"] == 109_417_000_000.0
    assert latest_q["operating_margin"] == round(32_000_000_000.0 / 109_417_000_000.0 * 100, 1)
    assert latest_q["eps_diluted"] == 2.02
    assert latest_q["equity"] == 70_000_000_000.0


def test_the_ladder_picks_the_tag_with_the_newest_data(db, edgar_lane):
    """NVIDIA형 태그 마이그레이션: 앞선 태그가 존재하지만 데이터가 끊겨 있다."""
    provider = FakeProvider({
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"USD": [
            _flow("2021-02-01", "2022-01-30", 26_914_000_000.0, fy=2022),
        ]},
        "Revenues": {"USD": [
            _flow("2025-01-27", "2026-01-25", 200_000_000_000.0, fy=2026),
        ]},
        "NetIncomeLoss": {"USD": [
            _flow("2025-01-27", "2026-01-25", 100_000_000_000.0, fy=2026),
        ]},
    })

    us_fundamentals.refresh_for(provider, "NVDA", "0001045810", "NVIDIA Corp")

    payload = us_fundamentals.build_report("NVDA")
    assert payload["concepts_used"]["revenue"] == "Revenues"
    assert payload["annual"][0]["end"] == "2026-01-25"
    assert payload["annual"][0]["net_margin"] == 50.0


def test_missing_revenue_is_a_failure_not_an_empty_cache(db, edgar_lane):
    provider = FakeProvider({"NetIncomeLoss": {"USD": [
        _flow("2024-09-29", "2025-09-27", 1.0)]}})

    with pytest.raises(DataUnavailable):
        us_fundamentals.refresh_for(provider, "ZZZZ", "0000000001", "Zed")

    assert db.load_report(us_fundamentals.cache_key("ZZZZ"), 10**9) is None


def test_an_unseen_ticker_is_queued_for_the_insider_batch(db, edgar_lane):
    response = TestClient(app).get("/api/us/fundamentals/NVDA")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    company = db.get_insider_company("NVDA")
    assert company is not None and company["status"] == "queued"


def test_the_lane_fails_closed(db, monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(config, "SEC_EDGAR_ENABLED", False)
    response = client.get("/api/us/fundamentals/AAPL")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "us_fundamentals_disabled"
    assert response.headers["cache-control"] == "no-store"

    monkeypatch.setattr(config, "SEC_EDGAR_ENABLED", True)
    monkeypatch.setattr(config, "SEC_EDGAR_USER_AGENT", "")
    response = client.get("/api/us/fundamentals/AAPL")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "us_fundamentals_not_configured"


def test_ingest_targets_collected_insider_companies_only(db, edgar_lane, monkeypatch):
    db.save_insider_filings("AAPL", cik="0000320193", name="Apple Inc.",
                            exchange="Nasdaq", filings_seen=1, transactions=[])
    calls = []

    def fake_refresh_for(provider, ticker, cik, name):
        calls.append((ticker, cik))
        db.save_report(us_fundamentals.cache_key(ticker), {"annual": [], "quarterly": []})
        return {"annual": 0, "quarterly": 0}

    monkeypatch.setattr(us_fundamentals, "refresh_for", fake_refresh_for)

    result = ingest.refresh_us_fundamentals()
    assert result["updated"] == 1
    assert calls == [("AAPL", "0000320193")]

    # 신선한 블롭이 있으면 다시 걷지 않는다.
    assert ingest.refresh_us_fundamentals() == {
        "skipped": "fresh", "attempted": 0, "updated": 0, "failed": 0}

    monkeypatch.setattr(config, "SEC_EDGAR_ENABLED", False)
    assert ingest.refresh_us_fundamentals() == {"skipped": "disabled"}
