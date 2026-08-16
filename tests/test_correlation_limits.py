from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.metrics.correlation import MAX_CORRELATION_TICKERS, correlation_matrix


def test_correlation_rejects_more_than_twelve_unique_tickers_before_data_access():
    tickers = [f"T{index}" for index in range(MAX_CORRELATION_TICKERS + 1)]

    with pytest.raises(ValueError, match="최대 12개"):
        correlation_matrix(tickers)


@pytest.mark.parametrize(
    "tickers",
    ["SPY,TLT,$BAD", "SPY,TLT;DROP", "SPY,TLT/QQQ"],
)
def test_correlation_route_rejects_disallowed_characters(db, tickers):
    response = TestClient(app).get("/api/correlation", params={"tickers": tickers})

    assert response.status_code == 422


def test_correlation_route_bounds_raw_query_length(db):
    response = TestClient(app).get(
        "/api/correlation",
        params={"tickers": "A" * 264},
    )

    assert response.status_code == 422


def test_correlation_route_rejects_more_than_twelve_unique_tickers(db, monkeypatch):
    monkeypatch.setattr(config, "LEGACY_PRICE_DATA_ENABLED", True)
    tickers = ",".join(f"T{index}" for index in range(MAX_CORRELATION_TICKERS + 1))

    response = TestClient(app).get("/api/correlation", params={"tickers": tickers})

    assert response.status_code == 400
