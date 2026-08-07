"""When a repeating bill next falls due.

Getting this wrong is quiet and expensive. A monthly bill that slips a day each
month has drifted a fortnight by the end of the year, and nobody notices until
a customer asks why their rent invoice arrived on the 14th.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.schedules import (
    DAILY, HALF_YEARLY, MONTHLY, QUARTERLY, WEEKLY, YEARLY, ScheduleError, advance,
    catch_up, describe, occurrences_between,
)


# ── moving forward ─────────────────────────────────────────────────
def test_daily_moves_a_day():
    assert advance(date(2026, 8, 7), DAILY) == date(2026, 8, 8)


def test_weekly_moves_a_week():
    assert advance(date(2026, 8, 7), WEEKLY) == date(2026, 8, 14)


def test_a_fortnight_is_two_weeks():
    assert advance(date(2026, 8, 7), WEEKLY, 2) == date(2026, 8, 21)


def test_monthly_keeps_the_same_day():
    assert advance(date(2026, 8, 15), MONTHLY) == date(2026, 9, 15)


def test_quarterly_moves_three_months():
    assert advance(date(2026, 1, 10), QUARTERLY) == date(2026, 4, 10)


def test_half_yearly_moves_six():
    assert advance(date(2026, 1, 10), HALF_YEARLY) == date(2026, 7, 10)


def test_yearly_moves_twelve():
    assert advance(date(2026, 2, 28), YEARLY) == date(2027, 2, 28)


def test_an_unknown_frequency_is_refused():
    with pytest.raises(ScheduleError, match="not a schedule"):
        advance(date(2026, 8, 7), "fortnightly")


def test_an_interval_of_zero_is_refused():
    with pytest.raises(ScheduleError, match="at least one"):
        advance(date(2026, 8, 7), MONTHLY, 0)


# ── the month-end trap ─────────────────────────────────────────────
def test_the_31st_lands_on_the_last_day_of_a_short_month():
    assert advance(date(2026, 1, 31), MONTHLY) == date(2026, 2, 28)
    assert advance(date(2026, 3, 31), MONTHLY) == date(2026, 4, 30)


def test_february_is_the_exception_not_the_new_rule():
    """Without an anchor a bill on the 31st becomes the 28th in February and
    stays on the 28th for the rest of the year — the schedule walks backwards
    and never recovers."""
    assert advance(date(2026, 2, 28), MONTHLY, anchor_day=31) == date(2026, 3, 31)
    assert advance(date(2026, 4, 30), MONTHLY, anchor_day=31) == date(2026, 5, 31)


def test_a_whole_year_from_the_31st_stays_on_month_ends():
    when = date(2026, 1, 31)
    seen = [when]
    for _ in range(11):
        when = advance(when, MONTHLY, anchor_day=31)
        seen.append(when)

    assert seen[1] == date(2026, 2, 28)
    assert seen[2] == date(2026, 3, 31), "March has 31 days and the bill goes back to it"
    assert seen[-1] == date(2026, 12, 31)


def test_a_leap_february_is_handled():
    assert advance(date(2028, 1, 31), MONTHLY) == date(2028, 2, 29)


def test_the_29th_of_february_falls_back_the_following_year():
    assert advance(date(2028, 2, 29), YEARLY) == date(2029, 2, 28)


# ── listing occurrences ────────────────────────────────────────────
def test_a_month_of_weekly_bills():
    dates = occurrences_between(date(2026, 8, 1), date(2026, 8, 31), WEEKLY)
    assert dates == [
        date(2026, 8, 1), date(2026, 8, 8), date(2026, 8, 15),
        date(2026, 8, 22), date(2026, 8, 29),
    ]


def test_both_ends_are_included():
    dates = occurrences_between(date(2026, 8, 1), date(2026, 8, 1), DAILY)
    assert dates == [date(2026, 8, 1)]


def test_a_window_that_ends_before_it_starts_has_nothing_in_it():
    assert occurrences_between(date(2026, 8, 10), date(2026, 8, 1), DAILY) == []


def test_a_long_run_is_capped_rather_than_unbounded():
    dates = occurrences_between(date(2020, 1, 1), date(2030, 1, 1), DAILY, limit=50)
    assert len(dates) == 50


# ── catching up ────────────────────────────────────────────────────
def test_nothing_is_due_before_the_first_run():
    assert catch_up(date(2026, 9, 1), date(2026, 8, 7), MONTHLY) == []


def test_one_run_due_today():
    assert catch_up(date(2026, 8, 7), date(2026, 8, 7), MONTHLY) == [date(2026, 8, 7)]


def test_six_weeks_away_owes_six_weekly_bills_not_one():
    """Raising only the most recent would silently lose five months of rent
    over a year of light use."""
    due = catch_up(date(2026, 7, 1), date(2026, 8, 7), WEEKLY)
    assert len(due) == 6
    assert due[0] == date(2026, 7, 1)
    assert due[-1] == date(2026, 8, 5)


def test_the_missed_runs_come_back_oldest_first():
    due = catch_up(date(2026, 5, 1), date(2026, 8, 7), MONTHLY)
    assert due == [date(2026, 5, 1), date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]


def test_a_dormant_schedule_is_capped_rather_than_flooding_the_books():
    """Hundreds of bills at once is a mistake to be told about, not acted on."""
    due = catch_up(date(2010, 1, 1), date(2026, 8, 7), DAILY, limit=60)
    assert len(due) == 60


def test_catching_up_keeps_the_anchor_day():
    due = catch_up(date(2026, 1, 31), date(2026, 5, 15), MONTHLY, anchor_day=31)
    assert due == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
    ]


# ── describing one ─────────────────────────────────────────────────
@pytest.mark.parametrize(
    "frequency,interval,expected",
    [
        (MONTHLY, 1, "Every month"),
        (WEEKLY, 1, "Every week"),
        (DAILY, 1, "Every day"),
        (QUARTERLY, 1, "Every 3 months"),
        (YEARLY, 1, "Every year"),
        (WEEKLY, 2, "Every 2 weeks"),
        (MONTHLY, 6, "Every 6 months"),
    ],
)
def test_a_schedule_reads_the_way_a_shopkeeper_would_say_it(frequency, interval, expected):
    assert describe(frequency, interval) == expected
