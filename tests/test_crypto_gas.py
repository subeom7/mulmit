"""Gas / fee strip — operator-account EVM RPC, keys never exposed, nothing invented."""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config, crypto_gas, data_rights
from app.main import app
from app.providers.base import DataUnavailable, RateLimited
from app.providers.evm_rpc import EvmRpcProvider, host_label, parse_fee_history

SECRET_URL = "https://eth-mainnet.g.alchemy.com/v2/supersecretkey123"


def _rpc_transport(fee_history: Any = None, gas_price: str = "0x129006f9", *, calls: list[str] | None = None, error: Exception | None = None):
    def transport(url: str, payload: dict[str, Any], timeout: float) -> Any:
        if calls is not None:
            calls.append(payload["method"])
        if error is not None:
            raise error
        if payload["method"] == "eth_feeHistory":
            if fee_history is None:
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}
            return {"jsonrpc": "2.0", "id": 1, "result": fee_history}
        if payload["method"] == "eth_gasPrice":
            return {"jsonrpc": "2.0", "id": 1, "result": gas_price}
        raise AssertionError(payload["method"])
    return transport


FEE_HISTORY = {
    "oldestBlock": "0x189c8e2",
    "baseFeePerGas": ["0x11041c4", "0x110a9b0"],  # current, next
    "reward": [["0x5f5e100"]],  # 0.1 gwei p50
    "gasUsedRatio": [0.51],
}


def test_parse_fee_history_takes_next_block_base_fee_and_p50_priority():
    parsed = parse_fee_history({"result": FEE_HISTORY})
    assert parsed["base_fee_wei"] == 0x110A9B0
    assert parsed["priority_fee_wei"] == 100_000_000
    assert parsed["oldest_block"] == 0x189C8E2
    with pytest.raises(DataUnavailable):
        parse_fee_history({"result": {"baseFeePerGas": []}})
    with pytest.raises(DataUnavailable):
        parse_fee_history({"error": {"code": 1}})


def test_provider_prefers_1559_and_falls_back_to_gas_price():
    calls: list[str] = []
    provider = EvmRpcProvider(SECRET_URL, transport=_rpc_transport(FEE_HISTORY, calls=calls), ttl=30, stale_ttl=60)
    fees = provider.fetch_fees()
    assert fees["supports_1559"] is True and fees["base_fee_wei"] == 0x110A9B0 and fees["priority_fee_wei"] == 100_000_000
    assert fees["gas_price_wei"] == 0x129006F9 and fees["host"] == "eth-mainnet.g.alchemy.com"
    assert provider.fetch_fees()["cached"] is True and calls.count("eth_feeHistory") == 1

    legacy = EvmRpcProvider("https://rpc.example.org/v1/k", transport=_rpc_transport(None, "0x5b8d80")).fetch_fees()
    assert legacy["supports_1559"] is False and legacy["base_fee_wei"] is None and legacy["gas_price_wei"] == 6_000_000


def test_provider_never_leaks_the_url_and_maps_auth_errors():
    def unauthorized(url: str, payload: dict[str, Any], timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 401, "Unauthorized", hdrs=None, fp=None)

    provider = EvmRpcProvider(SECRET_URL, transport=unauthorized, retries=0)
    with pytest.raises(DataUnavailable) as excinfo:
        provider.fetch_fees()
    assert "supersecretkey123" not in str(excinfo.value)
    assert host_label(SECRET_URL) == "eth-mainnet.g.alchemy.com"

    def too_many(url: str, payload: dict[str, Any], timeout: float) -> Any:
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)

    with pytest.raises(RateLimited):
        EvmRpcProvider(SECRET_URL, transport=too_many, retries=0).fetch_fees()
    with pytest.raises(ValueError):
        EvmRpcProvider("not a url")


class FakeFees:
    def __init__(self, fees: dict[str, Any] | None = None, *, error: Exception | None = None, host: str = "rpc.example") -> None:
        self.fees = fees
        self.error = error
        self.host = host

    def fetch_fees(self) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return {"fetched_at": "2026-08-21T15:00:00Z", "as_of": "2026-08-21T15:00:00Z", "host": self.host,
                "supports_1559": True, "cached": False, "stale": False, **(self.fees or {})}


class FakeHl:
    def __init__(self, eth: float | None = 2400.0) -> None:
        self.eth = eth

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        markets = [] if self.eth is None else [{"symbol": "ETH", "dex": dex, "metadata": {"name": "ETH"}, "context": {"oraclePx": str(self.eth)}}]
        return {"dex": dex, "as_of": "2026-08-21T15:00:00Z", "stale": False, "markets": markets}


