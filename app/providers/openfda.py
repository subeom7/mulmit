"""openFDA ``drug/drugsfda`` — recent original approvals (NDA/BLA/ANDA).

Rights posture (docs/DATA_SOURCE_REGISTER.md §3.23): openFDA content is public
domain under a Creative Commons CC0 1.0 Universal dedication; the Terms of
Service say "You can copy, modify, distribute, and perform the work, even for
commercial purposes, all without asking permission" and ask — not require — that
proper credit be given.  Every response carries a disclaimer ("Do not rely on
openFDA to make decisions regarding medical care … assume all results are
unvalidated") which the serving layer relays next to the values.  Limits: 240
requests/minute and 1,000/day per IP without a key, 120,000/day with a free key.
Mulmit makes a handful of calls per day from the ingest process.
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

PROVIDER_ID = "openfda"
PUBLISHER = "openFDA (U.S. Food and Drug Administration)"
ATTRIBUTION = "Source: openFDA (U.S. FDA) — public domain, CC0 1.0"
API_URL = "https://api.fda.gov/drug/drugsfda.json"
SITE_URL = "https://open.fda.gov/"
TERMS_URL = "https://open.fda.gov/terms/"
LICENSE_URL = "https://open.fda.gov/license/"
LICENSE_QUOTE = (
    "the content, data, documentation, code, and related materials on openFDA is public domain and "
    "made available with a Creative Commons CC0 1.0 Universal dedication (open.fda.gov/license, "
    "last updated 2014-05-27)"
)
DRUGSFDA_URL = "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={digits}"
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 2
DEFAULT_LIMIT = 100
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

Transport = Callable[[str, dict[str, str], float], Any]


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> Any:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _iso_date(value: Any) -> str | None:
    """openFDA dates are ``YYYYMMDD`` strings."""
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return None


def _first(values: Any) -> str | None:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    return values.strip() if isinstance(values, str) and values.strip() else None


def application_type(application_number: Any) -> str | None:
    if not isinstance(application_number, str):
        return None
    for prefix in ("ANDA", "NDA", "BLA"):
        if application_number.upper().startswith(prefix):
            return prefix
    return None


def parse_application(raw: Any, *, start: dt.date | None = None, end: dt.date | None = None) -> dict[str, Any] | None:
    """Flatten one Drugs@FDA application; keep only ORIG approvals inside the window (if given)."""
    if not isinstance(raw, dict):
        return None
    number = raw.get("application_number")
    if not isinstance(number, str) or not number:
        return None
    openfda = raw.get("openfda") if isinstance(raw.get("openfda"), dict) else {}
    products = [p for p in (raw.get("products") or []) if isinstance(p, dict)]
    approvals: list[dict[str, Any]] = []
    for sub in raw.get("submissions") or []:
        if not isinstance(sub, dict):
            continue
        if sub.get("submission_type") != "ORIG" or sub.get("submission_status") != "AP":
            continue
        date = _iso_date(sub.get("submission_status_date"))
        if date is None:
            continue
        if start is not None and dt.date.fromisoformat(date) < start:
            continue
        if end is not None and dt.date.fromisoformat(date) > end:
            continue
        approvals.append({
            "submission_number": sub.get("submission_number"),
            "approved_on": date,
            "review_priority": sub.get("review_priority"),
            "class_code": sub.get("submission_class_code"),
            "class_description": sub.get("submission_class_code_description"),
        })
    if not approvals:
        return None
    approvals.sort(key=lambda row: row["approved_on"], reverse=True)
    brand = _first(openfda.get("brand_name")) or _first([p.get("brand_name") for p in products])
    generic = _first(openfda.get("generic_name")) or _first(
        [ing.get("name") for p in products for ing in (p.get("active_ingredients") or []) if isinstance(ing, dict)]
    )
    digits = "".join(ch for ch in number if ch.isdigit())
    return {
        "application_number": number,
        "application_type": application_type(number),
        "sponsor_name": raw.get("sponsor_name"),
        "brand_name": brand,
        "generic_name": generic,
        "dosage_forms": sorted({str(p.get("dosage_form")) for p in products if p.get("dosage_form")})[:4],
        "routes": sorted({str(p.get("route")) for p in products if p.get("route")})[:4],
        "product_type": _first(openfda.get("product_type")),
        "approved_on": approvals[0]["approved_on"],
        "review_priority": approvals[0]["review_priority"],
        "class_description": approvals[0]["class_description"],
        "approvals": approvals,
        "url": DRUGSFDA_URL.format(digits=digits) if digits else SITE_URL,
    }


def parse_applications(raw: Any, *, start: dt.date | None = None, end: dt.date | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DataUnavailable("openFDA returned a non-object payload")
    error = raw.get("error")
    if isinstance(error, dict):
        if error.get("code") == "NOT_FOUND":
            return {"last_updated": None, "total": 0, "disclaimer": None, "applications": []}
        raise DataUnavailable(f"openFDA error {error.get('code')}: {error.get('message')}")
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    results_meta = meta.get("results") if isinstance(meta.get("results"), dict) else {}
    rows = [
        row for row in (parse_application(item, start=start, end=end) for item in raw.get("results") or []) if row
    ]
    rows.sort(key=lambda row: row["approved_on"], reverse=True)
    return {
        "last_updated": meta.get("last_updated"),
        "total": results_meta.get("total"),
        "disclaimer": meta.get("disclaimer"),
        "applications": rows,
    }


class OpenFdaProvider:
    """One or two GETs per refresh; the optional key never leaves the ingest process."""

    name = PROVIDER_ID

    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep

    def fetch_original_approvals(self, start: dt.date, end: dt.date, *, limit: int = DEFAULT_LIMIT, skip: int = 0) -> dict[str, Any]:
        """Applications with an ORIG approval dated inside [start, end]."""
        if end < start:
            raise ValueError("end must not precede start")
        search = (
            "submissions.submission_status:AP+AND+submissions.submission_type:ORIG+AND+"
            f"submissions.submission_status_date:[{start:%Y%m%d}+TO+{end:%Y%m%d}]"
        )
        params: list[tuple[str, str]] = []
        if self._api_key:
            params.append(("api_key", self._api_key))
        params += [("search", search), ("limit", str(max(1, min(1000, int(limit))))), ("skip", str(max(0, int(skip))))]
        # openFDA's search grammar needs literal '+' and ':' — only the key is percent-encoded.
        query = "&".join(f"{k}={urllib.parse.quote(v, safe='') if k == 'api_key' else v}" for k, v in params)
        raw = self._request(f"{API_URL}?{query}")
        parsed = parse_applications(raw, start=start, end=end)
        parsed["fetched_at"] = _utc_iso(self._wall_clock())
        parsed["window"] = {"start": start.isoformat(), "end": end.isoformat()}
        return parsed

    def _request(self, url: str) -> Any:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._transport(url, headers, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 404:
                    # openFDA answers "no matches" with 404 + {"error": {"code": "NOT_FOUND"}}.
                    try:
                        body = json.loads(exc.read().decode("utf-8"))
                    except Exception:  # noqa: BLE001 - a bare 404 is still "nothing found"
                        body = {"error": {"code": "NOT_FOUND", "message": "No matches found!"}}
                    return body
                if exc.code == 429:
                    if attempt >= self.retries:
                        raise RateLimited("openFDA rate limit reached") from exc
                elif exc.code in (401, 403):
                    raise DataUnavailable(f"openFDA rejected the request (HTTP {exc.code})") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(f"openFDA rejected the request with HTTP {exc.code}") from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("openFDA returned an unreadable response") from exc
            if attempt < self.retries:
                self._sleep(min(0.5 * (2**attempt), 2.0))
        raise DataUnavailable("openFDA is unavailable") from last_error
