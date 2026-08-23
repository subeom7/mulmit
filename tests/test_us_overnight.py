"""미국 대형주 야간 참고가 `/api/us/overnight`.

이 화면이 성립하는 조건은 하나다 — **미국 현물장이 닫혀 있을 것.** 장이 열려
있는 동안에는 진짜 나스닥 호가가 있고, 그때 합성 퍼프를 나란히 두면 나은 게
없으면서 "실시간 주가"로 오해만 부른다. 그래서 여기서 가장 중요하게 지키는
것은 값의 정확성이 아니라 **언제 보여 주지 않는가**이다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import config, us_overnight
from app.main import app

NY = ZoneInfo("America/New_York")


def _at(year: int, month: int, day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=NY).astimezone(dt.UTC)


class _Dex:
    """상장 마켓 하나를 흉내 내는 최소 프로바이더."""

    def __init__(self, mark: str = "218.00", prev: str = "215.00", volume: str = "12000000"):
        self.calls: list[str] = []
        self.mark, self.prev, self.volume = mark, prev, volume

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        self.calls.append(dex)
        return {
            "as_of": "2026-08-23T12:00:00Z",
            "markets": [
                {
                    "symbol": target.symbol,
                    "context": {
                        "markPx": self.mark, "prevDayPx": self.prev,
                        "dayNtlVlm": self.volume, "openInterest": "1000",
                    },
                }
                for target in us_overnight.TARGETS
            ],
        }

    def fetch_session_baseline(self, symbol: str, boundary: dt.datetime, *, interval: str = "5m"):
        return {"price": 214.00, "proximity_quality": "high"}


def test_nothing_is_built_while_the_us_market_is_open():
    """장중에는 카드를 만들지 않는다 — 상류도 부르지 않는다.

    숨기는 것으로 끝내면 서버는 5초마다 헛일을 하고, 그 값이 어딘가로 새면
    "실시간 주가"로 읽힌다. 아예 만들지 않는 편이 안전하다.
    """
    dex = _Dex()
    payload = us_overnight.build_us_overnight(dex, now=_at(2026, 8, 20, 11, 0))  # 수요일 11:00 ET
    assert payload["status"] == "market_open"
    assert payload["session"]["market_open"] is True
    assert payload["cards"] == []
    assert dex.calls == [], "장중인데 상류를 불렀다"


@pytest.mark.parametrize(
    "moment",
    [
        _at(2026, 8, 22, 12, 0),   # 토요일
        _at(2026, 8, 23, 12, 0),   # 일요일
        _at(2026, 8, 20, 17, 30),  # 수요일 마감 후
        _at(2026, 8, 20, 8, 0),    # 수요일 개장 전
    ],
)
def test_cards_stand_whenever_the_cash_market_is_shut(moment):
    payload = us_overnight.build_us_overnight(_Dex(), now=moment)
    assert payload["session"]["market_open"] is False
    assert len(payload["cards"]) == len(us_overnight.TARGETS)


def test_the_headline_is_measured_against_the_last_regular_close():
    """이 섹션의 존재 이유는 '마감 이후'다. 24시간 변화가 아니다."""
    payload = us_overnight.build_us_overnight(_Dex(), now=_at(2026, 8, 23, 12, 0))
    card = payload["cards"][0]
    # 마크 218.00, 마감 시점 퍼프 214.00 → +1.87%
    assert card["session_reference"]["vs_percent"] == pytest.approx(1.8692, abs=1e-3)
    # 24h는 별개다(218 대 215).
    assert card["change_24h"]["percent"] == pytest.approx(1.3953, abs=1e-3)


def test_the_boundary_is_the_last_day_the_market_actually_traded():
    """일요일에 보면 기준은 **금요일** 마감이다. 토요일 16:00이 아니다."""
    boundary = us_overnight.session_boundary(_at(2026, 8, 23, 12, 0))
    assert boundary.astimezone(NY).date() == dt.date(2026, 8, 21)
    assert boundary.astimezone(NY).hour == 16


def test_a_thin_market_is_flagged_not_hidden():
    """얕은 시장은 숨기지 않고 표시한다 — 값이 튈 수 있다는 것도 정보다."""
    payload = us_overnight.build_us_overnight(
        _Dex(volume="100000"), now=_at(2026, 8, 23, 12, 0)
    )
    assert all(card["liquidity_status"] == "low" for card in payload["cards"])


def test_prices_are_dollars_with_no_conversion():
    payload = us_overnight.build_us_overnight(_Dex(), now=_at(2026, 8, 23, 12, 0))
    assert all(card["price"]["currency"] == "USD" for card in payload["cards"])
    assert "fx" not in payload, "미국 종목에 환율이 끼어들 이유가 없다"


def test_the_route_follows_the_hip3_display_gate(db, monkeypatch):
    monkeypatch.setattr(config, "HIP3_PUBLIC_DISPLAY_ENABLED", False)
    response = TestClient(app).get("/api/us/overnight")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "hip3_public_display_pending_rights"
