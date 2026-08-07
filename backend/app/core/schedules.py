"""Working out when a repeating thing next falls due.

Kept apart so the date arithmetic can be checked on its own. Getting this wrong
is quiet and expensive: a monthly bill that slips a day each month has drifted
a fortnight by the end of the year, and nobody notices until a customer asks
why their rent invoice arrived on the 14th.
"""

from __future__ import annotations

from datetime import date, timedelta

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
QUARTERLY = "quarterly"
HALF_YEARLY = "half_yearly"
YEARLY = "yearly"

FREQUENCIES = (DAILY, WEEKLY, MONTHLY, QUARTERLY, HALF_YEARLY, YEARLY)

# How many months each frequency advances by, for the ones that move in months.
_MONTHS = {MONTHLY: 1, QUARTERLY: 3, HALF_YEARLY: 6, YEARLY: 12}


class ScheduleError(ValueError):
    """The schedule cannot be worked out."""


def advance(current: date, frequency: str, interval: int = 1, anchor_day: int | None = None) -> date:
    """The next occurrence after `current`.

    `anchor_day` is the day of the month the schedule was set up on. Without it
    a bill starting on the 31st becomes the 28th in February and then stays on
    the 28th for the rest of the year — the schedule quietly walks backwards
    and never recovers. Anchoring means February is the exception, not the new
    rule.
    """
    if interval < 1:
        raise ScheduleError("An interval has to be at least one.")

    if frequency == DAILY:
        return current + timedelta(days=interval)
    if frequency == WEEKLY:
        return current + timedelta(weeks=interval)

    months = _MONTHS.get(frequency)
    if months is None:
        raise ScheduleError(f"'{frequency}' is not a schedule this app keeps.")

    return add_months(current, months * interval, anchor_day=anchor_day)


def add_months(start: date, months: int, anchor_day: int | None = None) -> date:
    """Same day, N months on, clamped to the length of the target month."""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    wanted = anchor_day or start.day
    return date(year, month, min(wanted, days_in_month(year, month)))


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def occurrences_between(
    start: date, end: date, frequency: str, interval: int = 1, limit: int = 500
) -> list[date]:
    """Every date the schedule falls on in a window, inclusive of both ends.

    Capped rather than unbounded: a daily schedule over ten years is 3,650
    dates, and nothing that asks this question wants that many.
    """
    if end < start:
        return []

    anchor = start.day
    out: list[date] = []
    when = start
    while when <= end and len(out) < limit:
        out.append(when)
        when = advance(when, frequency, interval, anchor_day=anchor)
    return out


def catch_up(next_run: date, today: date, frequency: str, interval: int = 1,
             anchor_day: int | None = None, limit: int = 60) -> list[date]:
    """Every run that is due but has not happened, oldest first.

    A shop that did not open the app for six weeks has six weekly bills owing,
    not one. Raising only the most recent would silently lose five months of
    rent over a year of light use.

    Capped so a schedule left dormant for years cannot produce hundreds of
    bills in one go — that is a mistake to be told about, not to act on.
    """
    out: list[date] = []
    when = next_run
    while when <= today and len(out) < limit:
        out.append(when)
        when = advance(when, frequency, interval, anchor_day=anchor_day)
    return out


def describe(frequency: str, interval: int = 1) -> str:
    """'Every month', 'Every 2 weeks' — what a shopkeeper would say."""
    if interval == 1:
        return {
            DAILY: "Every day",
            WEEKLY: "Every week",
            MONTHLY: "Every month",
            QUARTERLY: "Every 3 months",
            HALF_YEARLY: "Every 6 months",
            YEARLY: "Every year",
        }.get(frequency, frequency)

    unit = {
        DAILY: "days",
        WEEKLY: "weeks",
        MONTHLY: "months",
        QUARTERLY: "quarters",
        HALF_YEARLY: "half-years",
        YEARLY: "years",
    }.get(frequency, frequency)
    return f"Every {interval} {unit}"
