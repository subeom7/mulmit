"""Read-only macro dashboard assembly from normalized local data.

Reads the provider-neutral ``economic_series`` tables first and falls back to
the legacy ``fred_*`` tables only for series that have not been migrated yet.
Nothing here calls a provider.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable, Iterable
from typing import Any

from . import config, data_rights, store
from .providers.bls import (
    BLS_ATTRIBUTION,
    BLS_PROVIDER_ID,
    BLS_PUBLISHER_URL,
    BLS_TERMS_URL,
)
from .providers.ecos import (
    ECOS_ATTRIBUTION,
    ECOS_PROVIDER_ID,
    ECOS_PUBLISHER_URL,
    ECOS_TERMS_URL,
)
from .providers.fedboard import (
    FEDBOARD_ATTRIBUTION,
    FEDBOARD_DDP_TRANSITION_URL,
    FEDBOARD_PROVIDER_ID,
    FEDBOARD_PUBLISHER_URL,
)
from .providers.fred import (
    FRED_API_TERMS_URL,
    FRED_GROUPS,
    FRED_PROVIDER_ID,
    FRED_REQUIRED_NOTICE,
    FRED_RIGHTS_NOTICE,
    FRED_SERIES,
    FRED_SERIES_BY_ID,
    FRED_SERIES_BY_KEY,
    FRED_SITE_BASE,
    FRED_TERMS_URL,
    FRED_USER_TERMS,
    FredSeriesSpec,
    rights_status_for,
)
from .providers.fsc import (
    FSC_ATTRIBUTION,
    FSC_PROVIDER_ID,
    FSC_PUBLISHER,
    FSC_PUBLISHER_URL,
    FSC_TERMS_URL,
)
from .providers.nyfed import NYFED_PROVIDER_ID, NYFED_PUBLISHER_URL, NYFED_TERMS_URL
from .providers.nyfed import attribution as nyfed_attribution
from .providers.ofr import (
    OFR_ATTRIBUTION,
    OFR_LEGAL_NOTICES_URL,
    OFR_PROVIDER_ID,
    OFR_PUBLISHER_URL,
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

# ``source.provider`` carries the stable machine id, per the published contract.
# ``source.provider_name`` is what a card footer should print, so the UI never
# has to hardcode a lookup table of its own.
PROVIDER_NAMES = {
    "fred": "FRED®",
    NYFED_PROVIDER_ID: "Federal Reserve Bank of New York",
    FEDBOARD_PROVIDER_ID: "Federal Reserve Board",
    BLS_PROVIDER_ID: "U.S. Bureau of Labor Statistics",
    FSC_PROVIDER_ID: FSC_PUBLISHER,
    ECOS_PROVIDER_ID: "한국은행 (ECOS)",
    OFR_PROVIDER_ID: "Office of Financial Research (U.S. Treasury)",
    "eia": "U.S. Energy Information Administration",
    "federal_reserve": "Federal Reserve Board",
    "treasury": "U.S. Department of the Treasury",
}

# Some licences are conditional on carrying a specific source identifier. The
# New York Fed prescribes exact wording, so it ships with every value rather
# than living only in a document nobody reads at render time.
PROVIDER_NOTICES: dict[str, Callable[[], str]] = {
    "fred": lambda: FRED_RIGHTS_NOTICE,
    NYFED_PROVIDER_ID: nyfed_attribution,
    FEDBOARD_PROVIDER_ID: lambda: FEDBOARD_ATTRIBUTION,
    BLS_PROVIDER_ID: lambda: BLS_ATTRIBUTION,
    FSC_PROVIDER_ID: lambda: FSC_ATTRIBUTION,
    ECOS_PROVIDER_ID: lambda: ECOS_ATTRIBUTION,
    OFR_PROVIDER_ID: lambda: OFR_ATTRIBUTION,
}


def _provider_notice(provider_id: str) -> str:
    notice = PROVIDER_NOTICES.get(provider_id)
    return notice() if notice else ""


class MacroDataDisabled(RuntimeError):
    """Raised when no macro provider lane may currently be served publicly."""


def _lane_for(spec: FredSeriesSpec, record: dict[str, Any] | None = None) -> str:
    """Which provider lane decides whether this series may be served.

    The stored row is the authority once a series has been collected through
    the neutral tables, so an approved NY Fed feed answers for itself even
    though it happens to share a catalog entry with the FRED adapter. The
    catalog is only the fallback for a series nothing has collected yet.
    """
    if record and record.get("provider_id"):
        return str(record["provider_id"])
    return FRED_PROVIDER_ID


def _rights_status_for(spec: FredSeriesSpec, record: dict[str, Any] | None) -> str:
    """Row first, catalog second, with one aggregator-specific safety net.

    FRED relays series owned by third parties and flags them by writing a
    copyright claim into the series notes. That is the data owner speaking after
    our catalog was written, so on the FRED lane it downgrades an otherwise
    approved series. It is deliberately not applied to lanes that publish their
    own data: the New York Fed asserts copyright over content it then licenses
    to us, so the same words mean the opposite thing there.
    """
    if record:
        provider_id = _lane_for(spec, record)
        notes = str(record.get("notes") or "").lower()
        if provider_id == FRED_PROVIDER_ID and "copyright" in notes:
            return "license_required"
        if record.get("rights_status"):
            return str(record["rights_status"])
    return rights_status_for(spec)


def _utc_iso(epoch: float | None = None) -> str:
    moment = dt.datetime.fromtimestamp(epoch, tz=dt.UTC) if epoch else dt.datetime.now(dt.UTC)
    return moment.isoformat().replace("+00:00", "Z")


def _date_iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


PROVIDER_URLS = {
    FRED_PROVIDER_ID: FRED_SITE_BASE,
    NYFED_PROVIDER_ID: NYFED_PUBLISHER_URL,
    FEDBOARD_PROVIDER_ID: FEDBOARD_PUBLISHER_URL,
    BLS_PROVIDER_ID: BLS_PUBLISHER_URL,
    FSC_PROVIDER_ID: FSC_PUBLISHER_URL,
    ECOS_PROVIDER_ID: ECOS_PUBLISHER_URL,
    OFR_PROVIDER_ID: OFR_PUBLISHER_URL,
}

# What each lane requires be shown when its values are published.
PROVIDER_ATTRIBUTION: dict[str, Callable[[], dict[str, str]]] = {
    FRED_PROVIDER_ID: lambda: {
        "provider": FRED_PROVIDER_ID,
        "name": PROVIDER_NAMES[FRED_PROVIDER_ID],
        "notice": FRED_REQUIRED_NOTICE,
        "terms_url": FRED_TERMS_URL,
        "api_terms_url": FRED_API_TERMS_URL,
        "user_terms": FRED_USER_TERMS,
    },
    NYFED_PROVIDER_ID: lambda: {
        "provider": NYFED_PROVIDER_ID,
        "name": PROVIDER_NAMES[NYFED_PROVIDER_ID],
        "notice": nyfed_attribution(),
        "terms_url": NYFED_TERMS_URL,
    },
    FEDBOARD_PROVIDER_ID: lambda: {
        "provider": FEDBOARD_PROVIDER_ID,
        "name": PROVIDER_NAMES[FEDBOARD_PROVIDER_ID],
        "notice": FEDBOARD_ATTRIBUTION,
        "terms_url": FEDBOARD_DDP_TRANSITION_URL,
    },
    BLS_PROVIDER_ID: lambda: {
        "provider": BLS_PROVIDER_ID,
        "name": PROVIDER_NAMES[BLS_PROVIDER_ID],
        "notice": BLS_ATTRIBUTION,
        "terms_url": BLS_TERMS_URL,
    },
    FSC_PROVIDER_ID: lambda: {
        "provider": FSC_PROVIDER_ID,
        "name": PROVIDER_NAMES[FSC_PROVIDER_ID],
        "notice": FSC_ATTRIBUTION,
        "terms_url": FSC_TERMS_URL,
    },
    ECOS_PROVIDER_ID: lambda: {
        "provider": ECOS_PROVIDER_ID,
        "name": PROVIDER_NAMES[ECOS_PROVIDER_ID],
        "notice": ECOS_ATTRIBUTION,
        "terms_url": ECOS_TERMS_URL,
    },
    OFR_PROVIDER_ID: lambda: {
        "provider": OFR_PROVIDER_ID,
        "name": PROVIDER_NAMES[OFR_PROVIDER_ID],
        "notice": OFR_ATTRIBUTION,
        "terms_url": OFR_LEGAL_NOTICES_URL,
    },
}


def provider_metadata() -> dict[str, str]:
    """Name the lanes actually serving, not the one that used to.

    Attributing New York Fed rates to FRED would credit an aggregator that is
    switched off for data it never supplied.
    """
    lanes = data_rights.enabled_macro_lanes()
    if len(lanes) == 1:
        lane = lanes[0]
        return {
            "id": lane,
            "name": PROVIDER_NAMES.get(lane, lane),
            "url": PROVIDER_URLS.get(lane, ""),
        }
    if not lanes:
        return {"id": "none", "name": "", "url": ""}
    return {
        "id": "multi-source",
        "name": " + ".join(PROVIDER_NAMES.get(lane, lane) for lane in lanes),
        "url": "",
    }


def attribution_metadata() -> dict[str, Any]:
    """Every serving lane's required notice, in one place.

    ``providers`` is the list the UI should render. The flat keys are kept for
    the single-lane case the published contract already described.
    """
    entries = [
        build()
        for lane, build in PROVIDER_ATTRIBUTION.items()
        if data_rights.macro_lane_enabled(lane)
    ]
    payload: dict[str, Any] = {"providers": entries}
    if entries:
        payload.update({key: value for key, value in entries[0].items() if key != "provider"})
    return payload


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


def _weekly_observations(
    observations: list[tuple[dt.date, float]],
) -> list[tuple[dt.date, float]]:
    """One point per ISO week — the last value actually published that week.

    Never an average. An average is a number the source never printed, and this
    file only ever hands out values as published. Taking the last observation of
    each week keeps every point real, and the most recent observation always
    survives because the current (partial) week is its own group.

    Idempotent for anything weekly or sparser: a monthly series has at most one
    observation per week, so grouping changes nothing. Only dense daily series
    actually shrink — which is the point.
    """
    by_week: dict[tuple[int, int], tuple[dt.date, float]] = {}
    for date, value in observations:
        iso = date.isocalendar()
        by_week[(iso[0], iso[1])] = (date, value)
    return [by_week[key] for key in sorted(by_week)]


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


_MONTHS_EN = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


# Lanes whose catalog entries carry a publisher-prescribed citation template.
_CITING_LANES = frozenset({FRED_PROVIDER_ID, OFR_PROVIDER_ID})


def _citation_for(
    spec: FredSeriesSpec, provider_id: str, fetched_at: float | None
) -> str | None:
    """The publisher-prescribed citation, dated to when the data was retrieved.

    St. Louis Fed's written reply (2026-08-18) asks that the suggested citation
    accompany the series with the access date, because economic series are
    revised and the retrieval date is part of the reference. The OFR's page
    gives its own suggested citation with an "(accessed ...)" slot, so its
    lane carries one the same way.
    """
    if not spec.citation or provider_id not in _CITING_LANES:
        return None
    moment = (
        dt.datetime.fromtimestamp(fetched_at, dt.UTC) if fetched_at else dt.datetime.now(dt.UTC)
    )
    date_text = f"{_MONTHS_EN[moment.month - 1]} {moment.day}, {moment.year}"
    return spec.citation.format(date=date_text)


def _requires_license(spec: FredSeriesSpec, record: dict[str, Any] | None = None) -> bool:
    """Fail closed unless the effective rights verdict is an explicit approval."""
    return _rights_status_for(spec, record) != data_rights.SERVABLE_ROW_RIGHTS


def _load_record(spec: FredSeriesSpec) -> dict[str, Any] | None:
    """Neutral tables first, legacy FRED tables only while a series is unmigrated."""
    record = store.get_economic_series(spec.key)
    if record is not None:
        return record
    return _adapt_legacy(spec, store.get_fred_series(spec.series_id))


def _adapt_legacy(spec: FredSeriesSpec, record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Present a legacy ``fred_series`` row in the neutral shape.

    Transitional only. Once :func:`store.migrate_fred_series_to_economic` has
    run for a series, ``_load_record`` never reaches this.
    """
    if record is None:
        return None
    adapted = dict(record)
    adapted["provider_id"] = FRED_PROVIDER_ID
    adapted["provider_series_id"] = record.get("series_id")
    adapted["rights_status"] = (
        "license_required" if record.get("copyrighted") else rights_status_for(spec)
    )
    adapted["_legacy"] = True
    return adapted


