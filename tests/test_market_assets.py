from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.market_assets import ASSETS, MAX_PUBLIC_OBSERVATIONS, build_asset_snapshot
from app.providers.base import DataUnavailable


def _context(
    mark: str | None,
    previous: str | None,
    *,
    oracle: str | None = None,
    volume: str = "2000000",
) -> dict[str, Any]:
    return {
        "markPx": mark,
        "oraclePx": oracle if oracle is not None else mark,
        "prevDayPx": previous,
        "funding": "0.00001",
        "openInterest": "123.4",
        "dayNtlVlm": volume,
    }


class FixtureProvider:
    def __init__(
        self,
        markets: list[tuple[str, dict[str, Any]]],
        *,
        stale: bool = False,
        cached: bool = False,
        error: Exception | None = None,
        delisted: set[str] | None = None,
    ) -> None:
        self.markets = markets
        self.stale = stale
        self.cached = cached
        self.error = error
        self.delisted = delisted or set()
        self.calls: list[str] = []

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        self.calls.append(dex)
        if self.error is not None:
            raise self.error
        return {
            "dex": dex,
            "fetched_at": "2026-08-16T01:02:03Z",
            "as_of": "2026-08-16T01:02:03Z",
            "cached": self.cached,
            "stale": self.stale,
            "age_seconds": 42.5 if self.stale else 0.0,
            "error": "DataUnavailable" if self.stale else None,
            "markets": [
                {
                    "symbol": symbol,
                    "dex": dex,
                    "metadata": {
                        "name": symbol,
                        "perpAnnotation": f"{symbol} fixture",
                        **({"isDelisted": True} if symbol in self.delisted else {}),
                    },
                    "context": context,
                }
                for symbol, context in self.markets
            ],
        }


def test_snapshot_uses_one_context_request_per_venue_and_calculates_24h_change():
    provider = FixtureProvider(
        [
            ("xyz:SP500", _context("110", "100")),
            ("xyz:XYZ100", _context("202", "200")),
            ("xyz:GOLD", _context("4400", "4380")),
        ]
    )

    snapshot = build_asset_snapshot("1y", provider)
    sp500 = next(item for item in snapshot["assets"] if item["id"] == "sp500")

    # One bounded request per venue, never one per asset.
    assert provider.calls == ["main", "xyz"]
    assert snapshot["history"] == "1y"
    assert snapshot["provider"]["read_path"] == "live_public_info_only"
    assert snapshot["provider"]["request_type"] == "metaAndAssetCtxs"
    assert snapshot["as_of"] == "2026-08-16T01:02:03Z"
    assert sp500["latest"] == {"date": "2026-08-16T01:02:03Z", "value": 110.0}
    assert sp500["previous"]["value"] == 100.0
    assert sp500["change"]["value"] == 10.0
    assert sp500["change"]["percent"] == pytest.approx(10.0)
    assert sp500["change"]["basis"].startswith("24h reference")
    assert sp500["drawdown"]["value"] is None
    assert sp500["observations"] == []
    assert sp500["observation_count"] == {
        "available": 0,
        "returned": 0,
        "limit": MAX_PUBLIC_OBSERVATIONS,
    }


def test_labels_and_sources_are_honest_about_proxies_and_quote_conversion():
    provider = FixtureProvider(
        [
            ("xyz:XYZ100", _context("30000", "29900")),
            ("xyz:KR200", _context("1100", "1090", volume="50000")),
            ("xyz:SMSN", _context("193", "190")),
            ("xyz:NIFTY", _context("24250", "24250", volume="0")),
            ("xyz:KRW", _context("1416", "1415", volume="0")),
        ]
    )

    assets = {item["id"]: item for item in build_asset_snapshot(provider=provider)["assets"]}

    assert assets["nasdaq"]["symbol"] == "xyz:XYZ100"
    assert "proxy" in assets["nasdaq"]["label"]["en"].lower()
    assert "neither the Nasdaq Composite" in assets["nasdaq"]["description"]["en"]
    assert assets["kospi"]["source"]["underlying"].startswith("Korea 200")
    assert "not the KOSPI Composite" in assets["kospi"]["description"]["en"]
    assert assets["samsung"]["currency"] == "USD"
    assert "KRX 005930" in assets["samsung"]["source"]["underlying"]
    assert "KRW-to-USD" in assets["samsung"]["description"]["en"]
    assert assets["inda"]["symbol"] == "xyz:NIFTY"
    assert "not INDA" in assets["inda"]["label"]["en"]
    assert assets["inda"]["market"]["liquidity_status"] == "unavailable"
    assert assets["usdkrw"]["source"]["underlying"] == "USD/KRW (KRW per USD)"


