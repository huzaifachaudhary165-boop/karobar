"""Working out what one line costs.

Kept apart from the database so the rules can be checked on their own. The
order they apply in is the whole of the behaviour: a shopkeeper has to be able
to explain a total to the customer standing in front of them, and a rate nobody
can account for is worse than no discount at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.money import ZERO, D, money, pct
from app.models.enums import DiscountType

# Which of an item's own prices a list starts from.
BASE_PRICES = ("sale", "purchase", "mrp", "wholesale")


@dataclass(frozen=True)
class PricedLine:
    """What a line costs, and why."""

    rate: Decimal
    discount: Decimal
    source: str            # 'item' | 'list_entry' | 'list_rule'
    scheme_name: str | None = None

    @property
    def net(self) -> Decimal:
        return money(self.rate - self.discount)


@dataclass(frozen=True)
class ItemPrices:
    """The prices an item carries, as far as pricing is concerned."""

    sale: Decimal
    purchase: Decimal = ZERO
    mrp: Decimal | None = None
    wholesale: Decimal | None = None
    min_sale: Decimal | None = None

    def base(self, which: str) -> Decimal:
        """The starting price a list names, falling back to the selling price.

        A list set to start from MRP on an item that has no MRP must not price
        it at zero — that is a free sack of sugar, and it would go out of the
        shop before anyone noticed.
        """
        value = {
            "sale": self.sale,
            "purchase": self.purchase,
            "mrp": self.mrp,
            "wholesale": self.wholesale,
        }.get(which)
        return D(value) if value else self.sale


@dataclass(frozen=True)
class ListRule:
    """A price list's blanket rule."""

    adjust_percent: Decimal = ZERO
    base_price: str = "sale"


@dataclass(frozen=True)
class Scheme:
    """A discount rule, reduced to what deciding actually needs."""

    name: str
    discount_type: str = DiscountType.PERCENT
    discount_value: Decimal = ZERO
    max_discount: Decimal | None = None
    min_amount: Decimal | None = None
    min_qty: Decimal | None = None
    priority: int = 0
    scope: str = "bill"


def resolve_rate(
    prices: ItemPrices,
    *,
    entry_price: Decimal | None = None,
    rule: ListRule | None = None,
) -> PricedLine:
    """The rate before any discount scheme.

    An entry naming this exact item wins over the list's blanket rule, which in
    turn wins over the item's own price. That order is the point of a price
    list: "everything at 8% off, except sugar which is fixed".
    """
    if entry_price is not None:
        return PricedLine(rate=money(entry_price), discount=ZERO, source="list_entry")

    if rule is not None and (rule.adjust_percent != 0 or rule.base_price != "sale"):
        base = prices.base(rule.base_price)
        adjusted = money(base + pct(base, rule.adjust_percent))
        # A rule that takes more than the whole price off is a keying error, not
        # a giveaway. Floor at zero rather than hand out money.
        return PricedLine(
            rate=max(adjusted, ZERO), discount=ZERO, source="list_rule"
        )

    return PricedLine(rate=money(prices.sale), discount=ZERO, source="item")


def best_scheme(
    schemes: list[Scheme],
    *,
    line_total: Decimal,
    qty: Decimal,
) -> tuple[Scheme, Decimal] | None:
    """Pick the one scheme that applies, and what it takes off.

    One, not all of them stacked. Two rules that both fire produce a total the
    shopkeeper cannot account for, and the customer only ever asks about the
    number at the bottom. Highest priority wins; where priorities tie, the
    larger discount does, because that is what a customer shown two offers
    expects to get.
    """
    eligible: list[tuple[Scheme, Decimal]] = []

    for scheme in schemes:
        if scheme.min_amount is not None and line_total < scheme.min_amount:
            continue
        if scheme.min_qty is not None and qty < scheme.min_qty:
            continue

        amount = discount_amount(scheme, line_total)
        if amount > 0:
            eligible.append((scheme, amount))

    if not eligible:
        return None
    return max(eligible, key=lambda pair: (pair[0].priority, pair[1]))


def discount_amount(scheme: Scheme, base: Decimal) -> Decimal:
    """What one scheme takes off an amount, capped and floored."""
    amount = base if base <= 0 else ZERO
    if base <= 0:
        return ZERO

    if scheme.discount_type == DiscountType.PERCENT:
        amount = pct(base, scheme.discount_value)
    else:
        amount = money(scheme.discount_value)

    if scheme.max_discount is not None:
        amount = min(amount, money(scheme.max_discount))

    # Never more than the thing being discounted: a flat 500 off a 300 bill is
    # a refund nobody agreed to.
    return max(ZERO, min(amount, money(base)))


def enforce_floor(rate: Decimal, minimum: Decimal | None) -> tuple[Decimal, bool]:
    """Hold a rate at the item's minimum, reporting whether it had to.

    A shop sets a floor so a salesman cannot discount below cost. Silently
    honouring the lower price defeats the setting; silently refusing the sale
    strands a customer at the counter. So the rate is held and the caller is
    told, and the app says so on screen.
    """
    if minimum is None or rate >= minimum:
        return money(rate), False
    return money(minimum), True


def applies_on(
    starts_on: date | None, ends_on: date | None, when: date, active: bool = True
) -> bool:
    if not active:
        return False
    if starts_on and when < starts_on:
        return False
    if ends_on and when > ends_on:
        return False
    return True
