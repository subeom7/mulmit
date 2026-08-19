"""Korean around-the-clock reference prices.

What these pin: the implied-won arithmetic is mark × official H.10 rate against
the roster's official close with both dates preserved; the index card compares
points to points with no FX involved; every missing input nulls exactly the
fields that depend on it instead of estimating; and the route refuses entirely
while the HIP-3 display gate is closed.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, kr_overnight
from app.kr_overnight import build_kr_overnight
from app.main import app
from app.providers.base import DataUnavailable


def _context(mark: str, previous: str, *, volume: str = "2000000") -> dict[str, Any]:
    return {
        "markPx": mark,
        "oraclePx": mark,
        "prevDayPx": previous,
        "funding": "0.00001",
        "openInterest": "10.0",
        "dayNtlVlm": volume,
    }


class FixtureProvider:
    def __init__(
        self,
        markets: list[tuple[str, dict[str, Any]]],
        *,
        stale: bool = False,
        error: Exception | None = None,
        delisted: set[str] | None = None,
    ) -> None:
        self.markets = markets
        self.stale = stale
        self.error = error
        self.delisted = delisted or set()
        self.calls: list[str] = []

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        self.calls.append(dex)
        if self.error is not None:
            raise self.error
        return {
            "dex": dex,
            "fetched_at": "2026-08-18T00:00:00Z",
            "as_of": "2026-08-18T00:00:00Z",
            "cached": False,
            "stale": self.stale,
            "age_seconds": 0.0,
            "markets": [
                {
                    "symbol": symbol,
                    "dex": dex,
                    "metadata": {
                        "name": symbol,
                        **({"isDelisted": True} if symbol in self.delisted else {}),
                    },
                    "context": context,
                }
                for symbol, context in self.markets
            ],
        }


ALL_MARKETS = [
    ("xyz:SMSN", _context("198.98", "190.63")),
    ("xyz:SKHX", _context("1210.0", "1171.6")),
    ("xyz:HYUNDAI", _context("325.29", "319.96")),
    ("xyz:KR200", _context("1131.5", "1095.8")),
    ("xyz:SKHY", _context("154.41", "151.2")),
]


def _seed_roster(db) -> None:
    db.save_kr_listings(
        [
            {"srtn_cd": "005930", "itms_nm": "삼성전자", "mrkt_ctg": "KOSPI",
             "clpr": 268000.0, "flt_rt": 4.89, "mrkt_tot_amt": 1.6e15},
            {"srtn_cd": "000660", "itms_nm": "SK하이닉스", "mrkt_ctg": "KOSPI",
             "clpr": 1593000.0, "flt_rt": -0.5, "mrkt_tot_amt": 1.1e15},
            {"srtn_cd": "005380", "itms_nm": "현대자동차", "mrkt_ctg": "KOSPI",
             "clpr": 418500.0, "flt_rt": 1.2, "mrkt_tot_amt": 9.0e13},
        ],
        "20260813",
    )


def _seed_index(db) -> None:
    db.save_kr_index_snapshot(
        [{"idx_nm": "코스피 200", "idx_csf": "KOSPI시리즈", "clpr": 1071.24,
          "vs": 41.81, "flt_rt": 4.06}],
        "20260813",
    )


def _seed_fx(db, *, rights: str = "approved") -> None:
    db.save_economic_series(
        "fx_usdkrw",
        provider_id="federal_reserve",
        provider_series_id="RXI_N.B.KO",
        metadata_fields={"title": "Korean won per US dollar", "units": "KRW per USD",
                         "units_short": "KRW", "frequency": "Daily", "frequency_short": "D"},
        observations=[
            (dt.date(2026, 8, 13), 1418.0),
            (dt.date(2026, 8, 14), 1414.29),
        ],
        publisher="Board of Governors of the Federal Reserve System",
        publisher_url="https://www.federalreserve.gov/",
        series_url="https://www.federalreserve.gov/releases/h10/",
        rights_status=rights,
    )


@pytest.fixture
def full_lanes(db, monkeypatch):
    """FSC + H.10 both servable; the HIP-3 side comes from the fixture provider."""
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", True)
    _seed_roster(db)
    _seed_index(db)
    _seed_fx(db)


def _card(payload: dict[str, Any], card_id: str) -> dict[str, Any]:
    return next(card for card in payload["cards"] if card["id"] == card_id)


# --- arithmetic ---------------------------------------------------------------


def test_equity_card_converts_mark_through_official_fx(full_lanes):
    payload = build_kr_overnight(FixtureProvider(ALL_MARKETS))
    samsung = _card(payload, "samsung_electronics")

    assert samsung["status"] == "ok"
    assert samsung["perp"]["mark"] == pytest.approx(198.98)
    assert samsung["perp"]["change_24h_percent"] == pytest.approx(4.3797, abs=1e-3)
    assert samsung["official"] == {
        **samsung["official"],
        "status": "ok", "close": 268000.0, "date": "2026-08-13", "unit": "KRW",
    }
    assert payload["fx"]["rate"] == pytest.approx(1414.29)
    assert payload["fx"]["date"] == "2026-08-14"
    assert samsung["implied"]["value"] == pytest.approx(198.98 * 1414.29)
    assert samsung["implied"]["vs_official_percent"] == pytest.approx(
        (198.98 * 1414.29 / 268000.0 - 1.0) * 100.0, abs=1e-3
    )
    assert samsung["implied"]["fx_applied"] is True


def test_index_card_compares_points_directly_without_fx(db, monkeypatch):
    # Only the FSC lane is open: the index must not need the H.10 series.
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", False)
    _seed_index(db)

    payload = build_kr_overnight(FixtureProvider(ALL_MARKETS))
    kospi = _card(payload, "kospi_200")

    assert payload["fx"]["status"] == "unavailable"
    assert kospi["status"] == "ok"
    assert kospi["implied"]["fx_applied"] is False
    assert kospi["implied"]["value"] == pytest.approx(1131.5)
    assert kospi["official"]["close"] == pytest.approx(1071.24)
    assert kospi["official"]["unit"] == "pt"
    assert kospi["implied"]["vs_official_percent"] == pytest.approx(
        (1131.5 / 1071.24 - 1.0) * 100.0, abs=1e-3
    )


# --- missing inputs null exactly their dependents -----------------------------


def test_missing_fx_withholds_conversion_but_not_the_mark(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", False)
    _seed_roster(db)

    payload = build_kr_overnight(FixtureProvider(ALL_MARKETS))
    samsung = _card(payload, "samsung_electronics")

    assert samsung["status"] == "no_fx"
    assert samsung["perp"]["mark"] == pytest.approx(198.98)
    assert samsung["official"]["close"] == pytest.approx(268000.0)
    assert samsung["implied"]["value"] is None
    assert samsung["implied"]["vs_official_percent"] is None


def test_unapproved_fx_rights_read_as_no_fx(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", True)
    _seed_roster(db)
    _seed_fx(db, rights="pending")

    payload = build_kr_overnight(FixtureProvider(ALL_MARKETS))

    assert payload["fx"]["status"] == "unavailable"
    assert _card(payload, "samsung_electronics")["status"] == "no_fx"


def test_closed_fsc_lane_withholds_official_closes(db, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", False)
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", True)
    _seed_roster(db)  # rows exist, but the lane is closed: they must not serve
    _seed_fx(db)

    payload = build_kr_overnight(FixtureProvider(ALL_MARKETS))
    samsung = _card(payload, "samsung_electronics")

    assert samsung["official"]["status"] == "lane_disabled"
    assert samsung["official"]["close"] is None
    # The conversion itself is still possible; only the comparison is not.
    assert samsung["implied"]["value"] == pytest.approx(198.98 * 1414.29)
    assert samsung["implied"]["vs_official_percent"] is None
    assert samsung["status"] == "no_official_close"


def test_delisted_and_absent_markets_read_as_market_unavailable(full_lanes):
    provider = FixtureProvider(
        [item for item in ALL_MARKETS if item[0] != "xyz:SKHX"],
        delisted={"xyz:HYUNDAI"},
    )
    payload = build_kr_overnight(provider)

    assert _card(payload, "sk_hynix")["status"] == "market_unavailable"
    assert _card(payload, "sk_hynix")["perp"] is None
    assert _card(payload, "hyundai_motor")["status"] == "market_unavailable"
    assert payload["coverage"] == {"available": 3, "total": 5}


def test_dex_outage_degrades_to_cards_without_marks(full_lanes):
    payload = build_kr_overnight(FixtureProvider([], error=DataUnavailable("down")))

    assert payload["source"]["perp"]["error"] == "unavailable"
    assert all(card["status"] == "market_unavailable" for card in payload["cards"])
    assert payload["coverage"]["available"] == 0


# --- route gate ---------------------------------------------------------------


def test_route_refuses_while_hip3_display_gate_is_closed(db):
    client = TestClient(app)
    response = client.get("/api/kr/overnight")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "hip3_public_display_pending_rights"
    assert response.headers["cache-control"] == "no-store"


def test_route_serves_the_assembled_payload_with_the_gate_open(
    full_lanes, hip3_public_display, monkeypatch
):
    monkeypatch.setattr(kr_overnight, "_DEFAULT_PROVIDER", FixtureProvider(ALL_MARKETS))
    client = TestClient(app)
    response = client.get("/api/kr/overnight")

    assert response.status_code == 200
    payload = response.json()
    assert payload["coverage"] == {"available": 5, "total": 5}
    assert response.headers["x-data-source"] == "Hyperliquid HIP-3 + FSC + Federal Reserve H.10"
    smsn = _card(payload, "samsung_electronics")
    assert smsn["implied"]["value"] == pytest.approx(198.98 * 1414.29)


def test_basis_dates_are_served_as_iso(full_lanes):
    payload = build_kr_overnight(FixtureProvider(ALL_MARKETS))
    assert _card(payload, "samsung_electronics")["official"]["date"] == "2026-08-13"
    assert _card(payload, "kospi_200")["official"]["date"] == "2026-08-13"


def test_the_adr_card_converts_through_the_disclosed_ratio(db, hip3_public_display, monkeypatch):
    """SKHY는 원주 1주 = 10 ADR — 환산가 = 마크 × 10 × 환율, 원주 종가 대비."""
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", True)
    _seed_roster(db)
    _seed_fx(db)

    payload = kr_overnight.build_kr_overnight(FixtureProvider(ALL_MARKETS))

    adr = next(card for card in payload["cards"] if card["id"] == "sk_hynix_adr")
    assert adr["kind"] == "adr"
    assert adr["adr"]["per_ordinary"] == 10
    expected = 154.41 * 10 * 1414.29
    assert adr["implied"]["value"] == pytest.approx(expected)
    assert adr["official"]["close"] == 1593000.0  # 원주(000660) 종가
    assert adr["implied"]["vs_official_percent"] == pytest.approx(
        (expected / 1593000.0 - 1) * 100, abs=1e-3)
    assert adr["status"] == "ok"


def test_the_adr_card_withholds_conversion_without_fx(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "FSC_ENABLED", True)
    _seed_roster(db)  # 환율 미시드

    payload = kr_overnight.build_kr_overnight(FixtureProvider(ALL_MARKETS))

    adr = next(card for card in payload["cards"] if card["id"] == "sk_hynix_adr")
    assert adr["status"] == "no_fx"
    assert adr["implied"]["value"] is None
    assert adr["perp"]["mark"] == 154.41  # 마크 자체는 보류하지 않는다
