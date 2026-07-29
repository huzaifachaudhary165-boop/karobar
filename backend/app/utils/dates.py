"""Date-range helpers used across reports, dashboards and the AI tools."""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone

from dateutil.relativedelta import relativedelta

Period = str  # today|yesterday|this_week|this_month|last_month|this_quarter|this_year|fy|last_7_days|last_30_days|all


def today() -> date:
    return datetime.now(timezone.utc).date()


def start_of_day(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def end_of_day(d: date) -> datetime:
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


def month_bounds(d: date) -> tuple[date, date]:
    return d.replace(day=1), d.replace(day=calendar.monthrange(d.year, d.month)[1])


def quarter_bounds(d: date) -> tuple[date, date]:
    q_start_month = 3 * ((d.month - 1) // 3) + 1
    start = date(d.year, q_start_month, 1)
    end = start + relativedelta(months=3, days=-1)
    return start, end


def financial_year_bounds(d: date, start_month: int = 7) -> tuple[date, date]:
    """FY runs start_month → start_month-1. Pakistan defaults to July–June, India April–March."""
    year = d.year if d.month >= start_month else d.year - 1
    start = date(year, start_month, 1)
    return start, start + relativedelta(years=1, days=-1)


def resolve_period(period: Period, *, fy_start_month: int = 7, ref: date | None = None) -> tuple[date, date]:
    """Turn a human period name into (start, end). Unknown names fall back to this month."""
    d = ref or today()
    match period:
        case "today":
            return d, d
        case "yesterday":
            y = d - timedelta(days=1)
            return y, y
        case "this_week":
            start = d - timedelta(days=d.weekday())
            return start, start + timedelta(days=6)
        case "last_week":
            start = d - timedelta(days=d.weekday() + 7)
            return start, start + timedelta(days=6)
        case "this_month":
            return month_bounds(d)
        case "last_month":
            return month_bounds(d - relativedelta(months=1))
        case "this_quarter":
            return quarter_bounds(d)
        case "last_quarter":
            return quarter_bounds(d - relativedelta(months=3))
        case "this_year":
            return date(d.year, 1, 1), date(d.year, 12, 31)
        case "last_year":
            return date(d.year - 1, 1, 1), date(d.year - 1, 12, 31)
        case "fy" | "financial_year":
            return financial_year_bounds(d, fy_start_month)
        case "last_fy":
            return financial_year_bounds(d - relativedelta(years=1), fy_start_month)
        case "last_7_days":
            return d - timedelta(days=6), d
        case "last_30_days":
            return d - timedelta(days=29), d
        case "last_90_days":
            return d - timedelta(days=89), d
        case "all":
            return date(2000, 1, 1), d
        case _:
            return month_bounds(d)


def previous_period(start: date, end: date) -> tuple[date, date]:
    """The equally-long window immediately before [start, end] — for % change."""
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=span - 1), prev_end


def bucket_label(d: date, granularity: str) -> str:
    match granularity:
        case "day":
            return d.isoformat()
        case "week":
            return f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
        case "month":
            return d.strftime("%Y-%m")
        case "quarter":
            return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
        case _:
            return str(d.year)


def auto_granularity(start: date, end: date) -> str:
    days = (end - start).days
    if days <= 31:
        return "day"
    if days <= 120:
        return "week"
    if days <= 800:
        return "month"
    return "quarter"


def iter_buckets(start: date, end: date, granularity: str) -> list[tuple[str, date, date]]:
    """Dense bucket list so charts show zero-days instead of skipping them."""
    out: list[tuple[str, date, date]] = []
    cur = start
    while cur <= end:
        match granularity:
            case "day":
                b_start, b_end = cur, cur
                nxt = cur + timedelta(days=1)
            case "week":
                b_start = cur - timedelta(days=cur.weekday())
                b_end = b_start + timedelta(days=6)
                nxt = b_end + timedelta(days=1)
            case "month":
                b_start, b_end = month_bounds(cur)
                nxt = b_end + timedelta(days=1)
            case "quarter":
                b_start, b_end = quarter_bounds(cur)
                nxt = b_end + timedelta(days=1)
            case _:
                b_start, b_end = date(cur.year, 1, 1), date(cur.year, 12, 31)
                nxt = b_end + timedelta(days=1)
        out.append((bucket_label(b_start, granularity), max(b_start, start), min(b_end, end)))
        cur = nxt
    return out


def parse_date(value: str | date | datetime | None, default: date | None = None) -> date | None:
    if value is None:
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        from dateutil import parser  # noqa: PLC0415

        return parser.parse(text, dayfirst=True).date()
    except Exception:
        return default


def humanise_date(d: date) -> str:
    delta = (today() - d).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta == -1:
        return "Tomorrow"
    if 0 < delta < 7:
        return f"{delta} days ago"
    return d.strftime("%d %b %Y")
