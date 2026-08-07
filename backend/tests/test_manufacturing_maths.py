"""What a made thing cost.

The quietest possible error lives here: the unit cost becomes the finished
item's cost of sales, so every margin the shop reads afterwards is wrong by the
same amount and nothing on any screen looks unusual.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.manufacturing import Component, batches_for, cost_run, max_producible

D = Decimal

# Forty rusks from one tray: flour, sugar, ghee.
RUSKS = [
    Component("flour", "Flour", D("2"), D("120"), available=D("50")),
    Component("sugar", "Sugar", D("1"), D("150"), available=D("20")),
    Component("ghee", "Ghee", D("0.5"), D("900"), available=D("6")),
]
TRAY = D("40")


# ── how many runs ──────────────────────────────────────────────────
def test_one_batch_makes_one_batch():
    assert batches_for(TRAY, D("40")) == D("1.0000")


def test_a_part_batch_is_a_fraction_not_a_whole_one():
    """Rounding up would consume twice the flour and silently double what
    twenty rusks cost."""
    assert batches_for(TRAY, D("20")) == D("0.5000")


def test_more_than_one_batch():
    assert batches_for(TRAY, D("100")) == D("2.5000")


def test_a_recipe_that_produces_nothing_is_refused():
    with pytest.raises(ValueError, match="produce something"):
        batches_for(D("0"), D("10"))


# ── the cost ───────────────────────────────────────────────────────
def test_materials_add_up_for_a_whole_batch():
    costing = cost_run(RUSKS, output_qty=TRAY, making=D("40"))
    # 2×120 + 1×150 + 0.5×900 = 240 + 150 + 450
    assert costing.material_cost == D("840.00")


def test_a_half_batch_uses_half_the_materials():
    costing = cost_run(RUSKS, output_qty=TRAY, making=D("20"))
    assert costing.material_cost == D("420.00")


def test_labour_scales_with_batches_not_with_the_calendar():
    """Half a batch of biscuits does not take a whole day's wages."""
    full = cost_run(RUSKS, output_qty=TRAY, making=D("40"), labour_cost=D("300"))
    half = cost_run(RUSKS, output_qty=TRAY, making=D("20"), labour_cost=D("300"))

    assert full.labour_cost == D("300.00")
    assert half.labour_cost == D("150.00")


def test_wastage_is_taken_on_the_materials_not_the_labour():
    """The wages are paid whether the flour burns or not."""
    costing = cost_run(
        RUSKS, output_qty=TRAY, making=D("40"),
        labour_cost=D("300"), wastage_percent=D("5"),
    )
    assert costing.wastage_cost == D("42.00")   # 5% of 840, not of 1140


def test_the_total_is_the_sum_of_its_parts():
    costing = cost_run(
        RUSKS, output_qty=TRAY, making=D("40"),
        labour_cost=D("300"), overhead_cost=D("100"), wastage_percent=D("5"),
    )
    assert costing.total_cost == (
        costing.material_cost
        + costing.labour_cost
        + costing.overhead_cost
        + costing.wastage_cost
    )
    assert costing.total_cost == D("1282.00")


def test_the_unit_cost_is_the_total_divided_by_what_was_made():
    costing = cost_run(
        RUSKS, output_qty=TRAY, making=D("40"),
        labour_cost=D("300"), overhead_cost=D("100"), wastage_percent=D("5"),
    )
    assert costing.unit_cost == D("32.05")


def test_a_recipe_with_no_extras_costs_only_its_materials():
    costing = cost_run(RUSKS, output_qty=TRAY, making=D("40"))
    assert costing.total_cost == costing.material_cost
    assert costing.unit_cost == D("21.00")


def test_making_nothing_is_refused():
    with pytest.raises(ValueError, match="how many to make"):
        cost_run(RUSKS, output_qty=TRAY, making=D("0"))


def test_a_recipe_with_no_components_still_costs_its_labour():
    """A service-like job — assembly, packing — has no materials of its own."""
    costing = cost_run([], output_qty=D("10"), making=D("10"), labour_cost=D("500"))
    assert costing.material_cost == D("0.00")
    assert costing.total_cost == D("500.00")
    assert costing.unit_cost == D("50.00")


# ── what is needed and what is there ───────────────────────────────
def test_the_requirement_lists_every_material_and_its_share():
    costing = cost_run(RUSKS, output_qty=TRAY, making=D("40"))
    flour = next(r for r in costing.requirements if r.item_id == "flour")

    assert flour.needed == D("2.0000")
    assert flour.rate == D("120.00")
    assert flour.value == D("240.00")


def test_enough_materials_means_no_shortages():
    costing = cost_run(RUSKS, output_qty=TRAY, making=D("40"))
    assert costing.shortages == []


def test_a_short_material_is_named_with_how_much_is_missing():
    costing = cost_run(RUSKS, output_qty=TRAY, making=D("2000"))
    short = {row.item_id: row for row in costing.shortages}

    assert "sugar" in short
    assert short["sugar"].needed == D("50.0000")
    assert short["sugar"].shortfall == D("30.0000")


def test_a_material_with_unknown_stock_is_never_reported_short():
    """Not knowing is not the same as not having, and blocking a run on a
    figure nobody has entered would stop the shop working."""
    unknown = [Component("x", "Mystery", D("1"), D("10"), available=None)]
    costing = cost_run(unknown, output_qty=D("1"), making=D("100"))
    assert costing.shortages == []


# ── how many could be made ─────────────────────────────────────────
def test_the_scarcest_material_decides_how_many_can_be_made():
    """The number a shopkeeper is actually asking for: not 'have I got flour'
    but 'how many trays can I get out of today'."""
    # flour 50/2 = 25 batches, sugar 20/1 = 20, ghee 6/0.5 = 12 → 12 batches.
    assert max_producible(RUSKS, TRAY) == D("480.0000")


def test_no_materials_at_all_means_nothing_can_be_made():
    empty = [Component("flour", "Flour", D("2"), D("120"), available=D("0"))]
    assert max_producible(empty, TRAY) == D("0.0000")


def test_a_recipe_with_nothing_measurable_produces_no_estimate():
    assert max_producible([], TRAY) == D("0")
    assert max_producible(RUSKS, D("0")) == D("0")
