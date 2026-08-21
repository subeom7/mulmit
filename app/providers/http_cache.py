"""Single-flight TTL cache with stale fallback, shared by the small JSON providers.

Same shape as the cache inside :class:`app.providers.hyperliquid.HyperliquidProvider`:
one loader call per key per TTL no matter how many request threads arrive,
the last good snapshot served (marked ``stale``) for ``stale_ttl`` after a
failure, and a cooldown so an outage never becomes one upstream call per HTTP
request.  Instance-level state, so two providers never share entries.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable
from typing import Any

from .base import DataUnavailable, RateLimited

Loader = Callable[[], dict[str, Any]]


class TtlCache:
    def __init__(
        self,
        *,
        ttl: float,
        stale_ttl: float,
        max_wait_seconds: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl = max(0.0, float(ttl))
        self.stale_ttl = max(self.ttl, float(stale_ttl))
        self.max_wait_seconds = max(0.5, float(max_wait_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}
        self._failures: dict[str, tuple[float, str]] = {}
        self._inflight: dict[str, threading.Event] = {}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._failures.clear()

    def _decorate(
        self, entry: tuple[float, dict[str, Any]], *, cached: bool, stale: bool, error: str | None
    ) -> dict[str, Any]:
        stored_at, raw = entry
        snapshot = copy.deepcopy(raw)
        snapshot["cached"] = cached
        snapshot["stale"] = stale
        snapshot["age_seconds"] = round(max(0.0, self._clock() - stored_at), 3)
        if error is not None:
            snapshot["error"] = error
        else:
            snapshot.pop("error", None)
        return snapshot

    def fetch(self, key: str, loader: Loader, *, label: str) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            existing = self._entries.get(key)
            if existing is not None and now - existing[0] <= self.ttl:
                return self._decorate(existing, cached=True, stale=False, error=None)
            failure = self._failures.get(key)
            if failure is not None and now < failure[0]:
                if existing is not None and now - existing[0] <= self.stale_ttl:
                    return self._decorate(existing, cached=True, stale=True, error=failure[1])
                if failure[1] == "RateLimited":
                    raise RateLimited(f"{label} retry is cooling down after a rate limit")
                raise DataUnavailable(f"{label} retry is cooling down after an upstream failure")
            if failure is not None:
                self._failures.pop(key, None)
            event = self._inflight.get(key)
            owner = event is None
            if owner:
                event = threading.Event()
                self._inflight[key] = event

        assert event is not None
        if not owner:
            if not event.wait(timeout=self.max_wait_seconds):
                raise DataUnavailable(f"Timed out waiting for a coalesced {label} request")
            with self._lock:
                completed = self._entries.get(key)
                failure = self._failures.get(key)
            if completed is None:
                if failure is not None and failure[1] == "RateLimited":
                    raise RateLimited(f"Coalesced {label} request was rate limited")
                raise DataUnavailable(f"Coalesced {label} request failed")
            is_stale = self._clock() - completed[0] > self.ttl
            return self._decorate(
                completed, cached=True, stale=is_stale,
                error=failure[1] if is_stale and failure is not None else None,
            )

        try:
            snapshot = loader()
            entry = (self._clock(), copy.deepcopy(snapshot))
            with self._lock:
                self._entries[key] = entry
                self._failures.pop(key, None)
            return self._decorate(entry, cached=False, stale=False, error=None)
        except (DataUnavailable, RateLimited) as exc:
            with self._lock:
                fallback = self._entries.get(key)
                failed_at = self._clock()
                self._failures[key] = (failed_at + max(self.ttl, 1.0), type(exc).__name__)
            if fallback is not None and failed_at - fallback[0] <= self.stale_ttl:
                return self._decorate(fallback, cached=True, stale=True, error=type(exc).__name__)
            raise
        finally:
            with self._lock:
                done = self._inflight.pop(key, None)
                if done is not None:
                    done.set()
