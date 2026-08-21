"""Minimal EVM JSON-RPC reader — ``eth_feeHistory`` and ``eth_gasPrice`` only.

Endpoint URLs come from the operator's own RPC-provider account (Alchemy, Infura,
…) through environment variables; no public endpoint is baked in, because the
public ones we checked either forbid redistribution (PublicNode ToS), say they
are "not suitable for production traffic" (Base docs) or require a commercial
plan (docs/DATA_SOURCE_REGISTER.md §3.21).  The URL usually embeds the API key,
so it is never echoed into payloads, logs or exceptions — only a short host
label is.

Reads are public chain state (base fee, priority-fee percentile, gas price);
nothing here sends transactions or touches an account.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from .base import DataUnavailable, RateLimited
from .http_cache import TtlCache

DEFAULT_TIMEOUT = 6.0
DEFAULT_RETRIES = 1
DEFAULT_TTL = 30.0
DEFAULT_STALE_TTL = 300.0
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"
WEI_PER_GWEI = 1_000_000_000
WEI_PER_ETH = 10**18
# eth_feeHistory: one block, latest, 50th-percentile priority fee.
FEE_HISTORY_PARAMS: list[Any] = ["0x1", "latest", [50]]

Transport = Callable[[str, dict[str, Any], float], Any]


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _hex_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.startswith("0x"):
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None


def host_label(url: str) -> str:
    """A displayable, key-free name for an RPC URL (hostname only)."""
    try:
        return urllib.parse.urlsplit(url).hostname or "rpc"
    except ValueError:
        return "rpc"


def _default_transport(url: str, payload: dict[str, Any], timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def parse_fee_history(raw: Any) -> dict[str, Any]:
    """``eth_feeHistory`` → next-block base fee and the p50 priority fee, in wei."""
    result = raw.get("result") if isinstance(raw, dict) else None
    if not isinstance(result, dict):
        raise DataUnavailable("eth_feeHistory returned no result")
    base_fees = [_hex_int(item) for item in result.get("baseFeePerGas") or []]
    base_fees = [item for item in base_fees if item is not None]
    if not base_fees:
        raise DataUnavailable("eth_feeHistory carried no baseFeePerGas")
    rewards = result.get("reward") or []
    priority = None
    if rewards and isinstance(rewards[-1], list) and rewards[-1]:
        priority = _hex_int(rewards[-1][0])
    return {
        "base_fee_wei": base_fees[-1],  # the last entry is the *next* block's base fee
        "priority_fee_wei": priority,
        "oldest_block": _hex_int(result.get("oldestBlock")),
    }


class EvmRpcProvider:
    name = "evm_rpc"

    def __init__(
        self,
        url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        ttl: float = DEFAULT_TTL,
        stale_ttl: float = DEFAULT_STALE_TTL,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not url or not url.strip().lower().startswith(("http://", "https://")):
            raise ValueError("RPC url must be an http(s) URL")
        self._url = url.strip()
        self.host = host_label(self._url)
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep
        self._cache = TtlCache(ttl=ttl, stale_ttl=stale_ttl)

    def clear_cache(self) -> None:
        self._cache.clear()

    def fetch_fees(self) -> dict[str, Any]:
        """Next-block base fee + p50 priority fee via eth_feeHistory; gas price as fallback."""

        def load() -> dict[str, Any]:
            fetched_at = _utc_iso(self._wall_clock())
            base_fee = priority = None
            block = None
            supports_1559 = True
            try:
                history = parse_fee_history(self._call("eth_feeHistory", FEE_HISTORY_PARAMS))
                base_fee, priority, block = history["base_fee_wei"], history["priority_fee_wei"], history["oldest_block"]
            except DataUnavailable:
                supports_1559 = False
            gas_price = _hex_int((self._call("eth_gasPrice", []) or {}).get("result"))
            if base_fee is None and gas_price is None:
                raise DataUnavailable(f"{self.host} returned neither fee history nor gas price")
            return {
                "fetched_at": fetched_at,
                "as_of": fetched_at,
                "host": self.host,
                "supports_1559": supports_1559,
                "base_fee_wei": base_fee,
                "priority_fee_wei": priority,
                "gas_price_wei": gas_price,
                "block": block,
            }

        return self._cache.fetch(self._url, load, label=f"{self.host} fees")

    def _call(self, method: str, params: list[Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                raw = self._transport(self._url, payload, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    if attempt >= self.retries:
                        raise RateLimited(f"{self.host} rate limit reached") from exc
                elif exc.code in (401, 403):
                    raise DataUnavailable(f"{self.host} rejected the RPC credentials (HTTP {exc.code})") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(f"{self.host} rejected {method} with HTTP {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable(f"{self.host} returned an unreadable {method} response") from exc
            else:
                if not isinstance(raw, dict):
                    raise DataUnavailable(f"{self.host} returned a non-object {method} response")
                if raw.get("error") is not None:
                    raise DataUnavailable(f"{self.host} reported an error for {method}")
                return raw
            if attempt < self.retries:
                self._sleep(min(0.3 * (2**attempt), 1.0))
        raise DataUnavailable(f"{self.host} {method} is unavailable") from last_error
