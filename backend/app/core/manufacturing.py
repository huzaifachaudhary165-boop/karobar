"""Working out what a made thing cost.

Kept apart so the arithmetic can be checked on its own. Getting this wrong is
the quietest possible error: the unit cost becomes the finished item's cost of
sales, so every margin the shop reads afterwards is wrong by the same amount
and nothing on any screen looks unusual.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import HUNDRED, ZERO, D, money, qty, safe_div


@dataclass(frozen=True)
class Component:
    """One material a recipe needs, per batch."""

    item_id: str
    item_name: str
    qty_per_batch: Decimal
    rate: Decimal
    available: Decimal | None = None


@dataclass(frozen=True)
class Requirement:
    """How much of one material a run actually needs."""

    item_id: str
    item_name: str
    needed: Decimal
    rate: Decimal
    value: Decimal
    available: Decimal | None = None

    @property
    def is_short(self) -> bool:
        return self.available is not None and self.available < self.needed

    @property
    def shortfall(self) -> Decimal:
        if self.available is None:
            return ZERO
        return max(ZERO, qty(self.needed - self.available))


@dataclass(frozen=True)
class Costing:
    """What a run comes to, and what one finished unit cost."""

    material_cost: Decimal
    labour_cost: Decimal
    overhead_cost: Decimal
    wastage_cost: Decimal
    total_cost: Decimal
    unit_cost: Decimal
    requirements: list[Requirement]

    @property
    def shortages(self) -> list[Requirement]:
        return [row for row in self.requirements if row.is_short]


def batches_for(output_qty: Decimal, wanted: Decimal) -> Decimal:
    """How many runs of a recipe are needed to make `wanted` units.

    Fractional on purpose. A recipe that yields forty rusks can be run for
    twenty; rounding up to a whole batch would consume twice the flour and
    silently double what those twenty cost.
    """
    if output_qty <= 0:
        raise ValueError("A recipe has to produce something.")
    return qty(safe_div(D(wanted), D(output_qty)))


def cost_run(
    components: list[Component],
    *,
    output_qty: Decimal,
    making: Decimal,
    labour_cost: Decimal = ZERO,
    overhead_cost: Decimal = ZERO,
    wastage_percent: Decimal = ZERO,
) -> Costing:
    """What making `making` units of this recipe needs, and what it costs.

    Labour and overhead are stated per batch and scale with the number of
    batches, not with the calendar. Half a batch of biscuits does not take a
    whole day's wages.
    """
    if making <= 0:
        raise ValueError("Set how many to make.")

    runs = batches_for(output_qty, making)

    requirements: list[Requirement] = []
    materials = ZERO
    for component in components:
        needed = qty(component.qty_per_batch * runs)
        value = money(needed * component.rate)
        materials += value
        requirements.append(
            Requirement(
                item_id=component.item_id,
                item_name=component.item_name,
                needed=needed,
                rate=money(component.rate),
                value=value,
                available=component.available,
            )
        )

    materials = money(materials)
    # Wastage is a loss of materials, so it is a percentage of the materials —
    # not of the labour, which is paid whether the flour burns or not.
    wastage = money(materials * D(wastage_percent) / HUNDRED)
    labour = money(D(labour_cost) * runs)
    overhead = money(D(overhead_cost) * runs)

    total = money(materials + wastage + labour + overhead)
    return Costing(
        material_cost=materials,
        labour_cost=labour,
        overhead_cost=overhead,
        wastage_cost=wastage,
        total_cost=total,
        unit_cost=money(safe_div(total, D(making))),
        requirements=requirements,
    )


def max_producible(components: list[Component], output_qty: Decimal) -> Decimal:
    """How many units the materials on hand could actually make.

    The scarcest component decides, which is the number a shopkeeper is
    actually asking for when they look at a recipe: not "have I got flour" but
    "how many trays can I get out of today".
    """
    if output_qty <= 0:
        return ZERO

    limits: list[Decimal] = []
    for component in components:
        if component.available is None or component.qty_per_batch <= 0:
            continue
        limits.append(safe_div(component.available, component.qty_per_batch))

    if not limits:
        return ZERO
    return qty(min(limits) * D(output_qty))