def _load_observations(
    spec: FredSeriesSpec,
    record: dict[str, Any],
    start: dt.date | None,
) -> list[tuple[dt.date, float]]:
    if record.get("_legacy"):
        return store.load_fred_observations(spec.series_id, start=start)
    return store.load_economic_observations(spec.key, start=start)


def _series_payload(
    spec: FredSeriesSpec,
    record: dict,
    history: str,
    *,
    weekly: bool = False,
) -> dict[str, Any] | None:
    # Second line of defence. Callers already filter by lane, but this reader is
    # the only place that turns stored rows into public values, so it refuses on
    # its own rather than trusting whoever called it. Both gates are checked:
    # the provider lane and the row's own rights verdict.
    if not data_rights.series_values_servable(
        _lane_for(spec, record), _rights_status_for(spec, record)
    ):
        return None
    all_observations = _load_observations(spec, record, _history_start(history))
    if not all_observations:
        return None
    # The card's change is the move between the last two *published* values.
    # Reading it off the shipped list instead would silently turn it into a
    # week-over-week change the moment the list is sampled weekly.
    latest_date, latest_value = all_observations[-1]
    previous = all_observations[-2] if len(all_observations) > 1 else None

    observations = _weekly_observations(all_observations) if weekly else all_observations
    observations = _downsample_observations(observations)
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
    provider_id = _lane_for(spec, record)
    return {
        # ``id`` stays the provider's own series id and ``key`` the internal one,
        # which is what the published contract already promised.
        "id": record.get("provider_series_id") or spec.series_id,
        "key": spec.key,
        "group": spec.group,
        "label": {"ko": spec.label_ko, "en": spec.label_en},
        "description": {"ko": spec.description_ko, "en": spec.description_en},
        "status": record.get("status") or "ok",
        "source": {
            "provider": provider_id,
            "provider_name": PROVIDER_NAMES.get(provider_id, provider_id),
            "provider_series_id": record.get("provider_series_id") or spec.series_id,
            # Prefer the original publisher over the aggregator that relayed it.
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
            "notice": _provider_notice(provider_id),
            "citation": _citation_for(spec, provider_id, fetched_at),
            "provider": provider_id,
            "series_notes": str(record.get("notes") or "")[:2000],
        },
        "observation_count": {
            "available": len(all_observations),
            "returned": len(observations),
            "downsampled": len(observations) < len(all_observations),
            "limit": MAX_PUBLIC_OBSERVATIONS,
            "sampling": "weekly" if weekly else "full",
        },
        "observations": [
            {"date": date.isoformat(), "value": value} for date, value in observations
        ],
    }


