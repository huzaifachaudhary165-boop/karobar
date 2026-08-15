"""How a shop measures what it sells.

The list used to be twelve, written into the app, all metric or retail. A
wholesaler could not enter a single real line with it: cloth is sold by the
thaan, grain by the maund, timber by the cubic foot. A unit a business cannot
name is a business that cannot use the app.

No list will ever cover every trade, so the part that matters most is that a
shop can add its own — and, once added, fix it.
"""

from __future__ import annotations

import pytest


async def _units(client) -> list[dict]:
    response = await client.get("/items/units")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_a_new_shop_can_measure_the_things_its_trade_measures(shop):
    shorts = {u["short_name"] for u in await _units(shop["client"])}

    # Not an arbitrary sample: each of these is a unit a Pakistani wholesaler
    # bills in every day and none of which existed before.
    for unit in ("Thaan", "Maund", "Seer", "Cft", "Sqft", "Bori", "Gaz", "Ton"):
        assert unit in shorts, f"{unit} missing — that trade cannot bill"


@pytest.mark.asyncio
async def test_a_shop_can_add_a_unit_nobody_thought_of(shop):
    response = await shop["client"].post(
        "/items/units",
        json={"name": "Katta", "short_name": "Katta", "allow_decimal": False},
    )
    assert response.status_code == 201, response.text
    assert response.json()["short_name"] == "Katta"
    assert response.json()["allow_decimal"] is False

    assert "Katta" in {u["short_name"] for u in await _units(shop["client"])}


@pytest.mark.asyncio
async def test_the_same_unit_twice_is_refused(shop):
    """The unit list is a dropdown read at speed while adding an item. Two
    entries reading "Kg" is a choice with no right answer, and whichever is
    picked, half the shop's stock ends up under the other."""
    client = shop["client"]
    await client.post("/items/units", json={"name": "Crate", "short_name": "Crate"})

    again = await client.post(
        "/items/units", json={"name": "Crate Large", "short_name": "crate"}
    )
    assert again.status_code == 422, again.text
    assert "Crate" in again.text


@pytest.mark.asyncio
async def test_a_unit_typed_wrong_can_be_fixed(shop):
    client = shop["client"]
    made = (
        await client.post("/items/units", json={"name": "Thann", "short_name": "Thann"})
    ).json()

    fixed = await client.patch(
        f"/items/units/{made['id']}", json={"name": "Thaan Roll", "short_name": "ThaanR"}
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["short_name"] == "ThaanR"


@pytest.mark.asyncio
async def test_renaming_a_unit_carries_the_items_measured_in_it(shop):
    """An item stores its unit as text.

    Renaming without moving the items would leave them measured in something
    the shop no longer has, and the dropdown would silently reset them the next
    time anybody opened the form.
    """
    client = shop["client"]
    made = (
        await client.post("/items/units", json={"name": "Peice", "short_name": "Peice"})
    ).json()

    item = (
        await client.post(
            "/items",
            json={"name": "Bolt", "sale_price": 20, "unit_label": "Peice"},
        )
    ).json()

    await client.patch(
        f"/items/units/{made['id']}", json={"name": "Piece", "short_name": "Piece"}
    )

    after = (await client.get(f"/items/{item['id']}")).json()
    assert after["unit_label"] == "Piece"


@pytest.mark.asyncio
async def test_a_unit_can_be_removed_while_nothing_uses_it(shop):
    client = shop["client"]
    made = (
        await client.post("/items/units", json={"name": "Spare", "short_name": "Spare"})
    ).json()

    gone = await client.delete(f"/items/units/{made['id']}")
    assert gone.status_code == 200, gone.text
    assert "Spare" not in {u["short_name"] for u in await _units(client)}


@pytest.mark.asyncio
async def test_a_unit_in_use_is_not_removed(shop):
    """A unit is not a label on the item — it is how the quantity is read.
    Taking one away while stock is counted in it leaves figures nobody can
    interpret."""
    client = shop["client"]
    made = (
        await client.post("/items/units", json={"name": "Katta", "short_name": "Katta"})
    ).json()
    await client.post(
        "/items", json={"name": "Wheat", "sale_price": 4000, "unit_label": "Katta"}
    )

    refused = await client.delete(f"/items/units/{made['id']}")
    assert refused.status_code == 422, refused.text
    # Says what to do instead, not just that it failed.
    assert "rename" in refused.text.lower()


@pytest.mark.asyncio
async def test_renaming_onto_a_unit_that_already_exists_is_refused(shop):
    client = shop["client"]
    made = (
        await client.post("/items/units", json={"name": "Tray", "short_name": "Tray"})
    ).json()

    clash = await client.patch(f"/items/units/{made['id']}", json={"short_name": "Kg"})
    assert clash.status_code == 422, clash.text
