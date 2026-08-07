"""Pakistani sales tax, as the FBR levies it.

Not GST. Pakistan runs federal sales tax under the Sales Tax Act 1990,
administered by the FBR, and it has rules India's GST does not — the one that
catches shops out being *further tax*, charged on top of the ordinary rate when
the buyer is not registered for sales tax. A shop that has never heard of it
under-charges every unregistered customer and is assessed for the difference
years later, with penalty.

Everything here is off unless a shop turns it on. Most small shops are not
registered for sales tax at all, and showing them an output-tax column is a
good way to make them think the app is for someone else.

Rates are settings, not constants. The standard rate has moved between 16, 17
and 18 percent inside a decade, and a shop that has to wait for an app update
to bill correctly on the day a budget takes effect is a shop that bills wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import HUNDRED, ZERO, D, money

# What the standard rate happens to be as this is written. A default, not a
# rule — the shop's own setting is what actually bills.
STANDARD_RATE = Decimal("18")

# Charged on top when the buyer has no sales tax registration number.
DEFAULT_FURTHER_TAX_RATE = Decimal("3")

# Provincial sales tax on *services* is a separate levy from a separate
# authority, and a shop billing both federal goods and provincial services is
# dealing with two collectors.
PROVINCIAL_AUTHORITIES = {
    "punjab": ("PRA", "Punjab Revenue Authority"),
    "sindh": ("SRB", "Sindh Revenue Board"),
    "kpk": ("KPRA", "Khyber Pakhtunkhwa Revenue Authority"),
    "balochistan": ("BRA", "Balochistan Revenue Authority"),
    "islamabad": ("FBR", "Federal Board of Revenue (ICT)"),
}


@dataclass(frozen=True)
class TaxSetup:
    """What a shop has switched on."""

    enabled: bool = False
    rate: Decimal = STANDARD_RATE
    further_tax_enabled: bool = True
    further_tax_rate: Decimal = DEFAULT_FURTHER_TAX_RATE
    withholding_enabled: bool = False
    withholding_rate: Decimal = ZERO
    prices_include_tax: bool = False


@dataclass(frozen=True)
class LineTax:
    """What one line owes."""

    taxable: Decimal
    sales_tax: Decimal
    further_tax: Decimal
    extra_tax: Decimal

    @property
    def total_tax(self) -> Decimal:
        return money(self.sales_tax + self.further_tax + self.extra_tax)

    @property
    def gross(self) -> Decimal:
        return money(self.taxable + self.total_tax)


def compute_line(
    amount: Decimal,
    setup: TaxSetup,
    *,
    rate: Decimal | None = None,
    buyer_registered: bool = True,
    exempt: bool = False,
    zero_rated: bool = False,
    extra_tax_rate: Decimal = ZERO,
) -> LineTax:
    """Tax on one line.

    `buyer_registered` is the whole point of further tax: a registered buyer
    reclaims the sales tax as input, an unregistered one does not, and the
    further tax exists to stop the second being cheaper than the first. Getting
    it wrong is not a rounding error — it is three percent of every sale to
    every walk-in customer.
    """
    base = D(amount)
    if not setup.enabled or base <= 0:
        return LineTax(money(max(base, ZERO)), ZERO, ZERO, ZERO)

    # Exempt and zero-rated are different things that both come to nothing
    # here: an exempt supply carries no tax and no input claim, a zero-rated
    # one carries no tax but keeps the claim. The return has to tell them
    # apart, which is why they are separate flags rather than "rate = 0".
    if exempt or zero_rated:
        return LineTax(money(base), ZERO, ZERO, ZERO)

    applied = D(rate if rate is not None else setup.rate)

    if setup.prices_include_tax:
        # The entered figure already has the tax in it, so it has to come back
        # out — including the further tax, which is levied on the same value
        # and so shares the divisor.
        divisor = HUNDRED + applied
        if setup.further_tax_enabled and not buyer_registered:
            divisor += D(setup.further_tax_rate)
        divisor += D(extra_tax_rate)
        taxable = money(base * HUNDRED / divisor)
    else:
        taxable = money(base)

    sales_tax = money(taxable * applied / HUNDRED)
    further = (
        money(taxable * D(setup.further_tax_rate) / HUNDRED)
        if setup.further_tax_enabled and not buyer_registered
        else ZERO
    )
    extra = money(taxable * D(extra_tax_rate) / HUNDRED) if extra_tax_rate else ZERO

    return LineTax(taxable, sales_tax, further, extra)


def withholding_on(sales_tax: Decimal, setup: TaxSetup) -> Decimal:
    """What a withholding agent keeps back rather than paying to the supplier.

    A share of the sales tax, not of the invoice. The buyer pays it straight to
    the FBR on the supplier's behalf, so the supplier receives less than the
    invoice says and must not treat the shortfall as a bad debt.
    """
    if not setup.enabled or not setup.withholding_enabled or sales_tax <= 0:
        return ZERO
    return money(D(sales_tax) * D(setup.withholding_rate) / HUNDRED)


def net_payable(output_tax: Decimal, input_tax: Decimal) -> tuple[Decimal, Decimal]:
    """What the month's return comes to: (payable, carried forward).

    Input tax above output tax is not a refund cheque — it carries forward to
    the next month. A shop shown "refund due" would go looking for money that
    is not coming.
    """
    difference = money(D(output_tax) - D(input_tax))
    if difference >= 0:
        return difference, ZERO
    return ZERO, money(-difference)


def is_registered(strn: str | None, ntn: str | None = None) -> bool:
    """Whether a party counts as sales-tax registered.

    The STRN is what registration means here. An NTN alone is income tax
    registration and does not stop further tax — treating the two as the same
    is exactly how a shop ends up under-charging.
    """
    return bool(strn and strn.strip())


def clean_ntn(value: str | None) -> str | None:
    """Normalise an NTN: seven digits and a check digit, dashes optional."""
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    if len(digits) == 8:
        return f"{digits[:7]}-{digits[7]}"
    return digits


def clean_strn(value: str | None) -> str | None:
    """Normalise an STRN to its thirteen digits."""
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits or None


def validate_ntn(value: str | None) -> bool:
    if not value:
        return False
    digits = "".join(ch for ch in value if ch.isdigit())
    return len(digits) in (7, 8)


def validate_strn(value: str | None) -> bool:
    if not value:
        return False
    return len("".join(ch for ch in value if ch.isdigit())) == 13


def authority_for(province: str | None) -> tuple[str, str] | None:
    """Which revenue authority collects the services tax where a shop trades."""
    if not province:
        return None
    return PROVINCIAL_AUTHORITIES.get(province.strip().lower())
