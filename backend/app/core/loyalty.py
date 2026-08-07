"""Loyalty arithmetic.

Kept apart so the rules can be checked on their own. Points are money to the
customer holding them — a shop that miscounts them will be argued with at the
counter, and the customer will be right.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from app.core.money import ZERO, D, money

HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Lot:
    """A batch of points earned at one moment, and when it goes stale."""

    id: str
    remaining: int
    expires_on: date | None


def points_for(amount: Decimal, earn_rate: Decimal, minimum: Decimal | None = None) -> int:
    """How many points a bill of this size earns.

    Rounded *down*. A shop that rounds up gives away a point on every bill,
    which across a year of trading is a real number, and no customer has ever
    complained about not being given a point they did not earn.
    """
    total = D(amount)
    if total <= 0 or earn_rate <= 0:
        return 0
    if minimum is not None and total < minimum:
        return 0
    return int((total * D(earn_rate)).to_integral_value(rounding=ROUND_DOWN))


def value_of(points: int, point_value: Decimal) -> Decimal:
    """What a number of points takes off a bill."""
    if points <= 0:
        return ZERO
    return money(D(points) * D(point_value))


def max_redeemable(
    balance: int,
    bill_total: Decimal,
    point_value: Decimal,
    *,
    max_percent: Decimal = HUNDRED,
    minimum_points: int = 0,
) -> int:
    """The most points that may be spent on this bill.

    Three separate limits, and the smallest wins: what the customer has, what
    the bill is worth, and what the shop allows one bill to be paid with. The
    last exists because a scheme with no cap lets a regular customer take a
    whole bill for nothing, which is not what anyone meant by 1%.
    """
    if balance <= 0 or bill_total <= 0 or point_value <= 0:
        return 0
    if balance < minimum_points:
        return 0

    cap_amount = money(D(bill_total) * D(max_percent) / HUNDRED)
    by_bill = int((cap_amount / D(point_value)).to_integral_value(rounding=ROUND_DOWN))

    allowed = min(balance, by_bill)
    return allowed if allowed >= minimum_points else 0


def expiry_for(earned_on: date, months: int | None) -> date | None:
    """When points earned today go stale."""
    if not months:
        return None
    total = earned_on.month - 1 + months
    year = earned_on.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(earned_on.day, _days_in_month(year, month)))


def allocate(lots: list[Lot], wanted: int, on: date | None = None) -> list[tuple[str, int]]:
    """Which lots to spend points from, and how many of each.

    Oldest expiry first, so a customer spends the points that were about to
    lapse rather than the ones with a year left. Spending the newest would let
    points quietly expire while the customer was actively using the scheme,
    which is the exact thing that makes people stop trusting a loyalty card.

    Already-expired lots are never spent from.
    """
    if wanted <= 0:
        return []

    today = on or date.today()
    live = [lot for lot in lots if lot.remaining > 0 and not _is_stale(lot, today)]
    # Lots that never expire go last: they can always be spent later.
    live.sort(key=lambda lot: (lot.expires_on is None, lot.expires_on or today))

    taken: list[tuple[str, int]] = []
    left = wanted
    for lot in live:
        if left <= 0:
            break
        take = min(lot.remaining, left)
        taken.append((lot.id, take))
        left -= take

    if left > 0:
        raise ValueError(f"Only {wanted - left} points are available, not {wanted}.")
    return taken


def stale_lots(lots: list[Lot], on: date | None = None) -> list[Lot]:
    """Lots whose date has passed and that still hold points."""
    today = on or date.today()
    return [lot for lot in lots if lot.remaining > 0 and _is_stale(lot, today)]


def usable_balance(lots: list[Lot], on: date | None = None) -> int:
    """Points a customer can actually spend today."""
    today = on or date.today()
    return sum(lot.remaining for lot in lots if lot.remaining > 0 and not _is_stale(lot, today))


def scheme_cost_percent(earn_rate: Decimal, point_value: Decimal) -> Decimal:
    """What the scheme costs as a percentage of turnover.

    A shopkeeper setting one up should see this before they save it: one point
    per rupee, each worth a rupee, is giving away everything.
    """
    return D(earn_rate * point_value * HUNDRED).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _is_stale(lot: Lot, on: date) -> bool:
    return lot.expires_on is not None and lot.expires_on < on


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31