def test_unsupported_assets_are_missing_and_legacy_store_is_never_consulted(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("legacy persisted prices must not be read")

    monkeypatch.setattr("app.store.load_close", fail_if_called)
    provider = FixtureProvider([("xyz:EWZ", _context("34", "33"))])

    snapshot = build_asset_snapshot(provider=provider)

    assert [item["id"] for item in snapshot["assets"]] == ["ewz"]
    assert {"bitcoin", "kosdaq", "vnm"}.issubset(snapshot["missing"])
    assert snapshot["coverage"] == {
        "available": 1,
        "total": len(ASSETS),
        "ratio": pytest.approx(1 / len(ASSETS), abs=0.0001),
    }


def test_oracle_fallback_and_stale_metadata_are_explicit():
    provider = FixtureProvider(
        [("xyz:EWJ", _context(None, "98", oracle="99"))],
        stale=True,
        cached=True,
    )

    snapshot = build_asset_snapshot(provider=provider)
    ewj = snapshot["assets"][0]

    assert snapshot["provider"]["cached"] is True
    assert snapshot["provider"]["stale"] is True
    assert snapshot["provider"]["age_seconds"] == 42.5
    assert ewj["latest"]["value"] == 99.0
    assert ewj["source"]["price_field"] == "oraclePx_fallback"
    assert ewj["status"] == "stale"
    assert ewj["freshness"]["as_of"] == "2026-08-16T01:02:03Z"


def test_vix_oil_and_copper_are_synthetic_proxies_and_delisted_markets_stay_missing():
    provider = FixtureProvider(
        [
            ("xyz:VIX", _context("20", "19", volume="0")),
            ("xyz:CL", _context("81", "80")),
            ("xyz:COPPER", _context("6.8", "6.7")),
        ],
        delisted={"xyz:VIX"},
    )

    snapshot = build_asset_snapshot(provider=provider)
    assets = {item["id"]: item for item in snapshot["assets"]}

    assert "vix" in snapshot["missing"]
    assert "vix" not in assets
    assert assets["wti"]["symbol"] == "xyz:CL"
    assert "not a WTI spot quote" in assets["wti"]["description"]["en"]
    assert assets["wti"]["source"]["underlying"].endswith("(WTI/CL proxy)")
    assert assets["copper"]["symbol"] == "xyz:COPPER"
    assert "not the IMF copper series" in assets["copper"]["description"]["en"]
    assert "not IMF copper" in assets["copper"]["source"]["underlying"]
    assert assets["wti"]["rights"]["status"] == "provider_terms_apply"
    assert "does not itself grant redistribution rights" in assets["wti"]["rights"]["notice"]

    relisted = build_asset_snapshot(
        provider=FixtureProvider([("xyz:VIX", _context("21", "20", volume="500000"))])
    )
    vix = next(item for item in relisted["assets"] if item["id"] == "vix")
    assert vix["symbol"] == "xyz:VIX"
    assert "not the official Cboe VIX" in vix["description"]["en"]
    assert "not an official Cboe VIX feed" in vix["source"]["underlying"]


def test_provider_failure_returns_null_coverage_without_fake_values():
    snapshot = build_asset_snapshot(
        provider=FixtureProvider([], error=DataUnavailable("offline"))
    )

    assert snapshot["assets"] == []
    assert snapshot["missing"] == [spec.asset_id for spec in ASSETS]
    assert snapshot["coverage"] == {"available": 0, "total": len(ASSETS), "ratio": 0.0}
    assert snapshot["provider"]["error"] == "unavailable"
    assert snapshot["as_of"] is None


def test_asset_endpoint_preserves_public_contract_and_never_needs_network(monkeypatch, hip3_public_display):
    payload = build_asset_snapshot(
        "3y", FixtureProvider([("xyz:DXY", _context("97", "96", volume="0"))])
    )
    monkeypatch.setattr("app.main.build_asset_snapshot", lambda history: payload)

    response = TestClient(app).get("/api/market/assets?history=3y")

    assert response.status_code == 200
    assert response.json() == payload
    assert response.headers["cache-control"] == "private, max-age=30, stale-while-revalidate=300"
    assert response.headers["x-data-source"] == "Hyperliquid HIP-3"
    assert TestClient(app).get("/api/market/assets?history=forever").status_code == 422


def test_bitcoin_comes_from_hyperliquids_own_venue_not_hip3():
    """BTC is listed by Hyperliquid itself, not by trade.xyz through HIP-3.

    Crediting trade.xyz for it would misstate who published the contract, which
    is the same class of mistake as calling a synthetic perpetual a spot price.
    """
    provider = FixtureProvider([("BTC", _context("63500", "62000"))])

    snapshot = build_asset_snapshot("1y", provider)
    bitcoin = next(item for item in snapshot["assets"] if item["id"] == "bitcoin")

    assert bitcoin["latest"]["value"] == 63500.0
    assert bitcoin["source"]["provider"] == "Hyperliquid"
    assert bitcoin["source"]["publisher"] == "Hyperliquid"
    assert bitcoin["source"]["venue"] == "main"
    assert bitcoin["instrument_kind"] == "crypto_perpetual"


def test_hip3_assets_still_credit_trade_xyz():
    provider = FixtureProvider([("xyz:SP500", _context("110", "100"))])

    sp500 = next(
        item for item in build_asset_snapshot("1y", provider)["assets"] if item["id"] == "sp500"
    )

    assert sp500["source"]["provider"] == "Hyperliquid HIP-3"
    assert sp500["source"]["publisher"] == "trade.xyz"
    assert sp500["source"]["venue"] == "xyz"


def test_a_secondary_venue_outage_only_costs_its_own_cards():
    """Losing Hyperliquid's own venue must not blank the HIP-3 dashboard."""

    class OnlyPrimary(FixtureProvider):
        def fetch_dex(self, dex):
            if dex != "xyz":
                raise DataUnavailable("main venue is down")
            return super().fetch_dex(dex)

    provider = OnlyPrimary([("xyz:SP500", _context("110", "100"))])

    snapshot = build_asset_snapshot("1y", provider)

    assert [item["id"] for item in snapshot["assets"]] == ["sp500"]
    assert "bitcoin" in snapshot["missing"]
    assert snapshot["provider"].get("error") is None


def test_a_hyperliquid_listed_perpetual_is_not_labelled_synthetic():
    """The UI picks its badge from source.venue, so the API must report it.

    HIP-3 deployments list synthetics referencing an outside market; the main
    venue lists Hyperliquid's own contracts. Calling a real BTC perpetual
    synthetic is the mirror image of calling a synthetic one spot.
    """
    provider = FixtureProvider([
        ("BTC", _context("63500", "62000")),
        ("xyz:SP500", _context("110", "100")),
    ])

    assets = {item["id"]: item for item in build_asset_snapshot("1y", provider)["assets"]}

    assert assets["bitcoin"]["source"]["venue"] == "main"
    assert "synthetic" not in assets["bitcoin"]["instrument_kind"]
    assert assets["sp500"]["source"]["venue"] == "xyz"
