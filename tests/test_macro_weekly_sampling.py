"""Weekly sampling for the snapshot — real values only, and the tail is exact.

The snapshot ships one point per week so the card sparklines stop costing
863KB uncompressed. Two properties make that safe: every point is a value the
source actually published (never an average), and the most recent observation
always survives, so the chart ends where the card's latest value says it does.
"""

from __future__ import annotations

import datetime as dt

from app.macro_dashboard import _weekly_observations

MONDAY = dt.date(2026, 8, 17)   # ISO week 34 of 2026


def _daily(start: dt.date, days: int, first: float = 1.0) -> list[tuple[dt.date, float]]:
    return [(start + dt.timedelta(days=i), first + i) for i in range(days)]


def test_each_week_keeps_the_last_value_actually_published():
    sampled = _weekly_observations(_daily(MONDAY, 14))
    assert sampled == [
        (MONDAY + dt.timedelta(days=6), 7.0),     # Sunday closes week 34
        (MONDAY + dt.timedelta(days=13), 14.0),   # and week 35
    ]
    # Every value survives from the input; none is computed.
    original = dict(_daily(MONDAY, 14))
    assert all(original[date] == value for date, value in sampled)


def test_the_most_recent_observation_always_survives():
    """The current week is partial, so its last point is the newest one."""
    for days in range(1, 30):
        series = _daily(MONDAY, days)
        assert _weekly_observations(series)[-1] == series[-1], days


def test_sampling_is_idempotent_for_anything_weekly_or_sparser():
    monthly = [(dt.date(2024, month, 1), float(month)) for month in range(1, 13)]
    assert _weekly_observations(monthly) == monthly

    weekly = [(MONDAY + dt.timedelta(weeks=i), float(i)) for i in range(20)]
    assert _weekly_observations(weekly) == weekly

    # Applying it twice changes nothing either.
    once = _weekly_observations(_daily(MONDAY, 40))
    assert _weekly_observations(once) == once


def test_it_collapses_a_dense_series_to_about_one_point_a_week():
    three_years = _daily(dt.date(2023, 8, 21), 366 * 3)
    sampled = _weekly_observations(three_years)
    assert 150 <= len(sampled) <= 160, len(sampled)
    assert len(sampled) < len(three_years) / 6


def test_an_empty_series_stays_empty():
    assert _weekly_observations([]) == []


def test_a_week_spanning_the_year_boundary_is_one_group():
    """ISO weeks, not calendar years — 2024-12-30 and 2025-01-01 share week 1."""
    series = [
        (dt.date(2024, 12, 30), 1.0),
        (dt.date(2025, 1, 1), 2.0),
        (dt.date(2025, 1, 6), 3.0),
    ]
    assert _weekly_observations(series) == [(dt.date(2025, 1, 1), 2.0), (dt.date(2025, 1, 6), 3.0)]
