"""Multi-location stock: locations, transfers, and the sums that must hold.

The one invariant worth defending is that per-location quantities always add up
to the item's total. A shop that cannot trust that will stop entering transfers,
and then the feature is worse than not having it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


async def _godowns(client) -> list[dict]:
    response = await client.get("/items/godowns")
    assert response.status_code == 200, response.text
    return response.json()


async def _stock_of(client, item_id: str) -> Decimal:
    response = await client.get(f"/items/{item_id}")
    assert response.status_code == 200, response.text
    return Decimal(response.json()["stock_qty"])


@pytest.mark.asyncio
async def test_the_first_location_becomes_the_default_even_if_not_asked_for(shop):
    client = shop["client"]

    created = await client.post("/items/godowns", json={"name": "Main Store"})
    assert created.status_code == 201, created.text
    assert created.json()["is_default"] is True, "a shop's only location must be its default"


@pytest.mark.asyncio
async def test_existing_stock_lands_in_the_first_location(shop):
    """The goods were always somewhere. Turning on locations must not hide them."""
    client = shop["client"]
    sugar_qty = await _stock_of(client, shop["sugar"]["id"])

    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()

    held = await client.get(f"/items/godowns/{main['id']}/stock")
    assert held.status_code == 200, held.text
    rows = {r["item_id"]: Decimal(r["qty"]) for r in held.json()}

    assert rows[shop["sugar"]["id"]] == sugar_qty
    assert sugar_qty > 0, "the fixture is supposed to open with stock on hand"


@pytest.mark.asyncio
async def test_a_transfer_moves_stock_without_changing_the_total(shop):
    client = shop["client"]
    item_id = shop["sugar"]["id"]

    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()
    branch = (await client.post("/items/godowns", json={"name": "Branch Shop"})).json()

    before = await _stock_of(client, item_id)

    moved = await client.post(
        "/items/stock/transfer",
        json={
            "item_id": item_id,
            "from_godown_id": main["id"],
            "to_godown_id": branch["id"],
            "qty": 30,
        },
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()

    assert Decimal(body["from_qty_after"]) == before - 30
    assert Decimal(body["to_qty_after"]) == Decimal("30")
    assert await _stock_of(client, item_id) == before, "a transfer is not a sale"


@pytest.mark.asyncio
async def test_locations_always_add_up_to_the_item_total(shop):
    client = shop["client"]
    item_id = shop["sugar"]["id"]

    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()
    branch = (await client.post("/items/godowns", json={"name": "Branch Shop"})).json()

    await client.post(
        "/items/stock/transfer",
        json={
            "item_id": item_id, "from_godown_id": main["id"],
            "to_godown_id": branch["id"], "qty": 40,
        },
    )
    # And a purchase afterwards, which lands on the default location.
    await client.post(
        "/items/stock/adjust",
        json={"item_id": item_id, "qty": 25, "reason": "Fresh delivery"},
    )

    split = (await client.get(f"/items/{item_id}/godowns")).json()
    assert sum(Decimal(row["qty"]) for row in split) == await _stock_of(client, item_id)


@pytest.mark.asyncio
async def test_a_transfer_cannot_take_more_than_the_source_holds(shop):
    client = shop["client"]
    item_id = shop["sugar"]["id"]

    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()
    branch = (await client.post("/items/godowns", json={"name": "Branch Shop"})).json()

    refused = await client.post(
        "/items/stock/transfer",
        json={
            "item_id": item_id, "from_godown_id": main["id"],
            "to_godown_id": branch["id"], "qty": 99999,
        },
    )
    assert refused.status_code == 422, refused.text
    assert "Main Store" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_transfer_does_not_move_the_average_cost(shop):
    """Otherwise a shopkeeper could rewrite their own cost of sales by carrying
    a carton into the next room."""
    client = shop["client"]
    item_id = shop["sugar"]["id"]

    before = Decimal((await client.get(f"/items/{item_id}")).json()["avg_cost"])

    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()
    branch = (await client.post("/items/godowns", json={"name": "Branch Shop"})).json()
    await client.post(
        "/items/stock/transfer",
        json={
            "item_id": item_id, "from_godown_id": main["id"],
            "to_godown_id": branch["id"], "qty": 50,
        },
    )

    after = Decimal((await client.get(f"/items/{item_id}")).json()["avg_cost"])
    assert after == before


@pytest.mark.asyncio
async def test_transferring_to_the_same_place_is_refused(shop):
    client = shop["client"]
    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()

    same = await client.post(
        "/items/stock/transfer",
        json={
            "item_id": shop["sugar"]["id"], "from_godown_id": main["id"],
            "to_godown_id": main["id"], "qty": 5,
        },
    )
    assert same.status_code == 422


@pytest.mark.asyncio
async def test_a_location_holding_stock_cannot_be_deleted(shop):
    client = shop["client"]
    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()
    branch = (await client.post("/items/godowns", json={"name": "Branch Shop"})).json()

    await client.post(
        "/items/stock/transfer",
        json={
            "item_id": shop["sugar"]["id"], "from_godown_id": main["id"],
            "to_godown_id": branch["id"], "qty": 10,
        },
    )

    refused = await client.delete(f"/items/godowns/{branch['id']}")
    assert refused.status_code == 422, refused.text
    assert "still holds stock" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_an_emptied_location_can_be_deleted(shop):
    client = shop["client"]
    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()
    branch = (await client.post("/items/godowns", json={"name": "Branch Shop"})).json()

    for source, target in ((main["id"], branch["id"]), (branch["id"], main["id"])):
        sent = await client.post(
            "/items/stock/transfer",
            json={
                "item_id": shop["sugar"]["id"], "from_godown_id": source,
                "to_godown_id": target, "qty": 10,
            },
        )
        assert sent.status_code == 200, sent.text

    removed = await client.delete(f"/items/godowns/{branch['id']}")
    assert removed.status_code == 200, removed.text
    assert branch["id"] not in {g["id"] for g in await _godowns(client)}


@pytest.mark.asyncio
async def test_two_locations_cannot_share_a_name(shop):
    client = shop["client"]
    await client.post("/items/godowns", json={"name": "Main Store"})

    clash = await client.post("/items/godowns", json={"name": "main store"})
    assert clash.status_code == 409, clash.text


@pytest.mark.asyncio
async def test_making_one_location_default_demotes_the_other(shop):
    client = shop["client"]
    main = (await client.post("/items/godowns", json={"name": "Main Store"})).json()
    branch = (await client.post("/items/godowns", json={"name": "Branch Shop"})).json()
    assert branch["is_default"] is False

    promoted = await client.patch(f"/items/godowns/{branch['id']}", json={"is_default": True})
    assert promoted.status_code == 200, promoted.text

    by_id = {g["id"]: g for g in await _godowns(client)}
    assert by_id[branch["id"]]["is_default"] is True
    assert by_id[main["id"]]["is_default"] is False, "a shop can only have one default"
