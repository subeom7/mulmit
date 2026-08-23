from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from app.macro_dashboard import MAX_PUBLIC_OBSERVATIONS, _downsample_observations
from app.main import app
from app.providers.fred import FRED_REQUIRED_NOTICE, FRED_SERIES_BY_ID

# Freshness is judged against the wall clock (7-day grace for daily series), so
# fixtures are dated relative to today rather than pinned to a calendar day.
#
# But not to *today* exactly. The weekly-sampling assertion below needs the two
# seeded days to land in the same ISO week, and a Monday has no earlier day in
# its own week — so on Mondays the pair straddled the boundary, sampling kept
# both points, and the suite went red at midnight with nothing having changed.
# Stepping back off Monday costs one day (still inside the 7-day grace) and
# makes the fixture mean the same thing on every calendar day.
_WALL_TODAY = dt.date.today()
TODAY = _WALL_TODAY - dt.timedelta(days=1) if _WALL_TODAY.weekday() == 0 else _WALL_TODAY
YESTERDAY = TODAY - dt.timedelta(days=1)
WEEK_AGO = TODAY - dt.timedelta(days=7)
assert TODAY.isocalendar()[:2] == YESTERDAY.isocalendar()[:2], (
    "두 점은 같은 ISO 주에 있어야 한다 — 주간 표본이 하나로 접히는지가 이 파일의 주장이다"
)


def _seed(db, *, notes: str = ""):
    spec = FRED_SERIES_BY_ID["DGS10"]
    db.save_fred_series(
        "DGS10",
        {
            "id": "DGS10",
            "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
            "units": "Percent",
            "units_short": "%",
            "frequency": "Daily, Close",
            "frequency_short": "D",
            "seasonal_adjustment": "Not Seasonally Adjusted",
            "seasonal_adjustment_short": "NSA",
            "observation_start": "1990-01-02",
            "observation_end": TODAY.isoformat(),
            "last_updated": "2026-08-15 08:38:01-05",
            "notes": notes,
        },
        [
            (YESTERDAY, 14.0),
            (TODAY, 14.25),
        ],
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
    )


def test_macro_overview_has_cards_series_freshness_and_attribution(db, fred_serving):
    _seed(db)
    client = TestClient(app)

    response = client.get("/api/market/macro?history=max")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"]["id"] == "fred"
    assert body["attribution"]["notice"] == FRED_REQUIRED_NOTICE
    assert body["attribution"]["terms_url"].startswith("https://fred.stlouisfed.org/")
    assert body["history"] == "max"
    treasury = next(item for item in body["series"] if item["id"] == "DGS10")
    assert treasury["source"]["publisher"] == "Board of Governors of the Federal Reserve System"
    assert treasury["units"]["long"] == "Percent"
    assert treasury["latest"] == {"date": TODAY.isoformat(), "value": 14.25}
    assert treasury["change"]["value"] == 0.25
    assert treasury["freshness"]["status"] == "fresh"
    assert treasury["rights"]["copyrighted"] is False
    assert treasury["rights"]["public_display"] is True
    # The snapshot carries one point per week for the card sparklines, so two
    # consecutive days collapse to the later one. The card's own numbers above
    # are unaffected: latest and change are read from the full series, not from
    # this sample — otherwise the change would quietly become week-over-week.
    assert treasury["observation_count"]["sampling"] == "weekly"
    # 달력에 기대지 않고 성질을 본다. 예전에는 "어제와 오늘"이 한 점으로 접힌다고
    # 못 박아 뒀는데, 오늘이 월요일이면 어제는 **지난 ISO 주**라 두 점이 남는다 —
    # 2026-08-24(월)에 그대로 터졌다. 지키려는 것은 "한 주에 한 점"이지
    # "이 두 날짜"가 아니다.
    assert treasury["observations"][-1] == {"date": TODAY.isoformat(), "value": 14.25}
    weeks = [
        dt.date.fromisoformat(point["date"]).isocalendar()[:2]
        for point in treasury["observations"]
    ]
    assert len(weeks) == len(set(weeks)), f"한 주에 두 점이 남았다: {treasury['observations']}"
    assert body["resolution"]["sampling"] == "weekly"
    assert body["resolution"]["full_series_url"] == "/api/market/macro/{series_id}"

    # And the full daily history stays one request away, at full resolution.
    single = client.get("/api/market/macro/DGS10?history=max").json()["series"]
    assert single["observation_count"]["sampling"] == "full"
    assert single["observations"] == [
        {"date": YESTERDAY.isoformat(), "value": 14.0},
        {"date": TODAY.isoformat(), "value": 14.25},
    ]
    assert single["change"]["value"] == 0.25

    assert set(body["restricted"]) == {"VIXCLS", "BAMLH0A0HYM2", "PCOPPUSDM"}
    for series_id in body["restricted"]:
        restricted = next(item for item in body["series"] if item["id"] == series_id)
        assert restricted["status"] == "license_required"
        assert restricted["latest"] is None
        assert restricted["observations"] == []
        assert restricted["rights"]["public_display"] is False
    assert response.headers["x-data-source"] == "FRED"
    assert "stale-while-revalidate" in response.headers["cache-control"]


