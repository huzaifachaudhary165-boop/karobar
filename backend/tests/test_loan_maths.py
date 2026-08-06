"""Loan arithmetic, checked against figures a bank would print.

These are pure functions, so they can be pinned to exact numbers. A shopkeeper
holding the bank's own schedule next to ours will notice a single rupee.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.loan_maths import add_months, emi, monthly_rate, schedule, split_payment
from app.models.enums import InterestType

D = Decimal


def test_a_reducing_balance_emi_matches_the_standard_formula():
    # 500,000 over 24 months at 12% a year is a widely published figure.
    assert emi(D("500000"), D("12"), 24) == D("23536.74")


def test_a_flat_rate_emi_spreads_the_whole_interest_evenly():
    # 12% flat on 100,000 for 2 years = 24,000 interest, so 124,000 over 24.
    assert emi(D("100000"), D("12"), 24, InterestType.FLAT) == D("5166.67")


def test_flat_costs_more_than_reducing_at_the_same_headline_rate():
    """The point of showing both: '12% flat' is not the same offer as '12%'."""
    flat = emi(D("100000"), D("12"), 24, InterestType.FLAT)
    reducing = emi(D("100000"), D("12"), 24, InterestType.REDUCING)
    assert flat > reducing


def test_an_interest_free_loan_just_divides_the_principal():
    assert emi(D("60000"), D("0"), 12, InterestType.NONE) == D("5000.00")


def test_a_zero_rate_is_treated_as_interest_free_whatever_the_type():
    assert emi(D("60000"), D("0"), 12, InterestType.REDUCING) == D("5000.00")


def test_a_loan_with_no_principal_or_no_term_has_no_instalment():
    assert emi(D("0"), D("12"), 24) == D("0")
    assert emi(D("50000"), D("12"), 0) == D("0")


def test_a_yearly_rate_becomes_a_monthly_fraction():
    assert monthly_rate(D("18")) == D("18") / D("100") / D("12")


# ── the schedule ───────────────────────────────────────────────────
def test_a_schedule_has_one_row_per_month():
    rows = schedule(D("120000"), D("15"), 12, date(2026, 1, 15))
    assert len(rows) == 12
    assert rows[0].number == 1 and rows[-1].number == 12


def test_a_schedule_ends_owing_exactly_nothing():
    """Rounding accumulates over a term. The last instalment has to absorb it."""
    for principal, rate, months in (
        (D("500000"), D("12"), 24),
        (D("83333"), D("17.5"), 37),
        (D("1000000"), D("9.25"), 60),
    ):
        rows = schedule(principal, rate, months, date(2026, 3, 31))
        assert rows[-1].balance_after == D("0.00"), f"{principal} @ {rate}% × {months}"


def test_every_rupee_of_principal_is_accounted_for():
    principal = D("250000")
    rows = schedule(principal, D("14"), 36, date(2026, 1, 1))
    assert sum(r.principal for r in rows) == principal


def test_each_instalment_is_its_own_two_halves():
    rows = schedule(D("300000"), D("11"), 18, date(2026, 6, 10))
    for row in rows:
        assert row.amount == row.principal + row.interest


def test_interest_falls_as_the_debt_is_repaid():
    rows = schedule(D("400000"), D("13"), 24, date(2026, 1, 1))
    interest = [r.interest for r in rows]
    assert interest == sorted(interest, reverse=True)
    assert interest[0] > interest[-1]


def test_flat_interest_stays_the_same_every_month():
    rows = schedule(D("100000"), D("12"), 24, date(2026, 1, 1), InterestType.FLAT)
    assert len({r.interest for r in rows[:-1]}) == 1, "flat interest does not reduce"


def test_an_interest_free_schedule_charges_nothing():
    rows = schedule(D("60000"), D("0"), 12, date(2026, 1, 1), InterestType.NONE)
    assert all(r.interest == 0 for r in rows)
    assert sum(r.amount for r in rows) == D("60000")


def test_due_dates_run_month_by_month_from_the_start():
    rows = schedule(D("60000"), D("0"), 3, date(2026, 1, 10), InterestType.NONE)
    assert [r.due_date for r in rows] == [date(2026, 2, 10), date(2026, 3, 10), date(2026, 4, 10)]


# ── applying a payment ─────────────────────────────────────────────
def test_a_payment_pays_the_interest_before_the_debt():
    principal, interest = split_payment(D("100000"), D("10000"), D("12"))
    assert interest == D("1000.00")          # one month at 1%
    assert principal == D("9000.00")


def test_a_payment_smaller_than_the_interest_repays_no_debt_at_all():
    """This is how a loan grows despite being paid — the app must not hide it."""
    principal, interest = split_payment(D("100000"), D("500"), D("12"))
    assert interest == D("500.00")
    assert principal == D("0.00")


def test_a_final_payment_never_repays_more_than_is_owed():
    principal, interest = split_payment(D("2000"), D("50000"), D("12"))
    assert principal == D("2000.00")


def test_an_interest_free_payment_is_all_principal():
    principal, interest = split_payment(D("50000"), D("5000"), D("0"), InterestType.NONE)
    assert (principal, interest) == (D("5000.00"), D("0"))


def test_nothing_owed_means_nothing_to_split():
    assert split_payment(D("0"), D("5000"), D("12")) == (D("0"), D("0"))


# ── dates ──────────────────────────────────────────────────────────
def test_the_31st_does_not_slip_into_the_next_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)


def test_february_is_handled_in_a_leap_year():
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_a_year_of_months_lands_on_the_same_day():
    assert add_months(date(2026, 5, 15), 12) == date(2027, 5, 15)


def test_crossing_a_year_boundary_works():
    assert add_months(date(2026, 11, 20), 3) == date(2027, 2, 20)
