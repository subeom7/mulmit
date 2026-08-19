"""자체 방문 통계.

고정하는 것: 같은 (일·경로·유입호스트)는 카운트 증가로 합쳐지고, 고유방문은
일×id로 한 번만 세며, 목록 밖 경로는 'other'로 버킷팅되고, 자기 도메인
유입은 유입경로로 남지 않는다. 저장되는 것은 전부 집계값 — 개인정보 없음.
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app import store
from app.main import app

DAY = dt.date(2026, 8, 19)


def test_pageviews_aggregate_and_uniques_count_once(db):
    store.record_pageview("/", "news.naver.com", "visitor-aaaa-1111", today=DAY)
    store.record_pageview("/", "news.naver.com", "visitor-aaaa-1111", today=DAY)
    store.record_pageview("/kr", "", "visitor-bbbb-2222", today=DAY)

    stats = store.traffic_stats(1, today=DAY)
    assert stats["daily"][-1] == {"date": "2026-08-19", "pageviews": 3, "unique_visitors": 2}
    assert {row["path"]: row["count"] for row in stats["by_path"]} == {"/": 2, "/kr": 1}
    assert stats["top_referrers"] == [{"host": "news.naver.com", "count": 2}]


def test_beacon_buckets_paths_and_drops_self_referrals(db):
    client = TestClient(app)

    ok = client.post("/api/pageview", json={
        "path": "/kr", "ref": "https://www.google.com/search?q=x",
        "id": "visitor-cccc-3333",
    })
    assert ok.status_code == 200
    # 목록 밖 경로는 'other'로, 자기 도메인 유입은 direct로 취급된다.
    client.post("/api/pageview", json={
        "path": "/definitely-not-a-page", "ref": "https://mulmit.com/kr", "id": "bad id!!",
    })

    stats = client.get("/api/stats/traffic").json()
    paths = {row["path"]: row["count"] for row in stats["by_path"]}
    assert paths == {"/kr": 1, "other": 1}
    assert stats["top_referrers"] == [{"host": "www.google.com", "count": 1}]
    assert "쿠키 없음" in stats["basis_ko"]
