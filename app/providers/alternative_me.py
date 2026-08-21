"""alternative.me Crypto Fear & Greed Index — read-only client, no key.

Why this source may be shown on a public, ad-supported page when most crypto
venues may not: the index page's own terms (accessed 2026-08-21,
https://alternative.me/crypto/fear-and-greed-index/) say

    "Commercial use is allowed as long as the attribution is given right next
    to the display of the data."

and "You must properly acknowledge the source of the data and prominently
reference it accordingly."  They also forbid using the data "to impersonate us
or to create a service that could be confused with our offering."  So every
response from this module carries an attribution block the UI must place next
to the value, and nothing here is renamed or rebranded as a Mulmit index.

The index updates once a day (00:00 UTC).  By the publisher's own description
it is bitcoin-centric — volatility 25%, market momentum/volume 25%, social
media 15%, surveys 15%, dominance 10%, trends 10% — and it is not comparable to
Mulmit's own sentiment gauge or to CNN's equity index.
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

ALTERNATIVE_ME_PROVIDER_ID = "alternative_me"
ALTERNATIVE_ME_PUBLISHER = "alternative.me"
ALTERNATIVE_ME_INDEX_NAME = "Crypto Fear & Greed Index"
ALTERNATIVE_ME_API_URL = "https://api.alternative.me/fng/"
ALTERNATIVE_ME_INDEX_URL = "https://alternative.me/crypto/fear-and-greed-index/"
# Shown verbatim next to every value. The terms ask for attribution "right next
# to the display of the data", so the text and link travel inside the payload
# rather than living only in a page footer.
ALTERNATIVE_ME_ATTRIBUTION = "Crypto Fear & Greed Index — alternative.me"
ALTERNATIVE_ME_TERMS_QUOTE = (
    "Commercial use is allowed as long as the attribution is given right next to "
    "the display of the data."
)
ALTERNATIVE_ME_TERMS_ACCESSED = "2026-08-21"

DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 2
DEFAULT_LIMIT = 400
MAX_LIMIT = 3000
USER_AGENT = "mulmit-market-monitor/1.0 (+https://mulmit.com)"

# Weights as the publisher states them on the index page (2026-08-21).
COMPONENTS: tuple[dict[str, Any], ...] = (
    {"id": "volatility", "weight_percent": 25, "label": {"ko": "변동성 (30·90일 대비)", "en": "Volatility (vs 30/90-day averages)"}},
    {"id": "market_momentum_volume", "weight_percent": 25, "label": {"ko": "모멘텀·거래량", "en": "Market momentum / volume"}},
    {"id": "social_media", "weight_percent": 15, "label": {"ko": "소셜 미디어", "en": "Social media"}},
    {"id": "surveys", "weight_percent": 15, "label": {"ko": "설문", "en": "Surveys"}},
    {"id": "dominance", "weight_percent": 10, "label": {"ko": "비트코인 도미넌스", "en": "Bitcoin dominance"}},
    {"id": "trends", "weight_percent": 10, "label": {"ko": "검색 트렌드", "en": "Search trends"}},
)

# The publisher's own labels; Korean renderings are ours, the English text is
# passed through unchanged so the index reads as what it is.
CLASSIFICATIONS: dict[str, dict[str, str]] = {
    "Extreme Fear": {"ko": "극단적 공포", "en": "Extreme Fear"},
    "Fear": {"ko": "공포", "en": "Fear"},
    "Neutral": {"ko": "중립", "en": "Neutral"},
    "Greed": {"ko": "탐욕", "en": "Greed"},
    "Extreme Greed": {"ko": "극단적 탐욕", "en": "Extreme Greed"},
}

Transport = Callable[[str, float], Any]


def classification_label(raw: str | None) -> dict[str, str]:
    text = str(raw or "").strip()
    return dict(CLASSIFICATIONS.get(text) or {"ko": text, "en": text})


def _utc_iso(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.UTC)
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _default_transport(url: str, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def parse_fear_greed(raw: Any, *, fetched_at: str) -> dict[str, Any]:
    """Normalise the publisher's payload; malformed rows are dropped, not repaired."""
    if not isinstance(raw, dict):
        raise DataUnavailable("alternative.me returned a non-object payload")
    metadata = raw.get("metadata")
    if isinstance(metadata, dict) and metadata.get("error"):
        raise DataUnavailable(f"alternative.me reported an error: {metadata.get('error')}")
    data = raw.get("data")
    if not isinstance(data, list) or not data:
        raise DataUnavailable("alternative.me returned no index data")

    by_timestamp: dict[int, dict[str, Any]] = {}
    next_update: int | None = None
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        try:
            value = int(str(item.get("value")).strip())
            timestamp = int(str(item.get("timestamp")).strip())
        except (TypeError, ValueError):
            continue
        if not 0 <= value <= 100:
            continue
        classification = str(item.get("value_classification") or "").strip()
        date = dt.datetime.fromtimestamp(timestamp, tz=dt.UTC).date().isoformat()
        by_timestamp[timestamp] = {
            "date": date,
            "timestamp": timestamp,
            "value": value,
            "classification": classification,
        }
        if index == 0:
            try:
                next_update = int(str(item.get("time_until_update")).strip())
            except (TypeError, ValueError):
                next_update = None
    if not by_timestamp:
        raise DataUnavailable("alternative.me returned no readable index rows")

    observations = [by_timestamp[key] for key in sorted(by_timestamp)]
    # One row per UTC date, the later timestamp winning.
    by_date: dict[str, dict[str, Any]] = {}
    for row in observations:
        by_date[row["date"]] = row
    return {
        "fetched_at": fetched_at,
        "index_name": str(raw.get("name") or ALTERNATIVE_ME_INDEX_NAME),
        "observations": [by_date[key] for key in sorted(by_date)],
        "next_update_in_seconds": next_update,
    }


class AlternativeMeProvider:
    """Fetch the daily index with bounded retries. Network only in the ingest lane."""

    name = ALTERNATIVE_ME_PROVIDER_ID

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        transport: Transport | None = None,
        wall_clock: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = max(0.1, float(timeout))
        self.retries = max(0, int(retries))
        self._transport = transport or _default_transport
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(dt.UTC))
        self._sleep = sleep

    def fetch_fear_greed(self, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
        bounded = max(1, min(int(limit), MAX_LIMIT))
        query = urllib.parse.urlencode({"limit": bounded, "format": "json"})
        raw = self._request(f"{ALTERNATIVE_ME_API_URL}?{query}")
        return parse_fear_greed(raw, fetched_at=_utc_iso(self._wall_clock()))

    def _request(self, url: str) -> Any:
        last_error: BaseException | None = None
        for attempt in range(self.retries + 1):
            try:
                return self._transport(url, self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 429:
                    if attempt >= self.retries:
                        raise RateLimited("alternative.me rate limit reached") from exc
                elif not 500 <= exc.code < 600:
                    raise DataUnavailable(
                        f"alternative.me rejected the request with HTTP {exc.code}"
                    ) from exc
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                last_error = exc
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError) as exc:
                raise DataUnavailable("alternative.me returned an unreadable response") from exc
            if attempt < self.retries:
                self._sleep(min(0.5 * (2**attempt), 2.0))
        raise DataUnavailable("alternative.me index data is unavailable") from last_error