def test_macro_series_endpoint_and_unknown_series(db, fred_serving):
    _seed(db)
    client = TestClient(app)

    response = client.get("/api/market/macro/dgs10?history=max")
    assert response.status_code == 200
    assert response.json()["series"]["key"] == "treasury_10y"

    restricted = client.get("/api/market/macro/vixcls?history=max")
    assert restricted.status_code == 200
    assert restricted.json()["series"]["status"] == "license_required"
    assert restricted.json()["series"]["observations"] == []

    unknown = client.get("/api/market/macro/NOPE")
    assert unknown.status_code == 404


def test_provider_copyright_note_fails_closed_at_runtime(db, fred_serving):
    _seed(db, notes="Copyright © Example Data Owner. Reprinted with permission.")
    client = TestClient(app)

    overview = client.get("/api/market/macro?history=max")
    detail = client.get("/api/market/macro/dgs10?history=max")

    assert overview.status_code == 200
    assert "DGS10" in overview.json()["restricted"]
    treasury = next(item for item in overview.json()["series"] if item["id"] == "DGS10")
    assert treasury["status"] == "license_required"
    assert treasury["latest"] is None
    assert treasury["observations"] == []
    assert treasury["rights"]["public_display"] is False
    assert detail.status_code == 200
    assert detail.json()["series"]["status"] == "license_required"
    assert detail.json()["series"]["observations"] == []


def test_macro_history_is_validated_without_network_access(db, fred_serving):
    client = TestClient(app)
    assert client.get("/api/market/macro?history=forever").status_code == 422


def test_long_macro_history_is_bounded_and_keeps_endpoints():
    start = dt.date(2000, 1, 1)
    observations = [
        (start + dt.timedelta(days=index), float(index)) for index in range(5000)
    ]

    sampled = _downsample_observations(observations)

    assert len(sampled) == MAX_PUBLIC_OBSERVATIONS
    assert sampled[0] == observations[0]
    assert sampled[-1] == observations[-1]


def test_stlfsi_ships_with_the_prescribed_citation(db, fred_serving):
    """St. Louis Fed's written permission (2026-08-18) asks for the suggested
    citation with the retrieval date wherever the series is displayed."""
    spec = FRED_SERIES_BY_ID["STLFSI4"]
    db.save_economic_series(
        "financial_stress",
        provider_id="fred",
        provider_series_id="STLFSI4",
        metadata_fields={"title": "St. Louis Fed Financial Stress Index"},
        observations=[(WEEK_AGO, -0.5), (TODAY, -0.4)],
        publisher=spec.publisher,
        publisher_url=spec.publisher_url,
        series_url=spec.series_url,
        rights_status="approved",
    )

    body = TestClient(app).get("/api/market/macro").json()

    stress = next(item for item in body["series"] if item["key"] == "financial_stress")
    citation = stress["rights"]["citation"]
    assert citation.startswith("Federal Reserve Bank of St. Louis, St. Louis Fed Financial Stress Index [STLFSI4]")
    assert "retrieved from FRED" in citation
    assert "https://fred.stlouisfed.org/series/STLFSI4" in citation
    # The date accessed follows the URL, e.g. "..., August 18, 2026."
    assert citation.rstrip(".").rsplit(", ", 2)[-1] == "2026"
    # No other series invents a citation.
    treasury = next(
        (item for item in body["series"] if item["key"] == "treasury_10y"), None
    )
    assert treasury is None or treasury["rights"]["citation"] is None
