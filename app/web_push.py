"""웹 푸시 발송 — 구독은 web이 받고(main.py /api/push/*), 발송은 ingest가 한다.

첫 알림은 김치프리미엄 임계값이다. 규칙은 signal_feed의 지수 급변 lane과 같은
이유로 같은 모양이다: **선을 넘는 순간만** 이벤트고, 선 위에 머무는 동안은
반복하지 않으며, 안쪽으로 히스테리시스만큼 들어와야 재장전된다(2026-08-20
아침 -3% 선 4연발 실측이 이 규칙의 이유다).

상태는 reports 블롭(STATE_KEY)에 둔다 — 발송 프로세스(ingest)가 재시작해도
같은 선을 다시 쏘지 않는다.

발송 실패의 두 종류를 구분한다:
- 404/410 — 푸시 서비스가 "이 구독은 소멸했다"고 말한 것. 즉시 지운다.
- 그 밖(일시 장애·429) — 죽었는지 알 수 없다. 실패 횟수만 쌓고, 한도를
  넘도록 한 번도 성공하지 못하면 그때 지운다(store.record_push_result).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import config, crypto_kimchi, store

log = logging.getLogger(__name__)

TOPIC_KIMCHI = "kimchi"
TOPICS = {TOPIC_KIMCHI}
STATE_KEY = "push_kimchi_alert_v1"
# 상태가 이보다 낡았으면 버리고 새로 시작한다 — 2주 전의 "선 밖" 기억으로
# 오늘의 알림을 삼키면 안 된다.
STATE_TTL = 60 * 60 * 24 * 14


def enabled() -> bool:
    return config.WEB_PUSH_ENABLED


def sending_enabled() -> bool:
    return enabled() and bool(config.VAPID_PRIVATE_KEY)


def evaluate_zone(premium: float, previous: str) -> str:
    """임계값 상태 기계의 한 걸음.

    above/below는 즉시 진입하고, inside로는 히스테리시스 안쪽까지 들어와야
    돌아온다. 그 사이(사각지대)에서는 이전 구역을 유지한다.
    """
    threshold = config.PUSH_KIMCHI_THRESHOLD
    if premium >= threshold:
        return "above"
    if premium <= -threshold:
        return "below"
    if abs(premium) <= threshold - config.PUSH_KIMCHI_REARM:
        return "inside"
    return previous if previous in ("above", "below", "inside") else "inside"


def refresh_kimchi_alert(*, now: float | None = None) -> dict[str, Any]:
    """김프를 한 번 재고, 선을 넘는 순간이면 구독자에게 쏜다.

    구독자가 없으면 업스트림을 부르지 않는다 — 알림이 갈 곳이 없는데
    업비트를 두드릴 이유가 없다.
    """
    if not sending_enabled():
        return {"skipped": "disabled"}
    if not crypto_kimchi.enabled():
        return {"skipped": "kimchi_lane_disabled"}

    subscriptions = store.load_push_subscriptions(TOPIC_KIMCHI)
    if not subscriptions:
        return {"skipped": "no_subscribers"}

    payload = crypto_kimchi.build_crypto_kimchi()
    premium = _btc_premium(payload)
    if premium is None:
        return {"skipped": "no_premium"}

    state = store.load_report(STATE_KEY, STATE_TTL) or {}
    previous = str(state.get("zone") or "inside")
    zone = evaluate_zone(premium, previous)
    fired = zone != previous and zone in ("above", "below")

    result: dict[str, Any] = {"premium": premium, "zone": zone, "fired": fired}
    if fired:
        result["sent"] = _send_all(subscriptions, _kimchi_notification(premium))
    store.save_report(
        STATE_KEY,
        {"zone": zone, "premium": premium, "checked_at": now or time.time()},
    )
    return result


def _btc_premium(payload: dict[str, Any]) -> float | None:
    """헤드라인 값 — BTC의 USDT 기준 프리미엄. 환율이 소거된 쪽이라
    공식환율 고시가 없는 주말·야간에도 값이 있다."""
    for coin in payload.get("coins") or []:
        if coin.get("symbol") == "BTC":
            value = coin.get("premium_usdt_basis_percent")
            return float(value) if value is not None else None
    return None


def _kimchi_notification(premium: float) -> dict[str, Any]:
    sign = "+" if premium >= 0 else ""
    direction = "김프" if premium >= 0 else "역프"
    return {
        "title": f"{direction} {sign}{premium:.1f}% — 기준선 ±{config.PUSH_KIMCHI_THRESHOLD:g}% 밖",
        "body": "BTC 김치프리미엄(USDT 기준)이 기준선을 넘었습니다. 호가·수수료 미반영 참고값입니다.",
        "tag": "mulmit-kimchi",
        "url": "/crypto#crypto-kimchi",
    }


def _send_all(subscriptions: list[dict[str, Any]], notification: dict[str, Any]) -> dict[str, int]:
    # pywebpush(→cryptography)는 발송 경로에서만 필요하다. 모듈 상단에 두면
    # web 컨테이너·테스트가 발송 없이도 그 무게를 진다.
    from pywebpush import WebPushException, webpush  # noqa: PLC0415

    data = json.dumps(notification, ensure_ascii=False)
    delivered = expired = failed = 0
    for subscription in subscriptions:
        info = {
            "endpoint": subscription["endpoint"],
            "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
        }
        try:
            webpush(
                subscription_info=info,
                data=data,
                vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": config.VAPID_SUBJECT},
                ttl=config.PUSH_TTL,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                store.delete_push_subscription(subscription["endpoint"])
                expired += 1
            else:
                store.record_push_result(subscription["endpoint"], ok=False)
                failed += 1
                log.warning("푸시 발송 실패(%s): %s", status, exc)
        except Exception as exc:  # noqa: BLE001 - 한 기기의 실패가 나머지 발송을 막지 않는다
            store.record_push_result(subscription["endpoint"], ok=False)
            failed += 1
            log.warning("푸시 발송 실패: %s", exc)
        else:
            store.record_push_result(subscription["endpoint"], ok=True)
            delivered += 1
    return {"delivered": delivered, "expired": expired, "failed": failed}
