"""Pakistani sales tax.

The rule that catches shops out is further tax: charged on top of the ordinary
rate when the buyer is not registered. A shop that has never heard of it
under-charges every unregistered customer and is assessed for the difference
years later, with penalty. Most of what follows is about that.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.pakistan_tax import (
    STANDARD_RATE, TaxSetup, authority_for, clean_ntn, clean_strn, compute_line,
    is_registered, net_payable, validate_ntn, validate_strn, withholding_on,
)

D = Decimal
ON = TaxSetup(enabled=True, rate=D("18"))
OFF = TaxSetup(enabled=False)


# ── the switch ─────────────────────────────────────────────────────
def test_a_shop_that_has_not_turned_it_on_is_charged_nothing():
    """Most small shops are not registered for sales tax at all, and showing
    them an output-tax column makes them think the app is for someone else."""
    line = compute_line(D("10000"), OFF, buyer_registered=False)
    assert line.sales_tax == D("0")
    assert line.further_tax == D("0")
    assert line.gross == D("10000.00")


# ── the ordinary rate ──────────────────────────────────────────────
def test_a_registered_buyer_pays_the_standard_rate_only():
    line = compute_line(D("10000"), ON, buyer_registered=True)
    assert line.taxable == D("10000.00")
    assert line.sales_tax == D("1800.00")
    assert line.further_tax == D("0")
    assert line.gross == D("11800.00")


def test_the_rate_is_a_setting_not_a_constant():
    """It has moved between 16, 17 and 18 percent inside a decade, and a shop
    waiting for an app update to bill correctly on budget day bills wrong."""
    line = compute_line(D("10000"), TaxSetup(enabled=True, rate=D("17")))
    assert line.sales_tax == D("1700.00")


def test_the_default_standard_rate_is_the_current_one():
    assert STANDARD_RATE == D("18")


# ── further tax ────────────────────────────────────────────────────
def test_an_unregistered_buyer_pays_further_tax_on_top():
    """Three percent of every sale to every walk-in customer — not a rounding
    error."""
    line = compute_line(D("10000"), ON, buyer_registered=False)
    assert line.sales_tax == D("1800.00")
    assert line.further_tax == D("300.00")
    assert line.gross == D("12100.00")


def test_further_tax_is_worked_out_on_the_value_not_on_the_sales_tax():
    line = compute_line(D("10000"), ON, buyer_registered=False)
    assert line.further_tax == D("300.00")   # 3% of 10,000, not of 1,800


def test_a_shop_can_switch_further_tax_off():
    setup = TaxSetup(enabled=True, rate=D("18"), further_tax_enabled=False)
    line = compute_line(D("10000"), setup, buyer_registered=False)
    assert line.further_tax == D("0")


def test_the_further_tax_rate_is_also_a_setting():
    setup = TaxSetup(enabled=True, rate=D("18"), further_tax_rate=D("4"))
    line = compute_line(D("10000"), setup, buyer_registered=False)
    assert line.further_tax == D("400.00")


# ── exempt and zero-rated are not the same thing ───────────────────
def test_an_exempt_supply_carries_no_tax():
    line = compute_line(D("10000"), ON, exempt=True, buyer_registered=False)
    assert line.total_tax == D("0")
    assert line.gross == D("10000.00")


def test_a_zero_rated_supply_carries_no_tax_either():
    """Different from exempt — a zero-rated supply keeps the input claim — but
    the invoice comes to the same, which is why the return needs both flags."""
    line = compute_line(D("10000"), ON, zero_rated=True, buyer_registered=False)
    assert line.total_tax == D("0")


# ── tax-inclusive prices ───────────────────────────────────────────
def test_a_tax_inclusive_price_is_split_back_out():
    setup = TaxSetup(enabled=True, rate=D("18"), prices_include_tax=True)
    line = compute_line(D("11800"), setup, buyer_registered=True)
    assert line.taxable == D("10000.00")
    assert line.sales_tax == D("1800.00")
    assert line.gross == D("11800.00")


def test_a_tax_inclusive_price_accounts_for_further_tax_in_the_divisor():
    """Otherwise the shop hands the FBR three percent out of its own margin."""
    setup = TaxSetup(enabled=True, rate=D("18"), prices_include_tax=True)
    line = compute_line(D("12100"), setup, buyer_registered=False)
    assert line.taxable == D("10000.00")
    assert line.sales_tax == D("1800.00")
    assert line.further_tax == D("300.00")
    assert line.gross == D("12100.00")


# ── extra tax ──────────────────────────────────────────────────────
def test_extra_tax_is_added_where_it_applies():
    line = compute_line(D("10000"), ON, buyer_registered=True, extra_tax_rate=D("2"))
    assert line.extra_tax == D("200.00")
    assert line.gross == D("12000.00")


def test_the_three_taxes_add_up_to_the_total():
    line = compute_line(
        D("10000"), ON, buyer_registered=False, extra_tax_rate=D("2")
    )
    assert line.total_tax == line.sales_tax + line.further_tax + line.extra_tax
    assert line.total_tax == D("2300.00")


# ── withholding ────────────────────────────────────────────────────
def test_a_withholding_agent_keeps_back_part_of_the_sales_tax():
    """The buyer pays it straight to the FBR, so the supplier receives less
    than the invoice says and must not treat the shortfall as a bad debt."""
    setup = TaxSetup(
        enabled=True, rate=D("18"), withholding_enabled=True, withholding_rate=D("20")
    )
    assert withholding_on(D("1800"), setup) == D("360.00")


def test_nothing_is_withheld_when_the_shop_has_not_turned_it_on():
    assert withholding_on(D("1800"), ON) == D("0")
    assert withholding_on(D("1800"), OFF) == D("0")


# ── the monthly return ─────────────────────────────────────────────
def test_more_output_than_input_is_payable():
    payable, carried = net_payable(D("50000"), D("30000"))
    assert payable == D("20000.00")
    assert carried == D("0")


def test_more_input_than_output_carries_forward_rather_than_refunds():
    """A shop shown 'refund due' would go looking for money that is not
    coming."""
    payable, carried = net_payable(D("30000"), D("50000"))
    assert payable == D("0")
    assert carried == D("20000.00")


def test_equal_input_and_output_owes_nothing_either_way():
    assert net_payable(D("40000"), D("40000")) == (D("0.00"), D("0"))


# ── who counts as registered ───────────────────────────────────────
def test_an_strn_makes_a_buyer_registered():
    assert is_registered("1234567890123") is True


def test_an_ntn_alone_does_not():
    """Income tax registration is not sales tax registration, and treating the
    two as the same is exactly how a shop ends up under-charging."""
    assert is_registered(None, ntn="1234567-8") is False
    assert is_registered("", ntn="1234567-8") is False


def test_a_walk_in_customer_is_not_registered():
    assert is_registered(None) is False
    assert is_registered("   ") is False


# ── tidying the numbers up ─────────────────────────────────────────
def test_an_ntn_is_normalised_to_its_usual_form():
    assert clean_ntn("12345678") == "1234567-8"
    assert clean_ntn("1234567-8") == "1234567-8"


def test_an_strn_keeps_only_its_digits():
    assert clean_strn("12-34-5678901-23") == "1234567890123"


def test_nothing_in_gives_nothing_out():
    assert clean_ntn(None) is None
    assert clean_ntn("") is None
    assert clean_strn("abc") is None


@pytest.mark.parametrize("value,valid", [
    ("1234567-8", True), ("12345678", True), ("1234567", True),
    ("123", False), ("", False), (None, False),
])
def test_ntn_validation(value, valid):
    assert validate_ntn(value) is valid


@pytest.mark.parametrize("value,valid", [
    ("1234567890123", True), ("12-34-5678901-23", True),
    ("12345", False), ("", False), (None, False),
])
def test_strn_validation(value, valid):
    assert validate_strn(value) is valid


# ── provincial services tax ────────────────────────────────────────
def test_the_right_authority_is_named_for_each_province():
    """A shop billing federal goods and provincial services is dealing with
    two collectors, and the invoice has to say which."""
    assert authority_for("punjab")[0] == "PRA"
    assert authority_for("Sindh")[0] == "SRB"
    assert authority_for("KPK")[0] == "KPRA"
    assert authority_for("balochistan")[0] == "BRA"


def test_an_unknown_province_names_nobody():
    assert authority_for("atlantis") is None
    assert authority_for(None) is None
