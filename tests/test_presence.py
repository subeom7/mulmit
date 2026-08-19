"""접속자 수 하트비트.

고정하는 것: 같은 id는 몇 번을 보내도 1로 세고, 창 밖으로 밀려난 id는
카운트에서 빠지며, 오래된 행은 하트비트가 지나갈 때 지워진다. API는
형식이 틀린 id를 거절하고, 어떤 lane 게이트와도 무관하게 동작한다.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import store
from app.main import app


def test_same_browser_counts_once(db):
    assert store.touch_presence("browser-aaaa-1111", now=1000.0) == 1
    assert store.touch_presence("browser-aaaa-1111", now=1030.0) == 1
    assert store.touch_presence("browser-bbbb-2222", now=1031.0) == 2


def test_stale_heartbeats_fall_out_of_the_window(db):
    store.touch_presence("browser-aaaa-1111", now=1000.0)
    # 91초 뒤: 첫 브라우저는 창 밖이다.
    assert store.touch_presence("browser-bbbb-2222", now=1091.0) == 1


def test_hour_old_rows_are_pruned_in_passing(db):
    store.touch_presence("browser-aaaa-1111", now=1000.0)
    store.touch_presence("browser-bbbb-2222", now=1000.0 + 3700.0)
    import sqlalchemy as sa

    with store.engine().begin() as conn:
        remaining = conn.execute(
            sa.select(store.presence.c.client_id)
        ).scalars().all()
    assert remaining == ["browser-bbbb-2222"]


def test_api_rejects_malformed_ids_and_counts_valid_ones(db):
    client = TestClient(app)

    bad = client.post("/api/presence", json={"id": "<script>"})
    assert bad.status_code == 422

    ok = client.post("/api/presence", json={"id": "0f0f0f0f-1234-abcd-9999-aaaaaaaaaaaa"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["count"] == 1
    assert body["window_seconds"] == 90
    assert "사람 수가 아닙니다" in body["basis_ko"]
    assert ok.headers["Cache-Control"] == "no-store"
