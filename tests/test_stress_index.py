"""Mulmit Liquidity & Stress Index.

The index exists because CNN's Fear & Greed cannot be copied and most of its
inputs cannot be licensed. These tests pin the things that keep a composite
honest: it only uses inputs this deployment may publish, it refuses to appear
at all when too few are available, it never imputes a missing one, and it
publishes the method rather than a number alone.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.stress_index import (
    COMPONENTS,
    MIN_COMPONENTS,
    StressIndexUnavailable,
    _percentile_rank,
    build_stress_index,
)

TODAY = dt.date(2026, 8, 14)


def _seed(db, series_key, values, *, provider_id="federal_reserve", rights_status="approved"):
    """Write a series with one observation per day ending today."""
    observations = [
        (TODAY - dt.timedelta(days=len(values) - 1 - index), float(value))
        for index, value in enumerate(values)
    ]
    db.save_economic_series(
        series_key,
        provider_id=provider_id,
        provider_series_id=series_key.upper(),
        metadata_fields={"title": series_key, "units": "Unit"},
        observations=observations,
        publisher="p",
        publisher_url="u",
        series_url="s",
        rights_status=rights_status,
    )


@pytest.fixture
def lanes(db, monkeypatch):
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", True)
    monkeypatch.setattr(config, "NYFED_ENABLED", True)
    monkeypatch.setattr(config, "BLS_ENABLED", True)


def _seed_enough(db):
    _seed(db, "reserve_balances", [100, 90, 80, 70, 60])
    _seed(db, "treasury_general_account", [10, 20, 30, 40, 50])
    _seed(db, "unemployment", [3.5, 3.6, 3.8, 4.0, 4.1], provider_id="bls")


def test_percentile_rank_is_a_share_not_a_z_score():
    history = [1.0, 2.0, 3.0, 4.0]

    assert _percentile_rank(history, 4.0) == 100.0
    assert _percentile_rank(history, 1.0) == 25.0
    assert _percentile_rank(history, 0.0) == 0.0
    # No history is a neutral score rather than a crash or a zero.
    assert _percentile_rank([], 5.0) == 50.0


def test_inverted_inputs_are_oriented_so_higher_always_means_more_stress(db, lanes):
    """Reserves at a five-year low must read as stress, not as calm."""
    _seed_enough(db)

    index = build_stress_index(as_of=TODAY)
    by_key = {item["series_key"]: item for item in index["components"]}

    reserves = by_key["reserve_balances"]
    assert reserves["inverted"] is True
    assert reserves["percentile"] == 20.0  # lowest of five
    assert reserves["score"] == 80.0  # ...which is high stress

    tga = by_key["treasury_general_account"]
    assert tga["inverted"] is False
    assert tga["percentile"] == tga["score"] == 100.0


def test_the_index_is_the_equal_weighted_mean_of_its_components(db, lanes):
    _seed_enough(db)

    index = build_stress_index(as_of=TODAY)

    scores = [item["score"] for item in index["components"]]
    assert index["score"] == pytest.approx(round(sum(scores) / len(scores), 1))
    assert index["method"]["weighting"] == "equal"


def test_a_missing_input_is_dropped_and_reported_never_imputed(db, lanes):
    _seed_enough(db)

    index = build_stress_index(as_of=TODAY)

    assert {item["series_key"] for item in index["components"]} == {
        "reserve_balances",
        "treasury_general_account",
        "unemployment",
    }
    # Everything else is named rather than silently filled with a neutral 50.
    assert set(index["missing"]) == {
        component.series_key for component in COMPONENTS
    } - {item["series_key"] for item in index["components"]}
    assert index["missing"]


def test_too_few_inputs_withholds_the_index_entirely(db, lanes):
    _seed(db, "reserve_balances", [100, 90, 80])
    _seed(db, "treasury_general_account", [10, 20, 30])

    with pytest.raises(StressIndexUnavailable) as caught:
        build_stress_index(as_of=TODAY)

    assert caught.value.available == 2
    assert caught.value.required == MIN_COMPONENTS


def test_an_input_the_deployment_may_not_publish_is_not_used(db, lanes):
    """A composite must not launder a withheld series into a published number."""
    _seed_enough(db)
    _seed(db, "yield_curve", [1.0, 0.5, 0.2, -0.1, -0.3], rights_status="license_required")

    index = build_stress_index(as_of=TODAY)

    assert "yield_curve" not in {item["series_key"] for item in index["components"]}
    assert "yield_curve" in index["missing"]


def test_a_closed_lane_excludes_its_inputs_too(db, monkeypatch):
    _seed_enough(db)
    monkeypatch.setattr(config, "FEDBOARD_ENABLED", False)
    monkeypatch.setattr(config, "BLS_ENABLED", True)

    # Only the BLS input survives, which is below the minimum.
    with pytest.raises(StressIndexUnavailable):
        build_stress_index(as_of=TODAY)


def test_the_published_method_is_specific_enough_to_reproduce(db, lanes):
    _seed_enough(db)

    method = build_stress_index(as_of=TODAY)["method"]

    assert method["lookback_years"] == 5
    assert "percentile" in method["scoring"]
    assert method["missing_data"] == "dropped, never imputed"
    assert method["minimum_components"] == MIN_COMPONENTS
    assert method["summary_ko"] and method["summary_en"]


def test_the_disclaimer_separates_this_from_other_sentiment_gauges(db, lanes):
    _seed_enough(db)

    index = build_stress_index(as_of=TODAY)

    # The register forbids reproducing CNN's name or score; saying plainly that
    # the values are not comparable is the other half of that.
    assert "Fear & Greed" in index["disclaimer"]["en"]
    assert "not comparable" in index["disclaimer"]["en"]
    assert "CNN" in index["disclaimer"]["ko"]
    assert index["label"]["en"] == "Mulmit Liquidity & Stress Index"
    # It is named for what it measures, not dressed as a sentiment gauge.
    assert "fear" not in index["label"]["en"].lower()
    assert "greed" not in index["label"]["en"].lower()


def test_bands_describe_the_reading_without_advising(db, lanes):
    _seed_enough(db)

    index = build_stress_index(as_of=TODAY)

    assert index["band"]["ko"] in {"매우 완화", "완화", "중립", "긴축", "매우 긴축"}
    assert 0 <= index["score"] <= 100


def test_api_serves_the_index_with_its_components(db, lanes):
    _seed_enough(db)

    response = TestClient(app).get("/api/market/stress")

    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "liquidity_stress"
    assert len(body["components"]) == 3
    assert response.headers["x-data-source"] == "Mulmit composite"


def test_api_returns_a_structured_503_when_inputs_are_thin(db, lanes):
    response = TestClient(app).get("/api/market/stress")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "stress_index_unavailable"
    assert detail["status"] == "insufficient_inputs"
    assert response.headers["cache-control"] == "no-store"


def test_every_component_names_a_real_series_and_explains_its_direction():
    from app.providers.fred import FRED_SERIES_BY_KEY

    for component in COMPONENTS:
        assert component.series_key in FRED_SERIES_BY_KEY, component.series_key
        assert component.rationale_ko and component.rationale_en
    assert len({c.series_key for c in COMPONENTS}) == len(COMPONENTS)


def test_components_reflect_only_series_this_project_can_publish():
    """Volatility and credit spreads are absent because they are unlicensed."""
    keys = {component.series_key for component in COMPONENTS}

    assert keys.isdisjoint({"vix", "high_yield_spread", "financial_stress", "skew", "pcr"})
