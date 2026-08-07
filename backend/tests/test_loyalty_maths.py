"""Loyalty arithmetic.

Points are money to the customer holding them. A shop that miscounts them will
be argued with at the counter, and the customer will be right.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.loyalty import (
    Lot, allocate, expiry_for, max_redeemable, points_for, scheme_cost_percent,
    stale_lots, usable_balance, value_of,
)

D = Decimal
ONE_PER_HUNDRED = D("0.01")


# ── earning ────────────────────────────────────────────────────────
def test_one_point_per_hundred_rupees():
    assert points_for(D("5000"), ONE_PER_HUNDRED) == 50


def test_points_round_down_never_up():
    """Rounding up gives away a point on every bill, which across a year of
    trading is a real number — and nobody complains about not being given a
    point they did not earn."""
    assert points_for(D("5099"), ONE_PER_HUNDRED) == 50
    assert points_for(D("199"), ONE_PER_HUNDRED) == 1
    assert points_for(D("99"), ONE_PER_HUNDRED) == 0


def test_a_bill_below_the_threshold_earns_nothing():
    assert points_for(D("400"), ONE_PER_HUNDRED, minimum=D("500")) == 0
    assert points_for(D("500"), ONE_PER_HUNDRED, minimum=D("500")) == 5


def test_a_scheme_that_is_switched_off_earns_nothing():
    assert points_for(D("5000"), D("0")) == 0


def test_a_credit_note_earns_nothing():
    assert points_for(D("-5000"), ONE_PER_HUNDRED) == 0


# ── what points are worth ──────────────────────────────────────────
def test_points_convert_at_the_shop_s_own_rate():
    assert value_of(50, D("1")) == D("50.00")
    assert value_of(50, D("0.5")) == D("25.00")


def test_no_points_is_worth_nothing():
    assert value_of(0, D("1")) == D("0")
    assert value_of(-10, D("1")) == D("0")


def test_the_scheme_cost_is_stated_plainly():
    """One point per hundred, each worth a rupee, is a 1% scheme. A shopkeeper
    should see that before they save it."""
    assert scheme_cost_percent(ONE_PER_HUNDRED, D("1")) == D("1.00")
    assert scheme_cost_percent(D("1"), D("1")) == D("100.00"), "giving away everything"
    assert scheme_cost_percent(D("0.05"), D("1")) == D("5.00")


# ── how many may be spent ──────────────────────────────────────────
def test_a_customer_cannot_spend_points_they_do_not_have():
    assert max_redeemable(30, D("10000"), D("1")) == 30


def test_points_cannot_exceed_the_bill():
    assert max_redeemable(5000, D("300"), D("1")) == 300


def test_a_cap_holds_back_how_much_one_bill_can_be_paid_with():
    """Without one, a regular customer takes a whole bill for nothing, which
    is not what anyone meant by 1%."""
    assert max_redeemable(5000, D("1000"), D("1"), max_percent=D("20")) == 200


def test_a_minimum_stops_a_handful_of_points_being_spent():
    assert max_redeemable(40, D("5000"), D("1"), minimum_points=50) == 0
    assert max_redeemable(50, D("5000"), D("1"), minimum_points=50) == 50


def test_a_high_point_value_still_cannot_overpay_a_bill():
    # Points worth 10 each, on a bill of 95: nine points, not ten.
    assert max_redeemable(100, D("95"), D("10")) == 9


def test_nothing_is_redeemable_against_nothing():
    assert max_redeemable(500, D("0"), D("1")) == 0
    assert max_redeemable(0, D("5000"), D("1")) == 0


# ── expiry dates ───────────────────────────────────────────────────
def test_points_go_stale_after_the_set_months():
    assert expiry_for(date(2026, 8, 7), 12) == date(2027, 8, 7)
    assert expiry_for(date(2026, 8, 7), 6) == date(2027, 2, 7)


def test_a_scheme_with_no_expiry_gives_none():
    assert expiry_for(date(2026, 8, 7), None) is None
    assert expiry_for(date(2026, 8, 7), 0) is None


def test_an_expiry_landing_on_a_short_month_is_clamped():
    assert expiry_for(date(2026, 8, 31), 6) == date(2027, 2, 28)


# ── spending from lots ─────────────────────────────────────────────
def test_the_points_closest_to_expiry_are_spent_first():
    """Spending the newest would let points quietly lapse while the customer
    was actively using the scheme — the exact thing that makes people stop
    trusting a loyalty card."""
    lots = [
        Lot("new", 100, date(2027, 12, 1)),
        Lot("soon", 40, date(2026, 9, 1)),
        Lot("mid", 60, date(2027, 1, 1)),
    ]
    assert allocate(lots, 70, on=date(2026, 8, 7)) == [("soon", 40), ("mid", 30)]


def test_points_that_never_expire_are_spent_last():
    lots = [Lot("forever", 100, None), Lot("dated", 30, date(2026, 9, 1))]
    assert allocate(lots, 50, on=date(2026, 8, 7)) == [("dated", 30), ("forever", 20)]


def test_expired_points_are_never_spent():
    lots = [Lot("gone", 500, date(2026, 1, 1)), Lot("live", 20, date(2027, 1, 1))]
    assert allocate(lots, 20, on=date(2026, 8, 7)) == [("live", 20)]


def test_spending_more_than_is_available_is_refused():
    lots = [Lot("a", 10, None)]
    with pytest.raises(ValueError, match="Only 10 points"):
        allocate(lots, 50)


def test_spending_nothing_takes_nothing():
    assert allocate([Lot("a", 10, None)], 0) == []


def test_a_lot_with_nothing_left_is_skipped():
    lots = [Lot("spent", 0, date(2026, 9, 1)), Lot("live", 25, date(2027, 1, 1))]
    assert allocate(lots, 25, on=date(2026, 8, 7)) == [("live", 25)]


# ── the balance ────────────────────────────────────────────────────
def test_the_usable_balance_leaves_out_what_has_already_lapsed():
    lots = [
        Lot("gone", 500, date(2026, 1, 1)),
        Lot("live", 120, date(2027, 1, 1)),
        Lot("forever", 30, None),
    ]
    assert usable_balance(lots, on=date(2026, 8, 7)) == 150


def test_lapsed_lots_can_be_listed_so_they_can_be_written_off():
    lots = [
        Lot("gone", 500, date(2026, 1, 1)),
        Lot("live", 120, date(2027, 1, 1)),
    ]
    stale = stale_lots(lots, on=date(2026, 8, 7))
    assert [lot.id for lot in stale] == ["gone"]


def test_a_lot_expiring_today_is_still_spendable():
    """A card that stops working on the morning of its expiry date is a card
    the customer will say stopped working early."""
    lots = [Lot("today", 50, date(2026, 8, 7))]
    assert usable_balance(lots, on=date(2026, 8, 7)) == 50
    assert allocate(lots, 50, on=date(2026, 8, 7)) == [("today", 50)]


def test_a_customer_with_no_points_has_a_balance_of_nothing():
    assert usable_balance([]) == 0
