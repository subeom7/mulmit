"""경제 캘린더 — FRED 릴리스 일정 + 정책회의 큐레이션.

무엇을 고정하는가: 지난 날짜는 나오지 않는다, FRED 저장분이 없어도 큐레이션은
서빙된다, 이벤트는 날짜순으로 합쳐지고 상한이 있다, 큐레이션 확인일과 잠정성
문구가 응답에 실린다, ingest는 FRED lane 게이트를 따른다.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app import config, econ_calendar, ingest
from app.main import app
from app.providers.fred import FredProvider

TODAY = dt.date(2026, 8, 19)


def test_provider_parses_release_dates():
    body = json.dumps({"release_dates": [
        {"release_id": 10, "date": "2026-09-11"},
        {"release_id": 10, "date": "2026-10-14"},
    ]}).encode("utf-8")
    provider = FredProvider("k", http_get=lambda r, t: body, retries=0)

    dates = provider.fetch_release_dates(10, start=TODAY, end=TODAY + dt.timedelta(days=90))

    assert dates == ["2026-09-11", "2026-10-14"]


class FakeProvider:
    def fetch_release_dates(self, release_id, *, start, end, limit=12):
        return {10: ["2026-09-11"], 50: ["2026-09-04"], 53: [], 54: []}.get(release_id, [])


def test_refresh_then_build_merges_and_sorts(db):
    econ_calendar.refresh(FakeProvider(), today=TODAY)

    payload = econ_calendar.build_calendar(today=TODAY)

    dates = [event["date"] for event in payload["events"]]
    assert dates == sorted(dates)
    assert "2026-08-27" in dates          # 금통위 (큐레이션)
    assert "2026-09-04" in dates          # 고용보고서 (FRED)
    assert "2026-09-11" in dates          # CPI (FRED)
    first = payload["events"][0]
    assert first["date"] >= TODAY.isoformat()
    providers = {event["provider"] for event in payload["events"]}
    assert providers == {"curated", "fred"}
    assert econ_calendar.CURATED_VERIFIED_AT in payload["basis_ko"]


def test_curated_events_serve_without_a_fred_blob(db):
    payload = econ_calendar.build_calendar(today=TODAY)

    assert payload["events"]
    assert all(event["provider"] == "curated" for event in payload["events"])
    # 지난 이벤트는 나오지 않는다.
    late = econ_calendar.build_calendar(today=dt.date(2026, 12, 31))
    assert all(event["date"] >= "2026-12-31" for event in late["events"])


def test_route_serves_the_calendar(db):
    response = TestClient(app).get("/api/calendar")

    assert response.status_code == 200
    body = response.json()
    assert body["events"]
    assert "FRED" in body["source"]["fred_notice"]


def test_ingest_respects_the_fred_gate(db, monkeypatch):
    assert ingest.refresh_econ_calendar() == {"skipped": "disabled"}

    monkeypatch.setattr(config, "FRED_ENABLED", True)
    monkeypatch.setattr(config, "FRED_API_KEY", "k")
    calls = []
    monkeypatch.setattr(econ_calendar, "refresh", lambda: calls.append(1) or {"releases": 0, "dates": 0})
    assert ingest.refresh_econ_calendar() == {"releases": 0, "dates": 0}
    assert calls == [1]

    db.save_report(econ_calendar.CACHE_KEY, {"releases": {}})
    assert ingest.refresh_econ_calendar() == {"skipped": "fresh"}
    assert calls == [1]
