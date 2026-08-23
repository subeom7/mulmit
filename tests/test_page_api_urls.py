"""Every API URL a hub page fetches must be a route this app actually serves.

`/stock/AAPL` asked for `/api/us/insider/{ticker}`, which has never existed —
the route is `/api/insider/{ticker}`. The 404 was swallowed by a bare `catch`,
so the insider section simply never appeared and the page looked like a data
gap. Nothing failed loudly, and nothing checked.

The hub pages are self-contained: they do not go through monitor.js, so the
fetch-wiring test does not cover them. This does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.main import app

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
# The pages that build their own requests rather than going through monitor.js.
SELF_CONTAINED = ("stock.html", "crypto-coin.html")


def _served_paths() -> list[str]:
    return [route.path for route in app.routes if getattr(route, "path", "").startswith("/api/")]


def _requested(page: str) -> list[str]:
    text = (STATIC / page).read_text(encoding="utf-8")
    # Quoted strings and template literals both appear in these pages. A
    # template literal is truncated at its first interpolation, which leaves
    # exactly the literal prefix a parameterised route is matched on.
    found: set[str] = set()
    for quote in ('"', "'", "`"):
        for match in re.findall(rf"{quote}(/api/[^{quote}]*){quote}", text):
            found.add(match.split("${", 1)[0])
    return sorted(found)


def _matches(url: str, served: list[str]) -> bool:
    path = url.split("?", 1)[0]
    if path in served:
        return True
    # A literal ending in "/" is the prefix of a parameterised route, e.g.
    # "/api/insider/" + SYMBOL against "/api/insider/{ticker}".
    if path.endswith("/"):
        return any(
            route.startswith(path) and route[len(path) :].startswith("{") for route in served
        )
    return False


@pytest.mark.parametrize("page", SELF_CONTAINED)
def test_every_api_url_a_page_fetches_is_a_real_route(page: str):
    served = _served_paths()
    requested = _requested(page)
    assert requested, f"{page} fetches no /api/ URL — has the page changed shape?"
    missing = [url for url in requested if not _matches(url, served)]
    assert not missing, (
        f"{page} requests routes this app does not serve: {missing}. "
        "A 404 here shows up as an empty section, not as an error."
    )


def test_the_matcher_would_actually_catch_the_bug_that_shipped():
    """A guard that cannot fail is not a guard."""
    served = _served_paths()
    assert _matches("/api/insider/", served)          # the real route
    assert not _matches("/api/us/insider/", served)   # what the page asked for
    assert _matches("/api/us/ptr?ticker=AAPL", served)
    assert not _matches("/api/us/nothing-here", served)


def test_the_stock_hub_asks_for_the_ticker_rather_than_filtering_a_global_feed():
    """Filtering a global window client-side left most tickers with nothing to show."""
    text = (STATIC / "stock.html").read_text(encoding="utf-8")
    for endpoint in ("/api/us/events", "/api/us/ptr"):
        assert f'"{endpoint}?ticker="' in text, (
            f"{endpoint} is fetched without a ticker; the global window rarely "
            "contains the symbol being viewed"
        )


def test_page_sections_report_a_failure_instead_of_swallowing_it():
    """Three broken sections survived because every catch was empty."""
    text = (STATIC / "stock.html").read_text(encoding="utf-8")
    assert "catch (e) {}" not in text, "a bare catch hides a broken section as an empty one"
