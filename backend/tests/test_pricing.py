"""How a line's rate is decided.

The order these rules apply in is the whole of the behaviour. A shopkeeper has
to be able to explain a total to the customer standing in front of them, so
every rule here is one they could say out loud.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.pricing import (
    ItemPrices, ListRule, Scheme, applies_on, best_scheme, discount_amount,
    enforce_floor, resolve_rate,
)
from app.models.enums import DiscountType

D = Decimal
SUGAR = ItemPrices(sale=D("7400"), purchase=D("6800"), mrp=D("7800"),
                   wholesale=D("7100"), min_sale=D("6900"))


# ── which rate wins ────────────────────────────────────────────────
def test_with_no_list_the_item_s_own_price_is_used():
    line = resolve_rate(SUGAR)
    assert line.rate == D("7400.00")
    assert line.source == "item"


def test_a_blanket_rule_moves_the_whole_catalogue():
    """Most shops want this and would never fill in a rate per item."""
    line = resolve_rate(SUGAR, rule=ListRule(adjust_percent=D("-8")))
    assert line.rate == D("6808.00")
    assert line.source == "list_rule"


def test_a_markup_works_the_same_way_upward():
    line = resolve_rate(SUGAR, rule=ListRule(adjust_percent=D("12")))
    assert line.rate == D("8288.00")


def test_a_rule_can_start_from_a_different_price():
    line = resolve_rate(SUGAR, rule=ListRule(adjust_percent=D("0"), base_price="mrp"))
    assert line.rate == D("7800.00")


def test_a_named_rate_beats_the_blanket_rule():
    """'Everything at 8% off, except sugar which is fixed' — the point of a
    price list."""
    line = resolve_rate(
        SUGAR, entry_price=D("7000"), rule=ListRule(adjust_percent=D("-8"))
    )
    assert line.rate == D("7000.00")
    assert line.source == "list_entry"


def test_a_named_rate_of_zero_is_honoured_rather_than_ignored():
    """A free line is a real thing — a sample, a replacement — and treating
    zero as 'unset' would quietly bill for it."""
    line = resolve_rate(SUGAR, entry_price=D("0"))
    assert line.rate == D("0.00")
    assert line.source == "list_entry"


def test_a_rule_starting_from_a_price_the_item_lacks_falls_back():
    """Pricing from MRP on an item with no MRP must not produce a free sack of
    sugar — it would leave the shop before anyone noticed."""
    no_mrp = ItemPrices(sale=D("500"), purchase=D("400"))
    line = resolve_rate(no_mrp, rule=ListRule(adjust_percent=D("-10"), base_price="mrp"))
    assert line.rate == D("450.00"), "fell back to the selling price"


def test_a_rule_cannot_take_more_than_the_whole_price():
    line = resolve_rate(SUGAR, rule=ListRule(adjust_percent=D("-150")))
    assert line.rate == D("0")


# ── the price floor ────────────────────────────────────────────────
def test_a_rate_above_the_floor_is_left_alone():
    rate, held = enforce_floor(D("7000"), D("6900"))
    assert (rate, held) == (D("7000.00"), False)


def test_a_rate_below_the_floor_is_held_and_reported():
    """Silently honouring it defeats the setting; silently refusing the sale
    strands a customer at the counter."""
    rate, held = enforce_floor(D("6500"), D("6900"))
    assert rate == D("6900.00")
    assert held is True


def test_an_item_with_no_floor_takes_any_rate():
    rate, held = enforce_floor(D("1"), None)
    assert (rate, held) == (D("1.00"), False)


# ── how much a scheme takes off ────────────────────────────────────
def test_a_percentage_scheme():
    scheme = Scheme("Eid offer", DiscountType.PERCENT, D("10"))
    assert discount_amount(scheme, D("5000")) == D("500.00")


def test_a_flat_scheme():
    scheme = Scheme("Rs 200 off", DiscountType.AMOUNT, D("200"))
    assert discount_amount(scheme, D("5000")) == D("200.00")


def test_a_cap_holds_a_percentage_down():
    scheme = Scheme("10% up to 300", DiscountType.PERCENT, D("10"), max_discount=D("300"))
    assert discount_amount(scheme, D("10000")) == D("300.00")
    assert discount_amount(scheme, D("2000")) == D("200.00")


def test_a_flat_discount_never_exceeds_the_bill():
    """Rs 500 off a Rs 300 bill is a refund nobody agreed to."""
    scheme = Scheme("Rs 500 off", DiscountType.AMOUNT, D("500"))
    assert discount_amount(scheme, D("300")) == D("300.00")


def test_nothing_is_taken_off_nothing():
    scheme = Scheme("10%", DiscountType.PERCENT, D("10"))
    assert discount_amount(scheme, D("0")) == D("0")


# ── which scheme applies ───────────────────────────────────────────
def test_a_scheme_below_its_threshold_does_not_fire():
    schemes = [Scheme("Over 5000", DiscountType.PERCENT, D("5"), min_amount=D("5000"))]
    assert best_scheme(schemes, line_total=D("4000"), qty=D("1")) is None


def test_a_scheme_at_its_threshold_does_fire():
    schemes = [Scheme("Over 5000", DiscountType.PERCENT, D("5"), min_amount=D("5000"))]
    result = best_scheme(schemes, line_total=D("5000"), qty=D("1"))
    assert result is not None and result[1] == D("250.00")


def test_a_quantity_threshold_is_honoured():
    schemes = [Scheme("Buy 10+", DiscountType.PERCENT, D("6"), min_qty=D("10"))]
    assert best_scheme(schemes, line_total=D("1000"), qty=D("9")) is None
    assert best_scheme(schemes, line_total=D("1000"), qty=D("10")) is not None


def test_only_one_scheme_applies_never_two_stacked():
    """Two rules that both fire produce a total the shopkeeper cannot account
    for, and the customer only ever asks about the number at the bottom."""
    schemes = [
        Scheme("10%", DiscountType.PERCENT, D("10")),
        Scheme("Rs 300 off", DiscountType.AMOUNT, D("300")),
    ]
    result = best_scheme(schemes, line_total=D("5000"), qty=D("1"))
    assert result is not None
    assert result[1] in (D("500.00"), D("300.00"))
    assert result[1] != D("800.00"), "the two must not add up"


def test_priority_decides_before_size_does():
    """The shop's own ordering wins, not whichever discount happens to be
    larger — a clearance rule is meant to beat the everyday one."""
    schemes = [
        Scheme("Everyday 15%", DiscountType.PERCENT, D("15"), priority=0),
        Scheme("Member 5%", DiscountType.PERCENT, D("5"), priority=10),
    ]
    scheme, amount = best_scheme(schemes, line_total=D("1000"), qty=D("1"))
    assert scheme.name == "Member 5%"
    assert amount == D("50.00")


def test_where_priorities_tie_the_customer_gets_the_larger():
    schemes = [
        Scheme("5%", DiscountType.PERCENT, D("5"), priority=1),
        Scheme("12%", DiscountType.PERCENT, D("12"), priority=1),
    ]
    scheme, amount = best_scheme(schemes, line_total=D("1000"), qty=D("1"))
    assert scheme.name == "12%"
    assert amount == D("120.00")


def test_a_scheme_worth_nothing_is_not_offered():
    schemes = [Scheme("0%", DiscountType.PERCENT, D("0"))]
    assert best_scheme(schemes, line_total=D("1000"), qty=D("1")) is None


def test_no_schemes_at_all_is_not_an_error():
    assert best_scheme([], line_total=D("1000"), qty=D("1")) is None


# ── when a scheme runs ─────────────────────────────────────────────
def test_a_scheme_runs_between_its_dates():
    assert applies_on(date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 15))


def test_a_scheme_does_not_run_before_it_starts():
    assert not applies_on(date(2026, 8, 1), date(2026, 8, 31), date(2026, 7, 31))


def test_a_scheme_does_not_run_after_it_ends():
    assert not applies_on(date(2026, 8, 1), date(2026, 8, 31), date(2026, 9, 1))


def test_the_first_and_last_days_are_both_inside():
    assert applies_on(date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 1))
    assert applies_on(date(2026, 8, 1), date(2026, 8, 31), date(2026, 8, 31))


def test_a_scheme_with_no_dates_always_runs():
    assert applies_on(None, None, date(2030, 1, 1))


def test_an_inactive_scheme_never_runs_whatever_its_dates():
    assert not applies_on(None, None, date(2026, 8, 15), active=False)


# ── the whole line, end to end ─────────────────────────────────────
@pytest.mark.parametrize(
    "entry,rule,scheme_pct,expected_rate,expected_net",
    [
        (None, None, 0, D("7400.00"), D("7400.00")),
        (None, D("-8"), 0, D("6808.00"), D("6808.00")),
        (D("7000"), D("-8"), 0, D("7000.00"), D("7000.00")),
        (None, None, 10, D("7400.00"), D("6660.00")),
        (D("7000"), None, 10, D("7000.00"), D("6300.00")),
    ],
)
def test_a_line_prices_the_way_a_shopkeeper_would_explain_it(
    entry, rule, scheme_pct, expected_rate, expected_net
):
    line = resolve_rate(
        SUGAR,
        entry_price=entry,
        rule=ListRule(adjust_percent=rule) if rule is not None else None,
    )
    assert line.rate == expected_rate

    discount = Decimal("0")
    if scheme_pct:
        found = best_scheme(
            [Scheme("offer", DiscountType.PERCENT, D(scheme_pct))],
            line_total=line.rate,
            qty=D("1"),
        )
        discount = found[1] if found else Decimal("0")

    assert line.rate - discount == expected_net
