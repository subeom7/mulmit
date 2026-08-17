"""Read-only FRED dashboard assembly from normalized local data."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from . import config, data_rights, store
from .providers.fred import (
    FRED_API_TERMS_URL,
    FRED_GROUPS,
    FRED_REQUIRED_NOTICE,
    FRED_RIGHTS_NOTICE,
    FRED_SERIES,
    FRED_SERIES_BY_ID,
    FRED_SITE_BASE,
    FRED_TERMS_URL,
    FRED_USER_TERMS,
    FredSeriesSpec,
)

HISTORY_DAYS = {
    "1y": 366,
    "2y": 366 * 2,
    "3y": 366 * 3,
    "5y": 366 * 5,
    "10y": 366 * 10,
    "max": None,
}

_OBSERVATION_GRACE_DAYS = {
    "D": 7,
    "W": 21,
    "M": 62,
    "Q": 124,
    "A": 550,
}
MAX_PUBLIC_OBSERVATIONS = 2500


class MacroDataDisabled(RuntimeError):
    """Raised when no macro provider lane may currently be served publicly."""


def _lane_for(_spec: FredSeriesSpec) -> str:
    """Every catalog entry is still FRED-sourced.

    P1 replaces this with the ``provider_id`` column on ``economic_series``.
    Keeping the lookup behind one function means that migration changes the
    mapping, not every call site.
    """
    return data_rights.FRED


def _utc_iso(epoch: float | None = None) -> str:
    moment = dt.datetime.fromtimestamp(epoch, tz=dt.UTC) if epoch else dt.datetime.now(dt.UTC)
    return moment.isoformat().replace("+00:00", "Z")


def _date_iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


def provider_metadata() -> dict[str, str]:
    return {
        "id": "fred",
        "name": "FRED®",
        "url": FRED_SITE_BASE,
    }


def attribution_metadata() -> dict[str, str]:
    return {
        "notice": FRED_REQUIRED_NOTICE,
        "terms_url": FRED_TERMS_URL,
        "api_terms_url": FRED_API_TERMS_URL,
        "user_terms": FRED_USER_TERMS,
    }


def _history_start(history: str) -> dt.date | None:
    if history not in HISTORY_DAYS:
        raise ValueError(f"unsupported history: {history}")
    days = HISTORY_DAYS[history]
    return None if days is None else dt.date.today() - dt.timedelta(days=days)


def _downsample_observations(
    observations: list[tuple[dt.date, float]],
) -> list[tuple[dt.date, float]]:
    """Bound JSON size while preserving both endpoints and broad chart shape."""
    if len(observations) <= MAX_PUBLIC_OBSERVATIONS:
        return observations
    last = len(observations) - 1
    indexes = {
        round(index * last / (MAX_PUBLIC_OBSERVATIONS - 1))
        for index in range(MAX_PUBLIC_OBSERVATIONS)
    }
    return [observations[index] for index in sorted(indexes)]


def _license_required_payload(spec: FredSeriesSpec) -> dict[str, Any]:
    """Describe a catalog item without redistributing its protected observations."""
    return {
        "id": spec.series_id,
        "key": spec.key,
        "group": spec.group,
        "label": {"ko": spec.label_ko, "en": spec.label_en},
        "description": {"ko": spec.description_ko, "en": spec.description_en},
        "status": "license_required",
        "source": {
            "provider": "FRED® catalog",
            "publisher": spec.publisher,
            "publisher_url": spec.publisher_url,
            "url": spec.series_url,
        },
        "units": {"long": None, "short": None},
        "frequency": {"long": None, "short": None},
        "seasonal_adjustment": {"long": None, "short": None},
        "latest": None,
        "previous": None,
        "change": None,
        "observation_start": None,
        "observation_end": None,
        "last_updated": None,
        "fetched_at": None,
        "freshness": {
            "status": "unavailable",
            "age_seconds": None,
            "max_age_seconds": config.FRED_MAX_AGE,
            "fetch_status": "unavailable",
            "data_status": "unavailable",
            "observation_age_seconds": None,
            "max_observation_age_seconds": None,
        },
        "rights": {
            "copyrighted": True,
            "public_display": False,
            "notice": (
                "Public observations are withheld until Mulmit has a redistribution "
                "license from the original publisher."
            ),
            "notice_ko": (
                "원 제공기관의 공개 재배포 허가를 확보하기 전까지 관측값을 제공하지 않습니다."
            ),
            "series_notes": "",
        },
        "observation_count": {
            "available": 0,
            "returned": 0,
            "downsampled": False,
            "limit": MAX_PUBLIC_OBSERVATIONS,
        },
        "observations": [],
    }


def _requires_license(spec: FredSeriesSpec, record: dict[str, Any] | None = None) -> bool:
    """Fail closed when either the catalog or current provider notes restrict reuse."""
    return not spec.public_web or bool(record and record.get("copyrighted"))


def _series_payload(
    spec: FredSeriesSpec,
    record: dict,
    history: str,
) -> dict[str, Any] | None:
    # Second line of defence. Callers already filter by lane, but this reader is
    # the only place that turns stored rows into public values, so it refuses on
    # its own rather than trusting whoever called it.
    if not data_rights.macro_lane_enabled(_lane_for(spec)):
        return None
    all_observations = store.load_fred_observations(
        spec.series_id,
        start=_history_start(history),
    )
    if not all_observations:
        return None
    observations = _downsample_observations(all_observations)

    latest_date, latest_value = observations[-1]
    previous = observations[-2] if len(observations) > 1 else None
    change = None
    if previous is not None:
        delta = latest_value - previous[1]
        change = {
            "value": delta,
            "percent": (delta / previous[1] * 100.0) if previous[1] != 0 else None,
        }

    fetched_at = record.get("fetched_at")
    age_seconds = max(0, round(time.time() - fetched_at)) if fetched_at else None
    fetch_is_fresh = (
        record.get("status") == "ok"
        and age_seconds is not None
        and age_seconds <= config.FRED_MAX_AGE
    )
    frequency_short = str(record.get("frequency_short") or "").upper()
    max_observation_age_days = _OBSERVATION_GRACE_DAYS.get(frequency_short[:1], 62)
    observation_age_days = max(0, (dt.date.today() - latest_date).days)
    data_is_fresh = observation_age_days <= max_observation_age_days
    is_fresh = fetch_is_fresh and data_is_fresh
    return {
        "id": spec.series_id,
        "key": spec.key,
        "group": spec.group,
        "label": {"ko": spec.label_ko, "en": spec.label_en},
        "description": {"ko": spec.description_ko, "en": spec.description_en},
        "status": record.get("status") or "ok",
        "source": {
            "provider": "FRED®",
            "publisher": record.get("publisher") or spec.publisher,
            "publisher_url": record.get("publisher_url") or spec.publisher_url,
            "url": record.get("series_url") or spec.series_url,
        },
        "units": {
            "long": record.get("units"),
            "short": record.get("units_short"),
        },
        "frequency": {
            "long": record.get("frequency"),
            "short": record.get("frequency_short"),
        },
        "seasonal_adjustment": {
            "long": record.get("seasonal_adjustment"),
            "short": record.get("seasonal_adjustment_short"),
        },
        "latest": {"date": latest_date.isoformat(), "value": latest_value},
        "previous": (
            {"date": previous[0].isoformat(), "value": previous[1]} if previous else None
        ),
        "change": change,
        "observation_start": _date_iso(record.get("observation_start")),
        "observation_end": _date_iso(record.get("observation_end")),
        "last_updated": record.get("provider_last_updated"),
        "fetched_at": _utc_iso(fetched_at) if fetched_at else None,
        "freshness": {
            "status": "fresh" if is_fresh else "stale",
            "age_seconds": age_seconds,
            "max_age_seconds": config.FRED_MAX_AGE,
            "fetch_status": "fresh" if fetch_is_fresh else "stale",
            "data_status": "fresh" if data_is_fresh else "stale",
            "observation_age_seconds": observation_age_days * 24 * 60 * 60,
            "max_observation_age_seconds": max_observation_age_days * 24 * 60 * 60,
        },
        "rights": {
            "copyrighted": bool(record.get("copyrighted")),
            "public_display": True,
            "notice": FRED_RIGHTS_NOTICE,
            "series_notes": str(record.get("notes") or "")[:2000],
        },
        "observation_count": {
            "available": len(all_observations),
            "returned": len(observations),
            "downsampled": len(observations) < len(all_observations),
            "limit": MAX_PUBLIC_OBSERVATIONS,
        },
        "observations": [
            {"date": date.isoformat(), "value": value} for date, value in observations
        ],
    }


def build_macro_snapshot(history: str = "3y") -> dict[str, Any]:
    _history_start(history)  # validate even when the database is empty
    servable = [spec for spec in FRED_SERIES if data_rights.macro_lane_enabled(_lane_for(spec))]
    servable_ids = {spec.series_id for spec in servable}
    disabled = [spec.series_id for spec in FRED_SERIES if spec.series_id not in servable_ids]
    if not servable:
        # Every lane is closed, so there is nothing to shape a 200 around. The
        # route turns this into a structured 503 with no public cache headers.
        raise MacroDataDisabled(", ".join(sorted({_lane_for(spec) for spec in FRED_SERIES})))

    records = {
        record["series_id"]: record
        for record in store.list_fred_series(spec.series_id for spec in servable)
    }
    payloads: list[dict[str, Any]] = []
    missing: list[str] = []
    restricted: list[str] = []
    for spec in servable:
        record = records.get(spec.series_id)
        if _requires_license(spec, record):
            payloads.append(_license_required_payload(spec))
            restricted.append(spec.series_id)
            continue
        payload = _series_payload(spec, record, history) if record else None
        if payload is None:
            missing.append(spec.series_id)
        else:
            payloads.append(payload)

    latest_dates = [
        item["latest"]["date"]
        for item in payloads
        if isinstance(item.get("latest"), dict) and item["latest"].get("date")
    ]
    return {
        "generated_at": _utc_iso(),
        "as_of": max(latest_dates) if latest_dates else None,
        "history": history,
        "provider": provider_metadata(),
        "attribution": attribution_metadata(),
        "lanes": {
            "enabled": data_rights.enabled_macro_lanes(),
            "disabled_series": disabled,
        },
        "groups": [
            {
                "id": group.group_id,
                "label": {"ko": group.label_ko, "en": group.label_en},
                "series_ids": [
                    spec.series_id for spec in servable if spec.group == group.group_id
                ],
            }
            for group in FRED_GROUPS
        ],
        "series": payloads,
        "missing": missing,
        "restricted": restricted,
        "disabled": disabled,
    }


def build_macro_series(series_id: str, history: str = "3y") -> dict[str, Any] | None:
    _history_start(history)
    spec = FRED_SERIES_BY_ID.get(series_id.strip().upper())
    if spec is None:
        raise KeyError(series_id)
    if not data_rights.macro_lane_enabled(_lane_for(spec)):
        raise MacroDataDisabled(_lane_for(spec))
    record = store.get_fred_series(spec.series_id)
    if _requires_license(spec, record):
        return {
            "generated_at": _utc_iso(),
            "history": history,
            "provider": provider_metadata(),
            "attribution": attribution_metadata(),
            "series": _license_required_payload(spec),
        }
    if record is None:
        return None
    payload = _series_payload(spec, record, history)
    if payload is None:
        return None
    return {
        "generated_at": _utc_iso(),
        "history": history,
        "provider": provider_metadata(),
        "attribution": attribution_metadata(),
        "series": payload,
    }