def _load_records(specs: Iterable[FredSeriesSpec]) -> dict[str, dict[str, Any] | None]:
    """One batched read per table rather than a query per series."""
    specs = list(specs)
    neutral = {row["series_key"]: row for row in store.list_economic_series(s.key for s in specs)}
    unmigrated = [spec for spec in specs if spec.key not in neutral]
    legacy = (
        {row["series_id"]: row for row in store.list_fred_series(s.series_id for s in unmigrated)}
        if unmigrated
        else {}
    )
    return {
        spec.key: neutral.get(spec.key) or _adapt_legacy(spec, legacy.get(spec.series_id))
        for spec in specs
    }


def build_macro_snapshot(history: str = "3y") -> dict[str, Any]:
    _history_start(history)  # validate even when the database is empty
    records = _load_records(FRED_SERIES)
    servable = [
        spec
        for spec in FRED_SERIES
        if data_rights.macro_lane_enabled(_lane_for(spec, records.get(spec.key)))
    ]
    servable_ids = {spec.series_id for spec in servable}
    disabled = [spec.series_id for spec in FRED_SERIES if spec.series_id not in servable_ids]
    if not servable:
        # Every lane is closed, so there is nothing to shape a 200 around. The
        # route turns this into a structured 503 with no public cache headers.
        raise MacroDataDisabled(
            ", ".join(sorted({_lane_for(spec, records.get(spec.key)) for spec in FRED_SERIES}))
        )

    payloads: list[dict[str, Any]] = []
    missing: list[str] = []
    restricted: list[str] = []
    for spec in servable:
        record = records.get(spec.key)
        if _requires_license(spec, record):
            payloads.append(_license_required_payload(spec))
            restricted.append(spec.series_id)
            continue
        payload = _series_payload(spec, record, history, weekly=True) if record else None
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
        # The cards draw sparklines, and a sparkline does not need daily
        # resolution over three years — that shape cost 863KB uncompressed and
        # ~145ms of gzip on every request. One point per week is the same
        # picture; the full daily series is one request away and named here.
        "resolution": {
            "sampling": "weekly",
            "full_series_url": "/api/market/macro/{series_id}",
            "note_ko": (
                "차트용으로 주당 한 점씩만 싣습니다. 평균이 아니라 그 주에 실제로 발표된 "
                "마지막 값이고, 최신 관측치는 항상 포함됩니다. 카드의 최신값·전일대비는 "
                "주간 표본이 아니라 원본 관측치에서 계산합니다. 일간 전체는 "
                "/api/market/macro/{series_id}에서 받습니다."
            ),
            "note_en": (
                "Charts carry one point per week: not an average but the last value "
                "actually published that week, and the most recent observation is always "
                "included. The card's latest value and change come from the full series, "
                "not the weekly sample. Full daily history is at /api/market/macro/{series_id}."
            ),
        },
        "series": payloads,
        "missing": missing,
        "restricted": restricted,
        "disabled": disabled,
    }


def build_macro_series(series_id: str, history: str = "3y") -> dict[str, Any] | None:
    _history_start(history)
    requested = series_id.strip()
    # Both the provider's id (DGS10) and the internal key (treasury_10y) resolve,
    # so a link keeps working after a series moves to a different provider.
    spec = FRED_SERIES_BY_ID.get(requested.upper()) or FRED_SERIES_BY_KEY.get(requested.lower())
    if spec is None:
        raise KeyError(series_id)
    record = _load_record(spec)
    lane = _lane_for(spec, record)
    if not data_rights.macro_lane_enabled(lane):
        raise MacroDataDisabled(lane)
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
