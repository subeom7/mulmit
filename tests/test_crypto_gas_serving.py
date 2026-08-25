"""How the gas strip is served — the visitor must not pay for the upstream reads.

Building the strip is four upstream round trips. Measured against production on
2026-08-22 a cold call took 1.57s and a warm one 0.03s, so under the previous
shape one visitor every 30 seconds paid the whole 1.5s. These cover the two
changes: the reads run concurrently, and a recent strip is served immediately
while a single background thread refreshes it.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from app import config, crypto_gas


class SlowProvider:
    """Takes `delay` seconds per read, like a real RPC round trip."""

    def __init__(self, delay: float, base_fee: int = 20_000_000_000) -> None:
        self.delay = delay
        self.base_fee = base_fee
        self.calls = 0

    def fetch_fees(self) -> dict[str, Any]:
        self.calls += 1
        time.sleep(self.delay)
        return {
            "chain_id": "ethereum",
            "base_fee_wei": self.base_fee,
            "priority_fee_wei": 1_000_000_000,
            "gas_price_wei": self.base_fee + 1_000_000_000,
            "block_number": 21_000_000,
            "as_of": "2026-08-22T12:00:00Z",
        }


class SlowHl:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def fetch_dex(self, dex: str) -> dict[str, Any]:
        time.sleep(self.delay)
        return {
            "as_of": "2026-08-22T12:00:00Z",
            "markets": [{"symbol": "ETH", "context": {"oraclePx": "2500"}}],
        }


def _settle_background_refresh(timeout: float = 5.0) -> None:
    """배경 새로고침이 끝날 때까지 기다린다.

    `_refresh_in_background`는 `_build_and_store()`가 **끝난 뒤** `finally`에서
    플래그를 내린다. 그래서 플래그가 내려갔다는 것은 저장까지 마쳤다는 뜻이다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with crypto_gas._snapshot_lock:
            if not crypto_gas._refreshing:
                return
        time.sleep(0.01)
    raise AssertionError("배경 새로고침이 시간 안에 끝나지 않았다")


@pytest.fixture(autouse=True)
def clean_snapshot():
    """스냅샷 상태를 테스트마다 비운다 — **그리고 스레드를 넘기지 않는다.**

    `reset_snapshot()`만으로는 부족했다. 이 모듈의 몇몇 테스트는 배경 새로고침
    스레드를 띄우는데, 그 스레드가 **자기 테스트보다 오래 살아남아** 다음
    테스트가 도는 동안 `_snapshot_at`을 갱신한다. 그러면 다음 테스트가 방금
    만든 값을 "아직 신선하다"고 오해하고, 새로 만들어야 할 자리에서 옛것을
    내보낸다.

    2026-08-25에 CI에서 `test_a_strip_too_old_to_trust_is_rebuilt_in_the_request`가
    `build-1` 대 `build-2`로 깨졌다. 로컬에서는 통과했고 재실행하면 통과했다 —
    **머지된 뒤에야 main에서 터지는 종류**라 배포가 조용히 막힌다. 이 저장소는
    머지가 곧 배포라서 플레이크 하나가 배포 실패와 같은 값이다.
    """
    crypto_gas.reset_snapshot()
    yield
    _settle_background_refresh()
    crypto_gas.reset_snapshot()


@pytest.fixture
def chains_configured(monkeypatch):
    for spec in crypto_gas.CHAINS[:3]:
        monkeypatch.setattr(config, spec.env_name, "https://rpc.example/key", raising=False)
    return [spec.chain_id for spec in crypto_gas.CHAINS[:3]]


def test_the_chain_reads_run_concurrently(chains_configured, monkeypatch):
    """Three 0.2s chains plus a 0.2s price read must not cost 0.8s in a row."""
    providers = {chain: SlowProvider(0.2) for chain in chains_configured}
    started = time.perf_counter()
    payload = crypto_gas.build_crypto_gas(providers=providers, hl_provider=SlowHl(0.2))
    elapsed = time.perf_counter() - started

    assert len(payload["chains"]) == len(chains_configured)
    assert all(row["status"] == "ok" for row in payload["chains"])
    # Sequential would be ~0.8s. Concurrent is one delay plus scheduling.
    assert elapsed < 0.5, f"reads look sequential: {elapsed:.2f}s"


