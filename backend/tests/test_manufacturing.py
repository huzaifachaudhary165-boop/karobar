"""Making things, over the API.

The unit cost a run records becomes the finished item's cost of sales. Getting
it wrong makes every margin the shop reads afterwards wrong by the same amount,
and nothing on any screen looks unusual.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


async def _material(client, name: str, *, stock: int, cost: int) -> dict:
    response = await client.post(
        "/items",
        json={
            "name": name,
            "purchase_price": cost,
            "sale_price": cost * 2,
            "opening_stock": stock,
            "opening_stock_value": stock * cost,
            "unit_label": "Kg",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _finished(client, name: str) -> dict:
    response = await client.post(
        "/items", json={"name": name, "sale_price": 100, "unit_label": "Pcs"}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _kitchen(shop) -> dict:
    """Forty rusks from one tray: flour, sugar, ghee."""
    client = shop["client"]
    flour = await _material(client, "Flour", stock=50, cost=120)
    sugar = await _material(client, "Sugar (raw)", stock=20, cost=150)
    ghee = await _material(client, "Ghee", stock=6, cost=900)
    rusk = await _finished(client, "Rusk")

    recipe = await client.post(
        "/manufacturing/recipes",
        json={
            "name": "Rusk tray",
            "item_id": rusk["id"],
            "output_qty": 40,
            "labour_cost": 300,
            "overhead_cost": 100,
            "wastage_percent": 5,
            "components": [
                {"item_id": flour["id"], "qty": 2},
                {"item_id": sugar["id"], "qty": 1},
                {"item_id": ghee["id"], "qty": 0.5},
            ],
        },
    )
    assert recipe.status_code == 201, recipe.text
    return {
        "flour": flour, "sugar": sugar, "ghee": ghee,
        "rusk": rusk, "recipe": recipe.json(), "client": client,
    }


async def _stock_of(client, item_id: str) -> Decimal:
    return Decimal((await client.get(f"/items/{item_id}")).json()["stock_qty"])


# ── recipes ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_recipe_reports_what_a_batch_costs(shop):
    kitchen = await _kitchen(shop)
    recipe = kitchen["recipe"]

    # 840 materials + 42 wastage + 300 labour + 100 overhead
    assert Decimal(recipe["batch_cost"]) == Decimal("1282.00")
    assert Decimal(recipe["unit_cost"]) == Decimal("32.05")


@pytest.mark.asyncio
async def test_a_recipe_says_how_many_could_be_made_today(shop):
    """The number a shopkeeper is asking for: not 'have I got flour' but
    'how many trays can I get out of today'."""
    kitchen = await _kitchen(shop)
    # ghee is scarcest: 6 / 0.5 = 12 batches × 40
    assert Decimal(kitchen["recipe"]["can_make"]) == Decimal("480.0000")


@pytest.mark.asyncio
async def test_an_item_cannot_be_an_ingredient_in_its_own_recipe(shop):
    client = shop["client"]
    thing = await _finished(client, "Circular")

    refused = await client.post(
        "/manufacturing/recipes",
        json={
            "name": "Impossible",
            "item_id": thing["id"],
            "components": [{"item_id": thing["id"], "qty": 1}],
        },
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_the_same_material_cannot_be_listed_twice(shop):
    client = shop["client"]
    flour = await _material(client, "Flour A", stock=10, cost=100)
    bread = await _finished(client, "Bread")

    refused = await client.post(
        "/manufacturing/recipes",
        json={
            "name": "Doubled",
            "item_id": bread["id"],
            "components": [
                {"item_id": flour["id"], "qty": 1},
                {"item_id": flour["id"], "qty": 2},
            ],
        },
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_a_recipe_with_no_materials_is_refused(shop):
    client = shop["client"]
    thing = await _finished(client, "Nothing from nothing")

    refused = await client.post(
        "/manufacturing/recipes",
        json={"name": "Empty", "item_id": thing["id"], "components": []},
    )
    assert refused.status_code == 422, refused.text


# ── costing before committing ──────────────────────────────────────
@pytest.mark.asyncio
async def test_costing_a_run_before_starting_it(shop):
    kitchen = await _kitchen(shop)
    costing = (
        await kitchen["client"].get(
            f"/manufacturing/recipes/{kitchen['recipe']['id']}/costing",
            params={"qty": 20},
        )
    ).json()

    assert Decimal(costing["material_cost"]) == Decimal("420.00")
    assert Decimal(costing["labour_cost"]) == Decimal("150.00"), "half a batch, half the wages"
    assert costing["can_make_now"] is True
    assert costing["shortages"] == []


@pytest.mark.asyncio
async def test_costing_names_what_is_short_and_by_how_much(shop):
    kitchen = await _kitchen(shop)
    costing = (
        await kitchen["client"].get(
            f"/manufacturing/recipes/{kitchen['recipe']['id']}/costing",
            params={"qty": 2000},
        )
    ).json()

    assert costing["can_make_now"] is False
    short = {row["item_name"]: row for row in costing["shortages"]}
    assert "Sugar (raw)" in short
    assert Decimal(short["Sugar (raw)"]["short_by"]) == Decimal("30.0000")


# ── making it ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_run_consumes_the_materials_and_produces_the_goods(shop):
    kitchen = await _kitchen(shop)
    client = kitchen["client"]

    run = await client.post(
        "/manufacturing/runs",
        json={"bom_id": kitchen["recipe"]["id"], "qty": 40},
    )
    assert run.status_code == 201, run.text

    assert await _stock_of(client, kitchen["rusk"]["id"]) == Decimal("40.0000")
    assert await _stock_of(client, kitchen["flour"]["id"]) == Decimal("48.0000")
    assert await _stock_of(client, kitchen["sugar"]["id"]) == Decimal("19.0000")
    assert await _stock_of(client, kitchen["ghee"]["id"]) == Decimal("5.5000")


@pytest.mark.asyncio
async def test_the_finished_goods_arrive_at_what_they_cost_to_make(shop):
    """This is what keeps every margin the shop reads afterwards honest."""
    kitchen = await _kitchen(shop)
    client = kitchen["client"]

    await client.post(
        "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
    )
    rusk = (await client.get(f"/items/{kitchen['rusk']['id']}")).json()
    assert Decimal(rusk["avg_cost"]) == Decimal("32.05")


@pytest.mark.asyncio
async def test_a_run_records_what_it_used_at_the_rate_it_used_it(shop):
    kitchen = await _kitchen(shop)
    run = (
        await kitchen["client"].post(
            "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
        )
    ).json()

    used = {row["item_name"]: row for row in run["consumed"]}
    assert Decimal(used["Flour"]["qty"]) == Decimal("2.0000")
    assert Decimal(used["Flour"]["rate"]) == Decimal("120.00")
    assert Decimal(used["Flour"]["value"]) == Decimal("240.00")


@pytest.mark.asyncio
async def test_a_run_gets_its_own_number(shop):
    kitchen = await _kitchen(shop)
    run = (
        await kitchen["client"].post(
            "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
        )
    ).json()
    assert run["number"].startswith("MFG-")


@pytest.mark.asyncio
async def test_a_run_without_the_materials_is_refused_before_anything_moves(shop):
    """A run that cannot finish must not leave half the flour consumed and no
    biscuits to show."""
    kitchen = await _kitchen(shop)
    client = kitchen["client"]
    before = await _stock_of(client, kitchen["flour"]["id"])

    refused = await client.post(
        "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 2000}
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "insufficient_materials"
    assert await _stock_of(client, kitchen["flour"]["id"]) == before


@pytest.mark.asyncio
async def test_a_switched_off_recipe_cannot_be_run(shop):
    kitchen = await _kitchen(shop)
    client = kitchen["client"]
    await client.patch(
        f"/manufacturing/recipes/{kitchen['recipe']['id']}", json={"is_active": False}
    )

    refused = await client.post(
        "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
    )
    assert refused.status_code == 422, refused.text


# ── undoing ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_undoing_a_run_puts_the_materials_back(shop):
    kitchen = await _kitchen(shop)
    client = kitchen["client"]

    run = (
        await client.post(
            "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
        )
    ).json()

    undone = await client.delete(f"/manufacturing/runs/{run['id']}")
    assert undone.status_code == 200, undone.text

    assert await _stock_of(client, kitchen["flour"]["id"]) == Decimal("50.0000")
    assert await _stock_of(client, kitchen["ghee"]["id"]) == Decimal("6.0000")
    assert await _stock_of(client, kitchen["rusk"]["id"]) == Decimal("0.0000")


@pytest.mark.asyncio
async def test_a_run_whose_output_has_been_sold_cannot_be_undone(shop):
    """Putting the flour back while the biscuits are already out the door would
    invent stock that does not exist."""
    kitchen = await _kitchen(shop)
    client = kitchen["client"]

    run = (
        await client.post(
            "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
        )
    ).json()

    sold = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": kitchen["rusk"]["id"], "qty": 35, "rate": 60}],
        },
    )
    assert sold.status_code == 201, sold.text

    refused = await client.delete(f"/manufacturing/runs/{run['id']}")
    assert refused.status_code == 422, refused.text
    assert "already been sold" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_recipe_that_has_been_used_cannot_be_deleted(shop):
    kitchen = await _kitchen(shop)
    client = kitchen["client"]
    await client.post(
        "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
    )

    refused = await client.delete(f"/manufacturing/recipes/{kitchen['recipe']['id']}")
    assert refused.status_code == 422, refused.text
    assert "Switch it off" in refused.json()["error"]["message"]


# ── what was made ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_summary_adds_up_what_was_made_and_what_it_cost(shop):
    kitchen = await _kitchen(shop)
    client = kitchen["client"]

    await client.post(
        "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 40}
    )
    await client.post(
        "/manufacturing/runs", json={"bom_id": kitchen["recipe"]["id"], "qty": 20}
    )

    summary = (await client.get("/manufacturing/summary")).json()
    assert summary["runs"] == 2
    assert Decimal(summary["units_made"]) == Decimal("60.0000")
    assert Decimal(summary["total_cost"]) == Decimal("1282.00") + Decimal("641.00")
