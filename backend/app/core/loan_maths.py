"""Instalment arithmetic for loans.

Kept apart from the service so the numbers can be checked on their own. A
shopkeeper comparing this against the bank's own schedule will notice a rupee,
and being wrong here costs trust in everything else the app says about money.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.money import HUNDRED, ZERO, D, money
from app.models.enums import InterestType

MONTHS_PER_YEAR = Decimal("12")


@dataclass(frozen=True)
class Instalment:
    number: int
    due_date: date
    amount: Decimal
    principal: Decimal
    interest: Decimal
    balance_after: Decimal


def monthly_rate(annual_percent: Decimal | float | str) -> Decimal:
    """A yearly percentage as a monthly fraction: 18% a year → 0.015 a month."""
    return D(annual_percent) / HUNDRED / MONTHS_PER_YEAR


def emi(
    principal: Decimal,
    annual_rate: Decimal,
    tenure_months: int,
    interest_type: str = InterestType.REDUCING,
) -> Decimal:
    """The equal monthly instalment for a loan.

    Reducing balance uses the standard annuity formula — interest is charged on
    what is still owed, so a rupee repaid early is a rupee that stops costing.
    Flat charges the full rate on the original amount for the whole term, which
    is why a "12% flat" loan is nearer 21% in real terms; the app should be able
    to show both honestly rather than pretending they are the same offer.
    """
    p = D(principal)
    n = int(tenure_months)
    if p <= 0 or n <= 0:
        return ZERO

    if interest_type == InterestType.NONE or D(annual_rate) <= 0:
        return money(p / n)

    if interest_type == InterestType.FLAT:
        years = D(n) / MONTHS_PER_YEAR
        total_interest = p * D(annual_rate) / HUNDRED * years
        return money((p + total_interest) / n)

    r = monthly_rate(annual_rate)
    # (1 + r)^n, by repeated multiplication so this never touches a float.
    growth = (Decimal("1") + r) ** n
    return money(p * r * growth / (growth - Decimal("1")))


def schedule(
    principal: Decimal,
    annual_rate: Decimal,
    tenure_months: int,
    start: date,
    interest_type: str = InterestType.REDUCING,
    instalment: Decimal | None = None,
) -> list[Instalment]:
    """The full repayment plan, month by month.

    The last instalment absorbs whatever rounding has accumulated over the term
    so the balance lands exactly on zero. Every real lender does the same; a
    schedule that ends owing four paise is a schedule nobody trusts.
    """
    p = D(principal)
    n = int(tenure_months)
    if p <= 0 or n <= 0:
        return []

    payment = money(instalment) if instalment else emi(p, annual_rate, n, interest_type)
    if payment <= 0:
        return []

    rows: list[Instalment] = []
    balance = money(p)

    if interest_type == InterestType.FLAT:
        # Flat interest is fixed at the outset, so every month carries the same
        # share of it regardless of how much is left owing.
        years = D(n) / MONTHS_PER_YEAR
        total_interest = money(p * D(annual_rate) / HUNDRED * years)
        per_month_interest = money(total_interest / n)
    else:
        per_month_interest = None

    r = monthly_rate(annual_rate) if interest_type == InterestType.REDUCING else ZERO

    for i in range(1, n + 1):
        last = i == n

        if per_month_interest is not None:
            interest = per_month_interest
        elif interest_type == InterestType.NONE:
            interest = ZERO
        else:
            interest = money(balance * r)

        principal_part = money(payment - interest)
        if last or principal_part > balance:
            principal_part = balance
            payment_now = money(principal_part + interest)
        else:
            payment_now = payment

        balance = money(balance - principal_part)
        rows.append(
            Instalment(
                number=i,
                due_date=add_months(start, i),
                amount=payment_now,
                principal=principal_part,
                interest=interest,
                balance_after=balance,
            )
        )
        if balance <= 0 and not last:
            break

    return rows


def split_payment(
    outstanding: Decimal,
    amount: Decimal,
    annual_rate: Decimal,
    interest_type: str = InterestType.REDUCING,
    flat_monthly_interest: Decimal | None = None,
) -> tuple[Decimal, Decimal]:
    """Divide one instalment into (principal, interest).

    Interest is taken first, which is how every lender applies a payment. Only
    the interest half is a business expense — booking the whole instalment as
    one would understate profit by the principal every month.
    """
    owed = D(outstanding)
    paid = D(amount)
    if paid <= 0 or owed <= 0:
        return ZERO, ZERO

    if interest_type == InterestType.NONE:
        interest = ZERO
    elif flat_monthly_interest is not None:
        interest = money(flat_monthly_interest)
    else:
        interest = money(owed * monthly_rate(annual_rate))

    interest = min(interest, paid)
    principal = money(min(paid - interest, owed))
    return principal, money(interest)


def add_months(start: date, months: int) -> date:
    """Same day next month, clamped to the shortest month.

    A loan taken on the 31st is due on the 30th in April and the 28th in
    February. Nobody's instalment silently jumps into the following month.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31
