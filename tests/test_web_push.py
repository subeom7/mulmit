"""웹 푸시 — 구독 API와 임계값 상태 기계.

발송의 끝(푸시 서비스)은 그물 밖이라 테스트가 실제로 보낼 수 없다. 대신
- 상태 기계(evaluate_zone)는 순수 함수라 표로 고정하고 — 특히 히스테리시스
  사각지대(기준선과 재장전선 사이)에서 이전 구역이 유지되는 것,
- 발송 루프는 pywebpush를 스텁으로 갈아 끼워 두 종류의 실패를 확인한다:
  404/410(구독 소멸)은 즉시 삭제, 그 밖의 실패는 카운터 누적 후 한도 삭제.
- 선을 넘는 "순간"에만 발사되는 것은 refresh_kimchi_alert를 연속 호출로
  재현한다 — 2026-08-20 지수 급변 lane의 -3% 4연발이 이 규칙의 이유다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_kimchi, store, web_push
from app.main import app

client = TestClient(app)

ENDPOINT = "https://push.example.com/send/abc123"


@pytest.fixture
def push_enabled(db, monkeypatch):
    monkeypatch.setattr(config, "WEB_PUSH_ENABLED", True)
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", "test-public-key")
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "test-private-key")
    monkeypatch.setattr(config, "PUSH_KIMCHI_THRESHOLD", 3.0)
    monkeypatch.setattr(config, "PUSH_KIMCHI_REARM", 0.5)
    return db


# --- 상태 기계 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("previous", "premium", "expected"),
    [
        ("inside", 3.0, "above"),  # 기준선 도달 = 진입
        ("inside", 2.9, "inside"),  # 사각지대지만 안에서 출발했으면 안
        ("above", 2.7, "above"),  # 사각지대 — 선 아래로 내려와도 아직 재장전 전
        ("above", 2.5, "inside"),  # 재장전선(3.0-0.5) 안쪽 = 복귀
        ("above", -3.2, "below"),  # 반대쪽 선 돌파는 곧바로 반대 구역
        ("below", -2.6, "below"),
        ("below", 0.0, "inside"),
        ("inside", -3.0, "below"),
    ],
)
def test_zone_machine_with_hysteresis(push_enabled, previous, premium, expected):
    assert web_push.evaluate_zone(premium, previous) == expected


def test_alert_fires_on_crossing_not_on_staying(push_enabled, monkeypatch):
    """선 위에 머무는 동안 반복 발사하면 알림은 스팸이 되고 해제된다."""
    store.save_push_subscription(ENDPOINT, "p", "a", ["kimchi"])
    monkeypatch.setattr(crypto_kimchi, "enabled", lambda: True)
    sent: list[float] = []
    monkeypatch.setattr(
        web_push, "_send_all", lambda subs, note: sent.append(note) or {"delivered": len(subs)}
    )

    def feed(premium):
        monkeypatch.setattr(
            crypto_kimchi,
            "build_crypto_kimchi",
            lambda: {"coins": [{"symbol": "BTC", "premium_usdt_basis_percent": premium}]},
        )
        return web_push.refresh_kimchi_alert()

    assert feed(3.4)["fired"] is True  # 진입 — 발사
    assert feed(3.6)["fired"] is False  # 머무름 — 침묵
    assert feed(2.8)["fired"] is False  # 사각지대 — 아직 above
    assert feed(2.0)["fired"] is False  # 재장전
    assert feed(-3.1)["fired"] is True  # 반대쪽 진입 — 발사
    assert len(sent) == 2


def test_no_subscribers_means_no_upstream_call(push_enabled, monkeypatch):
    monkeypatch.setattr(crypto_kimchi, "enabled", lambda: True)

    def explode():
        raise AssertionError("구독자가 없는데 업비트를 불렀다")

    monkeypatch.setattr(crypto_kimchi, "build_crypto_kimchi", explode)
    assert web_push.refresh_kimchi_alert() == {"skipped": "no_subscribers"}


# --- 구독 API ----------------------------------------------------------------


def test_subscribe_stores_and_unsubscribe_removes(push_enabled):
    response = client.post(
        "/api/push/subscribe",
        json={"endpoint": ENDPOINT, "keys": {"p256dh": "pk", "auth": "ak"}, "topics": ["kimchi"]},
    )

    assert response.status_code == 200
    rows = store.load_push_subscriptions("kimchi")
    assert [row["endpoint"] for row in rows] == [ENDPOINT]

    assert client.post("/api/push/unsubscribe", json={"endpoint": ENDPOINT}).status_code == 200
    assert store.load_push_subscriptions("kimchi") == []


@pytest.mark.parametrize(
    "payload",
    [
        {"endpoint": "http://insecure.example/x", "keys": {"p256dh": "p", "auth": "a"}, "topics": ["kimchi"]},
        {"endpoint": "https://push.example/x", "keys": {"p256dh": "", "auth": "a"}, "topics": ["kimchi"]},
        {"endpoint": "https://push.example/x", "keys": {"p256dh": "p", "auth": "a"}, "topics": ["unknown"]},
        {"endpoint": "https://push.example/" + "x" * 1100, "keys": {"p256dh": "p", "auth": "a"}, "topics": ["kimchi"]},
    ],
)
def test_subscribe_rejects_bad_input(push_enabled, payload):
    assert client.post("/api/push/subscribe", json=payload).status_code == 422


def test_subscribe_is_gated(db, monkeypatch):
    monkeypatch.setattr(config, "WEB_PUSH_ENABLED", False)
    response = client.post(
        "/api/push/subscribe",
        json={"endpoint": ENDPOINT, "keys": {"p256dh": "p", "auth": "a"}, "topics": ["kimchi"]},
    )
    assert response.status_code == 503


def test_config_endpoint_hides_and_shows(db, monkeypatch):
    monkeypatch.setattr(config, "WEB_PUSH_ENABLED", False)
    assert client.get("/api/push/config").json() == {"enabled": False}

    monkeypatch.setattr(config, "WEB_PUSH_ENABLED", True)
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", "pub")
    payload = client.get("/api/push/config").json()
    assert payload["enabled"] is True
    assert payload["vapid_public_key"] == "pub"
    assert payload["topics"]["kimchi"]["threshold_percent"] == config.PUSH_KIMCHI_THRESHOLD


# --- 발송 루프의 실패 분류 ----------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _stub_pywebpush(monkeypatch, outcome_by_endpoint):
    import pywebpush

    def fake_webpush(subscription_info, **kwargs):
        outcome = outcome_by_endpoint[subscription_info["endpoint"]]
        if outcome is not None:
            raise pywebpush.WebPushException("boom", response=_FakeResponse(outcome))

    monkeypatch.setattr(pywebpush, "webpush", fake_webpush)


def test_gone_subscription_is_deleted_and_flaky_one_survives(push_enabled, monkeypatch):
    gone = "https://push.example.com/gone"
    flaky = "https://push.example.com/flaky"
    store.save_push_subscription(gone, "p", "a", ["kimchi"])
    store.save_push_subscription(flaky, "p", "a", ["kimchi"])
    store.save_push_subscription(ENDPOINT, "p", "a", ["kimchi"])
    _stub_pywebpush(monkeypatch, {gone: 410, flaky: 500, ENDPOINT: None})

    result = web_push._send_all(
        store.load_push_subscriptions("kimchi"), {"title": "t"}
    )

    assert result == {"delivered": 1, "expired": 1, "failed": 1}
    remaining = {row["endpoint"]: row["failures"] for row in store.load_push_subscriptions("kimchi")}
    assert gone not in remaining, "410은 구독 소멸 — 즉시 지워야 한다"
    assert remaining[flaky] == 1, "일시 실패는 지우지 않고 센다"
    assert remaining[ENDPOINT] == 0


def test_repeated_failures_eventually_delete(push_enabled):
    store.save_push_subscription(ENDPOINT, "p", "a", ["kimchi"])
    for _ in range(8):
        store.record_push_result(ENDPOINT, ok=False)
    assert store.load_push_subscriptions("kimchi") == []


def test_success_resets_the_failure_counter(push_enabled):
    store.save_push_subscription(ENDPOINT, "p", "a", ["kimchi"])
    for _ in range(7):
        store.record_push_result(ENDPOINT, ok=False)
    store.record_push_result(ENDPOINT, ok=True)
    store.record_push_result(ENDPOINT, ok=False)
    assert [row["failures"] for row in store.load_push_subscriptions("kimchi")] == [1]