def test_a_recent_strip_is_served_without_rebuilding(monkeypatch):
    builds = []

    def fake_build(**_kwargs):
        builds.append(1)
        return {"generated_at": f"build-{len(builds)}", "chains": []}

    monkeypatch.setattr(crypto_gas, "build_crypto_gas", fake_build)
    first = crypto_gas.snapshot()
    second = crypto_gas.snapshot()
    assert first["generated_at"] == "build-1"
    assert second["generated_at"] == "build-1"   # inside the TTL, no second build
    assert len(builds) == 1


def test_an_expired_strip_goes_out_at_once_and_refreshes_behind_it(monkeypatch):
    builds = []
    released = threading.Event()

    def fake_build(**_kwargs):
        builds.append(1)
        if len(builds) > 1:
            released.wait(2.0)     # the refresh is slow; the visitor must not wait for it
        return {"generated_at": f"build-{len(builds)}", "chains": []}

    monkeypatch.setattr(crypto_gas, "build_crypto_gas", fake_build)
    monkeypatch.setattr(crypto_gas, "SNAPSHOT_TTL", 0.01)

    crypto_gas.snapshot()
    time.sleep(0.05)   # the clock is coarse; make the strip measurably older than the TTL
    started = time.perf_counter()
    served = crypto_gas.snapshot()
    elapsed = time.perf_counter() - started

    assert served["generated_at"] == "build-1"    # the old strip, immediately
    assert elapsed < 0.3, f"the caller waited on the refresh: {elapsed:.2f}s"
    released.set()
    for _ in range(40):
        if len(builds) >= 2:
            break
        time.sleep(0.05)
    # Reading through snapshot() while the TTL is 0.01 would itself keep
    # starting refreshes, so raise it before checking what got stored.
    monkeypatch.setattr(crypto_gas, "SNAPSHOT_TTL", 60.0)
    for _ in range(40):
        if crypto_gas.snapshot()["generated_at"] == "build-2":
            break
        time.sleep(0.05)
    assert crypto_gas.snapshot()["generated_at"] == "build-2"
    assert len(builds) == 2


def test_only_one_refresh_runs_at_a_time(monkeypatch):
    builds = []
    hold = threading.Event()

    def fake_build(**_kwargs):
        builds.append(1)
        if len(builds) > 1:
            hold.wait(2.0)
        return {"generated_at": f"build-{len(builds)}", "chains": []}

    monkeypatch.setattr(crypto_gas, "build_crypto_gas", fake_build)
    monkeypatch.setattr(crypto_gas, "SNAPSHOT_TTL", 0.01)
    crypto_gas.snapshot()
    time.sleep(0.05)
    for _ in range(5):
        crypto_gas.snapshot()
    time.sleep(0.2)
    hold.set()
    # 스레드를 다음 테스트로 넘기지 않는다 — 넘기면 그 테스트가 플레이크가 된다.
    _settle_background_refresh()
    assert len(builds) == 2, f"five expired reads started {len(builds) - 1} refreshes"


def test_a_strip_too_old_to_trust_is_rebuilt_in_the_request(monkeypatch):
    builds = []

    def fake_build(**_kwargs):
        builds.append(1)
        return {"generated_at": f"build-{len(builds)}", "chains": []}

    monkeypatch.setattr(crypto_gas, "build_crypto_gas", fake_build)
    monkeypatch.setattr(crypto_gas, "SNAPSHOT_TTL", 0.01)
    monkeypatch.setattr(crypto_gas, "SNAPSHOT_MAX_STALE", 0.01)
    crypto_gas.snapshot()
    time.sleep(0.05)
    served = crypto_gas.snapshot()
    assert served["generated_at"] == "build-2"   # waited, rather than serving something stale
    assert len(builds) == 2
