"""Gas / fee strip — Ethereum mainnet and the L2s the operator configured.

Reads public chain state through the operator's own RPC account (URLs in env,
keys never echoed).  Shows the next-block base fee, the p50 priority fee, the
effective gas price, and what a plain 21,000-gas transfer costs in ETH and USD
(ETH priced from the Hyperliquid oracle already on the page).  For L2s the cost
shown is the L2 execution leg only — the L1 data fee is not estimated, and the
payload says so.  A chain without a URL is simply absent, never invented.

Gate: ``CRYPTO_SECTION_ENABLED`` + ``CHAIN_GAS_ENABLED`` + at least one URL
(docs/DATA_SOURCE_REGISTER.md §3.21).
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from . import config, data_rights
from .crypto_market import _DEFAULT_PROVIDER as _HL_PROVIDER
from .providers.base import DataUnavailable, RateLimited
from .providers.evm_rpc import WEI_PER_ETH, WEI_PER_GWEI, EvmRpcProvider, host_label
from .providers.hyperliquid import MAIN_DEX

SIMPLE_TRANSFER_GAS = 21_000

log = logging.getLogger(__name__)

# Serving policy. Building the strip is four upstream round trips; measured
# cold it took 1.57s while a warm one took 0.03s, so under the old shape one
# visitor every 30 seconds paid the whole thing. Now a recent strip goes out
# immediately and a single background thread refreshes behind it.
SNAPSHOT_TTL = 30.0
# Past this, a stale strip is not worth serving and the caller waits.
SNAPSHOT_MAX_STALE = 600.0

_snapshot_lock = threading.Lock()
_snapshot: dict[str, Any] | None = None
_snapshot_at = 0.0
_refreshing = False


@dataclass(frozen=True)
class ChainSpec:
    chain_id: str
    label_ko: str
    label_en: str
    layer: str  # "L1" | "L2"
    env_name: str
    docs_url: str


CHAINS: tuple[ChainSpec, ...] = (
    ChainSpec("ethereum", "이더리움 메인넷", "Ethereum mainnet", "L1", "CHAIN_RPC_ETHEREUM_URL", "https://ethereum.org/en/developers/docs/gas/"),
    ChainSpec("base", "Base (L2)", "Base (L2)", "L2", "CHAIN_RPC_BASE_URL", "https://docs.base.org/"),
    ChainSpec("arbitrum", "Arbitrum One (L2)", "Arbitrum One (L2)", "L2", "CHAIN_RPC_ARBITRUM_URL", "https://docs.arbitrum.io/"),
)


class FeeProvider(Protocol):
    host: str

    def fetch_fees(self) -> dict[str, Any]: ...


class DexProvider(Protocol):
    def fetch_dex(self, dex: str) -> dict[str, Any]: ...


_providers: dict[str, EvmRpcProvider] = {}


def _build_and_store() -> dict[str, Any]:
    global _snapshot, _snapshot_at
    payload = build_crypto_gas()
    with _snapshot_lock:
        _snapshot, _snapshot_at = payload, time.monotonic()
    return payload


def _refresh_in_background() -> None:
    global _refreshing
    try:
        _build_and_store()
    except Exception:  # noqa: BLE001 - the served strip is already good enough
        log.warning("gas strip background refresh failed", exc_info=True)
    finally:
        with _snapshot_lock:
            _refreshing = False


def snapshot() -> dict[str, Any]:
    """The strip the route serves: recent, and never paid for by the visitor.

    Only the first request after a restart builds synchronously. After that a
    strip younger than ``SNAPSHOT_MAX_STALE`` goes out at once, and if it is
    older than ``SNAPSHOT_TTL`` one background thread refreshes it. That trades
    up to a few seconds of staleness — on a value the response already caches
    for 30 seconds — for never making a visitor wait on four RPC round trips.
    """
    global _refreshing
    with _snapshot_lock:
        cached, age = _snapshot, time.monotonic() - _snapshot_at
        start_refresh = (
            cached is not None and age > SNAPSHOT_TTL and not _refreshing
        )
        if start_refresh:
            _refreshing = True
    if cached is not None and age <= SNAPSHOT_MAX_STALE:
        if start_refresh:
            threading.Thread(target=_refresh_in_background, daemon=True).start()
        return cached
    if start_refresh:  # too old to serve; build here and let the flag go
        with _snapshot_lock:
            _refreshing = False
    return _build_and_store()


def reset_snapshot() -> None:
    """Drop the served strip — tests and the first call after a config change."""
    global _snapshot, _snapshot_at, _refreshing
    with _snapshot_lock:
        _snapshot, _snapshot_at, _refreshing = None, 0.0, False


def configured_urls() -> dict[str, str]:
    return {
        spec.chain_id: url
        for spec in CHAINS
        if (url := getattr(config, spec.env_name, "") or "").strip()
    }


def enabled() -> bool:
    return data_rights.chain_gas_serving_enabled()


def reset_providers() -> None:
    _providers.clear()


def _provider_for(chain_id: str, url: str) -> EvmRpcProvider:
    provider = _providers.get(chain_id)
    if provider is None or provider._url != url:  # noqa: SLF001 - same-module accessor
        provider = EvmRpcProvider(url, timeout=config.CHAIN_RPC_TIMEOUT)
        _providers[chain_id] = provider
    return provider


def _iso_utc() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _eth_usd(hl_provider: DexProvider) -> tuple[float | None, dict[str, Any]]:
    try:
        snapshot = hl_provider.fetch_dex(MAIN_DEX)
    except (RateLimited, DataUnavailable):
        return None, {"status": "unavailable"}
    for market in snapshot.get("markets") or []:
        if isinstance(market, dict) and market.get("symbol") == "ETH":
            context = market.get("context") if isinstance(market.get("context"), dict) else {}
            price = _number(context.get("oraclePx")) or _number(context.get("markPx"))
            if price and price > 0:
                return price, {"status": "ok", "as_of": snapshot.get("as_of"), "stale": bool(snapshot.get("stale"))}
    return None, {"status": "missing"}


def _gwei(wei: int | None) -> float | None:
    return None if wei is None else round(wei / WEI_PER_GWEI, 6)


def _chain_row(spec: ChainSpec, fees: dict[str, Any] | None, error: str | None, eth_usd: float | None) -> dict[str, Any]:
    base = fees.get("base_fee_wei") if fees else None
    priority = fees.get("priority_fee_wei") if fees else None
    gas_price = fees.get("gas_price_wei") if fees else None
    # Effective price per gas: base + priority when EIP-1559 data exists, else the legacy gas price.
    effective = (base + (priority or 0)) if base is not None else gas_price
    transfer_eth = effective * SIMPLE_TRANSFER_GAS / WEI_PER_ETH if effective is not None else None
    return {
        "id": spec.chain_id,
        "label": {"ko": spec.label_ko, "en": spec.label_en},
        "layer": spec.layer,
        "status": "ok" if fees else (error or "unavailable"),
        "base_fee_gwei": _gwei(base),
        "priority_fee_gwei": _gwei(priority),
        "gas_price_gwei": _gwei(gas_price),
        "effective_gwei": _gwei(effective),
        "supports_1559": bool(fees.get("supports_1559")) if fees else None,
        "transfer": {
            "gas": SIMPLE_TRANSFER_GAS,
            "eth": round(transfer_eth, 9) if transfer_eth is not None else None,
            "usd": round(transfer_eth * eth_usd, 6) if transfer_eth is not None and eth_usd else None,
            "basis": (
                f"effective gas price × {SIMPLE_TRANSFER_GAS:,} gas (plain ETH transfer); "
                + ("L2 execution leg only — the L1 data fee is not included" if spec.layer == "L2" else "mainnet")
            ),
        },
        "block": fees.get("block") if fees else None,
        "as_of": fees.get("as_of") if fees else None,
        "stale": bool(fees.get("stale")) if fees else None,
        "rpc_host": fees.get("host") if fees else None,
        "documentation_url": spec.docs_url,
    }


_DISCLAIMER = {
    "ko": (
        "RPC가 보고하는 다음 블록 기본 수수료·우선 수수료(50분위)·가스 가격의 참고값입니다. 실제 수수료는 트랜잭션 종류·"
        "혼잡도·지갑 설정에 따라 달라지고, L2는 L1 데이터 수수료가 빠져 있습니다. 투자 권유가 아닙니다."
    ),
    "en": (
        "Reference values from the RPC: next-block base fee, p50 priority fee and gas price. Actual fees depend on "
        "the transaction, congestion and wallet settings; L2 rows omit the L1 data fee. Not a recommendation."
    ),
}

_METHOD = {
    "ko": (
        "eth_feeHistory(1블록, p50)의 다음 블록 baseFeePerGas + 우선 수수료 = 유효 가스 가격; 미지원 체인은 eth_gasPrice. "
        "전송 비용 = 유효 가격 × 21,000 gas, USD 환산은 Hyperliquid ETH 오라클가. 전부 표시값의 산술 파생입니다."
    ),
    "en": (
        "Next-block baseFeePerGas from eth_feeHistory (1 block, p50) + priority fee = effective gas price; eth_gasPrice "
        "where 1559 data is unavailable. Transfer cost = effective price × 21,000 gas; USD via the Hyperliquid ETH "
        "oracle. Arithmetic on displayed values."
    ),
}

_RIGHTS = {
    "status": "public_chain_state",
    "notice": (
        "Gas values are public blockchain state read through the operator's own RPC-provider account under that "
        "provider's terms; no public RPC endpoint is used. Not a recommendation."
    ),
    "notice_localized": {
        "ko": "가스 값은 운영자 계정의 RPC 제공자를 통해 읽은 공개 체인 상태이며 해당 제공자 약관을 따릅니다. 퍼블릭 RPC는 쓰지 않습니다. 투자 권유가 아닙니다.",
        "en": "Gas values are public chain state read through the operator's own RPC-provider account under that provider's terms; no public RPC endpoint is used. Not a recommendation.",
    },
}


def build_crypto_gas(
    providers: dict[str, FeeProvider] | None = None,
    hl_provider: DexProvider | None = None,
) -> dict[str, Any]:
    urls = configured_urls()

    targets: list[tuple[ChainSpec, FeeProvider]] = []
    for spec in CHAINS:
        provider = (providers or {}).get(spec.chain_id)
        if provider is None:
            url = urls.get(spec.chain_id)
            if not url:
                continue
            provider = _provider_for(spec.chain_id, url)
        targets.append((spec, provider))

    def read(provider: FeeProvider) -> tuple[dict[str, Any] | None, str | None]:
        try:
            return provider.fetch_fees(), None
        except RateLimited:
            return None, "rate_limited"
        except DataUnavailable:
            return None, "unavailable"

    # The chains do not depend on each other and the ETH price depends on none
    # of them, so the wall time is the slowest call rather than their sum.
    with ThreadPoolExecutor(max_workers=len(targets) + 1) as pool:
        price = pool.submit(_eth_usd, hl_provider or _HL_PROVIDER)
        reads = [pool.submit(read, provider) for _spec, provider in targets]
        eth_usd, eth_meta = price.result()
        results = [future.result() for future in reads]

    chains = [
        _chain_row(spec, fees, error, eth_usd)
        for (spec, _provider), (fees, error) in zip(targets, results, strict=True)
    ]
    return {
        "generated_at": _iso_utc(),
        "status": "ok" if any(row["status"] == "ok" for row in chains) else "unavailable",
        "chains": chains,
        "eth_usd": {"value": eth_usd, **eth_meta, "source": "Hyperliquid oraclePx"},
        "rpc": {
            "provider_name": config.CHAIN_RPC_PROVIDER_NAME or None,
            "hosts": sorted({host_label(url) for url in urls.values()}),
            "note": "operator account; URLs and keys are never exposed",
        },
        "methodology": _METHOD,
        "disclaimer": _DISCLAIMER,
        "rights": _RIGHTS,
    }