@pytest.fixture
def gas_lane(db, hip3_public_display, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CHAIN_GAS_ENABLED", True)
    monkeypatch.setattr(config, "CHAIN_RPC_ETHEREUM_URL", SECRET_URL)
    monkeypatch.setattr(config, "CHAIN_RPC_BASE_URL", "https://base-mainnet.g.alchemy.com/v2/k2")
    monkeypatch.setattr(config, "CHAIN_RPC_ARBITRUM_URL", "")
    monkeypatch.setattr(config, "CHAIN_RPC_PROVIDER_NAME", "Alchemy")
    crypto_gas.reset_providers()
    yield
    crypto_gas.reset_providers()


def test_build_gas_computes_transfer_cost_and_skips_unconfigured_chains(gas_lane):
    providers = {
        "ethereum": FakeFees({"base_fee_wei": 300_000_000, "priority_fee_wei": 100_000_000, "gas_price_wei": 350_000_000, "block": 123}),
        "base": FakeFees({"base_fee_wei": None, "priority_fee_wei": None, "gas_price_wei": 6_000_000, "supports_1559": False}, host="base-mainnet.g.alchemy.com"),
        "arbitrum": FakeFees({"base_fee_wei": 20_000_000, "priority_fee_wei": 0, "gas_price_wei": 20_000_000}),
    }
    payload = crypto_gas.build_crypto_gas(providers=providers, hl_provider=FakeHl(2400.0))
    assert payload["status"] == "ok"
    rows = {row["id"]: row for row in payload["chains"]}
    # Explicit providers are used as given; without them a chain with no URL is absent.
    assert set(rows) == {"ethereum", "base", "arbitrum"}
    eth = rows["ethereum"]
    assert eth["effective_gwei"] == pytest.approx(0.4)
    assert eth["transfer"]["eth"] == pytest.approx(0.4e-9 * 21_000, rel=1e-6)
    assert eth["transfer"]["usd"] == pytest.approx(0.4e-9 * 21_000 * 2400.0, abs=1e-6)
    assert eth["layer"] == "L1" and "mainnet" in eth["transfer"]["basis"]
    base = rows["base"]
    assert base["supports_1559"] is False and base["effective_gwei"] == pytest.approx(0.006)
    assert "L1 data fee is not included" in base["transfer"]["basis"]
    assert payload["eth_usd"]["value"] == 2400.0
    assert payload["rpc"]["provider_name"] == "Alchemy"
    dumped = json.dumps(payload)
    assert "supersecretkey123" not in dumped and "/v2/k2" not in dumped
    assert "eth-mainnet.g.alchemy.com" in dumped  # host label only


def test_build_gas_reports_outages_and_missing_eth_price_without_inventing(gas_lane):
    providers = {"ethereum": FakeFees(error=RateLimited("slow")), "base": FakeFees({"base_fee_wei": 1_000_000, "priority_fee_wei": 0, "gas_price_wei": 1_000_000})}
    payload = crypto_gas.build_crypto_gas(providers=providers, hl_provider=FakeHl(None))
    rows = {row["id"]: row for row in payload["chains"]}
    assert rows["ethereum"]["status"] == "rate_limited" and rows["ethereum"]["effective_gwei"] is None
    assert rows["base"]["transfer"]["usd"] is None and rows["base"]["transfer"]["eth"] is not None
    assert payload["eth_usd"]["value"] is None and payload["status"] == "ok"


def test_configured_urls_follow_env_and_gate_logic(db, monkeypatch):
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    monkeypatch.setattr(config, "CHAIN_GAS_ENABLED", True)
    monkeypatch.setattr(config, "CHAIN_RPC_ETHEREUM_URL", "")
    monkeypatch.setattr(config, "CHAIN_RPC_BASE_URL", "")
    monkeypatch.setattr(config, "CHAIN_RPC_ARBITRUM_URL", "")
    assert crypto_gas.configured_urls() == {}
    assert data_rights.chain_gas_status() == "not_configured"
    assert data_rights.chain_gas_serving_enabled() is False
    monkeypatch.setattr(config, "CHAIN_RPC_ARBITRUM_URL", "https://arb-mainnet.g.alchemy.com/v2/k3")
    assert list(crypto_gas.configured_urls()) == ["arbitrum"]
    assert data_rights.chain_gas_status() == "enabled"
    assert data_rights.lane_report()["chain_gas"]["chains"] == ["arbitrum"]
    monkeypatch.setattr(config, "CHAIN_GAS_ENABLED", False)
    assert data_rights.chain_gas_status() == "disabled"


def test_gas_route_states(db, hip3_public_display, monkeypatch):
    client = TestClient(app)
    assert client.get("/api/crypto/gas").json()["detail"]["code"] == "crypto_section_disabled"
    monkeypatch.setattr(config, "CRYPTO_SECTION_ENABLED", True)
    assert client.get("/api/crypto/gas").json()["detail"]["code"] == "chain_gas_disabled"
    monkeypatch.setattr(config, "CHAIN_GAS_ENABLED", True)
    monkeypatch.setattr(config, "CHAIN_RPC_ETHEREUM_URL", "")
    monkeypatch.setattr(config, "CHAIN_RPC_BASE_URL", "")
    monkeypatch.setattr(config, "CHAIN_RPC_ARBITRUM_URL", "")
    response = client.get("/api/crypto/gas")
    assert response.status_code == 503 and response.json()["detail"]["code"] == "chain_gas_not_configured"
    monkeypatch.setattr(config, "CHAIN_RPC_ETHEREUM_URL", SECRET_URL)
    crypto_gas.reset_providers()
    monkeypatch.setattr(crypto_gas, "_provider_for", lambda chain_id, url: FakeFees({"base_fee_wei": 300_000_000, "priority_fee_wei": 100_000_000, "gas_price_wei": 350_000_000}))
    monkeypatch.setattr(crypto_gas, "_HL_PROVIDER", FakeHl(2400.0))
    response = client.get("/api/crypto/gas")
    assert response.status_code == 200
    body = response.json()
    assert body["chains"][0]["id"] == "ethereum" and body["chains"][0]["transfer"]["usd"] > 0
    assert "supersecretkey123" not in response.text
    assert response.headers["x-data-source"].startswith("EVM JSON-RPC")
    crypto_gas.reset_providers()


def test_crypto_page_has_gas_section(db):
    page = TestClient(app).get("/crypto").text
    assert 'id="crypto-gas"' in page
