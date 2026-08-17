"""Serving-side rights gates for every public data lane.

Reachable is not the same as redistributable. ``FRED_ENABLED=false`` used to
stop ingestion only, so a database that had been seeded earlier kept serving
FRED-derived numbers from the request path. Every public lane now asks here
before a stored value may leave the process.

The gate is per provider lane on purpose. Closing the FRED lane must not block
an approved New York Fed lane that lands later, and an unregistered provider id
must never resolve to "allowed" — adding a lane is a deliberate edit here, not
a side effect of writing rows into the database.
"""

from __future__ import annotations

from collections.abc import Callable

from . import config

# --- lane identifiers --------------------------------------------------------
FRED = "fred"
HYPERLIQUID_HIP3 = "hyperliquid_hip3"
LEGACY_PRICE_DATA = "legacy_price_data"

# --- structured client contracts --------------------------------------------
# The frontend keys off ``code``: these are disabled states, not retryable
# errors, so it must not offer "refresh and try again".
MACRO_DATA_DISABLED = {
    "code": "macro_data_disabled",
    "status": "disabled",
    "message": (
        "No approved macro data source is enabled. Stored values from disabled "
        "providers are withheld from the public API."
    ),
}

HIP3_PENDING_RIGHTS = {
    "code": "hip3_public_display_pending_rights",
    "status": "pending_rights",
    "message": (
        "Public display rights for Hyperliquid HIP-3 / trade.xyz data are not "
        "confirmed in writing, so Mulmit withholds the values."
    ),
}

NO_STORE_HEADERS = {"Cache-Control": "no-store"}

# Macro lanes and the flag that decides whether their stored rows may be served.
# Flags are read through ``config`` at call time so tests and a restart-free
# rollback both take effect immediately.
_MACRO_LANES: dict[str, Callable[[], bool]] = {
    FRED: lambda: config.FRED_ENABLED,
}


def macro_lane_enabled(provider_id: str) -> bool:
    """Fail closed for any lane that has not been registered above."""
    gate = _MACRO_LANES.get(provider_id)
    return bool(gate()) if gate is not None else False


def enabled_macro_lanes() -> list[str]:
    return [provider_id for provider_id in _MACRO_LANES if macro_lane_enabled(provider_id)]


def macro_serving_enabled() -> bool:
    return bool(enabled_macro_lanes())


def hip3_public_display_enabled() -> bool:
    return bool(config.HIP3_PUBLIC_DISPLAY_ENABLED)


def lane_report() -> dict[str, dict[str, str]]:
    """Operator-facing lane summary for ``/api/status``."""
    report: dict[str, dict[str, str]] = {
        LEGACY_PRICE_DATA: {
            "status": "enabled" if config.LEGACY_PRICE_DATA_ENABLED else "disabled",
            "gate": "LEGACY_PRICE_DATA_ENABLED",
        },
        HYPERLIQUID_HIP3: {
            "status": "enabled" if hip3_public_display_enabled() else "pending_rights",
            "gate": "HIP3_PUBLIC_DISPLAY_ENABLED",
        },
    }
    for provider_id in _MACRO_LANES:
        report[f"macro:{provider_id}"] = {
            "status": "enabled" if macro_lane_enabled(provider_id) else "disabled",
            "gate": "FRED_ENABLED" if provider_id == FRED else f"{provider_id.upper()}_ENABLED",
        }
    return report
