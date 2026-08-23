"""Paging against data.go.kr — the pages after the first go out together.

A round trip to this API measures seconds, so walking pages one after another
put the whole count on the caller's clock: `/api/kr/stock/{code}` answered a
cold read in 5.8s in production, which is two pages of five years of daily
closes. The page count is known from the first response, so the rest are
fetched at once.

Two things have to survive that change: the walk must still reach `totalCount`
when the server returns short pages, and an inflated `totalCount` must not turn
into a burst of calls against a quota-limited free API.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time

import pytest

from app.providers.fsc import FSC_SERIES_BY_KEY, PARALLEL_PAGES, FscProvider

RAW_KEY = "ab+cd/ef=="


def _row(date: str, close: str) -> dict:
    return {"basDt": date, "idxNm": "코스피", "idxCsf": "KOSPI시리즈", "clpr": close}


def _envelope(rows: list[dict], total: int) -> bytes:
    return json.dumps({
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {"numOfRows": 1000, "pageNo": 1, "totalCount": total, "items": {"item": rows}},
        }
    }).encode("utf-8")


class PageServer:
    """Answers by page number, not by call order, and records concurrency.

    Order-based fakes cannot describe a parallel fetch: the calls arrive
    interleaved. This one keys off ``pageNo`` and tracks how many requests were
    in flight at once, which is the property under test.
    """

    def __init__(self, pages: dict[int, bytes], *, delay: float = 0.0) -> None:
        self.pages = pages
        self.delay = delay
        self.requested: list[int] = []
        self.max_in_flight = 0
        self._in_flight = 0
        self._lock = threading.Lock()

    def __call__(self, request, timeout):  # noqa: ANN001 - urllib Request
        page = int(re.search(r"pageNo=(\d+)", request.full_url).group(1))
        with self._lock:
            self.requested.append(page)
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        if self.delay:
            time.sleep(self.delay)
        with self._lock:
            self._in_flight -= 1
        return self.pages.get(page, _envelope([], 0))


def _provider(http) -> FscProvider:
    return FscProvider(RAW_KEY, http_get=http, retries=0, request_interval=0.0, sleep=lambda _s: None)


def _fetch(http):
    return _provider(http).fetch_series(
        FSC_SERIES_BY_KEY["kospi_exact"], start=dt.date(2020, 1, 1)
    )


def test_pages_after_the_first_are_fetched_at_once():
    pages = {
        1: _envelope([_row("20260810", "6800.00")], total=4),
        2: _envelope([_row("20260811", "6810.00")], total=4),
        3: _envelope([_row("20260812", "6820.00")], total=4),
        4: _envelope([_row("20260813", "6830.00")], total=4),
    }
    http = PageServer(pages, delay=0.15)

    started = time.perf_counter()
    _metadata, observations = _fetch(http)
    elapsed = time.perf_counter() - started

    assert [value for _date, value in observations] == [6800.0, 6810.0, 6820.0, 6830.0]
    assert sorted(http.requested) == [1, 2, 3, 4]
    # One round trip for page 1, then one more for the other three together.
    assert http.max_in_flight >= 3, "pages 2-4 did not overlap"
    assert elapsed < 0.45, f"looks sequential: {elapsed:.2f}s"


def test_short_pages_are_still_walked_to_the_total():
    """The estimate divides by what page one returned; smaller pages undershoot it."""
    pages = {
        1: _envelope([_row("20260810", "1.0"), _row("20260811", "2.0")], total=5),
        2: _envelope([_row("20260812", "3.0")], total=5),
        3: _envelope([_row("20260813", "4.0")], total=5),
        4: _envelope([_row("20260814", "5.0")], total=5),
    }
    http = PageServer(pages)

    _metadata, observations = _fetch(http)

    assert len(observations) == 5
    assert 4 in http.requested, "the walk stopped before reaching totalCount"


def test_an_inflated_total_count_does_not_burn_the_daily_quota():
    """totalCount is trusted for the estimate, so it must not be trusted far."""
    http = PageServer({1: _envelope([_row("20260810", "1.0")], total=10_000)})

    _metadata, observations = _fetch(http)

    assert [value for _date, value in observations] == [1.0]
    # The first page, one capped parallel batch, and the empty page that stops
    # the walk — never the 40-page maximum.
    assert len(http.requested) <= PARALLEL_PAGES + 1
    assert max(http.requested) <= PARALLEL_PAGES + 1


def test_a_single_page_answer_makes_exactly_one_request():
    http = PageServer({1: _envelope([_row("20260810", "6800.00")], total=1)})

    _metadata, observations = _fetch(http)

    assert len(observations) == 1
    assert http.requested == [1]
    assert http.max_in_flight == 1


def test_every_row_survives_the_parallel_path():
    """Order of arrival must not drop or duplicate anything."""
    pages = {
        page: _envelope([_row(f"2026081{page}", f"{6800 + page}.00")], total=6)
        for page in range(1, 7)
    }
    http = PageServer(pages, delay=0.02)

    _metadata, observations = _fetch(http)

    assert [value for _date, value in observations] == pytest.approx(
        [6801.0, 6802.0, 6803.0, 6804.0, 6805.0, 6806.0]
    )
    assert len({date for date, _value in observations}) == 6
