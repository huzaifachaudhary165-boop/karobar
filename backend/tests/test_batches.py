"""Batch and expiry tracking.

A pharmacy buys batch tracking for one reason: to never sell an expired strip.
Everything here defends that, and the arithmetic that has to hold around it.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest


async def _batched_item(client, name: str = "Panadol 500mg") -> dict:
    response = await client.post(
        "/items",
        json={
            "name": name, "sale_price": 250, "purchase_price": 180,
            "unit_label": "Strip", "track_batches": True, "track_expiry": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _batch(client, item_id: str, number: str, *, days: int | None, qty: int) -> dict:
    response = await client.post(
        "/items/batches",
        json={
            "item_id": item_id,
            "batch_number": number,
            "qty": qty,
            "expiry_date": (date.today() + timedelta(days=days)).isoformat() if days is not None else None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_a_batch_opening_quantity_reaches_the_item_stock(shop):
    client = shop["client"]
    item = await _batched_item(client)

    await _batch(client, item["id"], "B-001", days=180, qty=40)

    after = (await client.get(f"/items/{item['id']}")).json()
    assert Decimal(after["stock_qty"]) == Decimal("40"), "a batch is stock, not a label"


@pytest.mark.asyncio
async def test_batches_are_listed_earliest_expiry_first(shop):
    client = shop["client"]
    item = await _batched_item(client, "Amoxil 250mg")

    await _batch(client, item["id"], "LATE", days=300, qty=10)
    await _batch(client, item["id"], "SOON", days=20, qty=10)
    await _batch(client, item["id"], "MID", days=120, qty=10)

    listed = (await client.get(f"/items/{item['id']}/batches")).json()
    assert [b["batch_number"] for b in listed] == ["SOON", "MID", "LATE"]


@pytest.mark.asyncio
async def test_selling_pulls_from_the_batch_that_expires_first(shop):
    client = shop["client"]
    item = await _batched_item(client, "Brufen 400mg")

    await _batch(client, item["id"], "LATE", days=300, qty=50)
    await _batch(client, item["id"], "SOON", days=15, qty=30)

    plan = (await client.get(f"/items/{item['id']}/batches/allocate", params={"qty": 40})).json()

    assert [(p["batch_number"], Decimal(p["qty"])) for p in plan] == [
        ("SOON", Decimal("30")),
        ("LATE", Decimal("10")),
    ], "the stock closest to expiry has to move first"


@pytest.mark.asyncio
async def test_an_expired_batch_is_never_offered_for_sale(shop):
    client = shop["client"]
    item = await _batched_item(client, "Augmentin 625mg")

    await _batch(client, item["id"], "EXPIRED", days=-5, qty=100)
    await _batch(client, item["id"], "GOOD", days=90, qty=20)

    plan = (await client.get(f"/items/{item['id']}/batches/allocate", params={"qty": 20})).json()

    assert [p["batch_number"] for p in plan] == ["GOOD"]


@pytest.mark.asyncio
async def test_asking_for_more_than_the_unexpired_stock_is_refused(shop):
    """The expired hundred are on the shelf, but they are not sellable stock."""
    client = shop["client"]
    item = await _batched_item(client, "Calpol 120mg")

    await _batch(client, item["id"], "EXPIRED", days=-1, qty=100)
    await _batch(client, item["id"], "GOOD", days=60, qty=5)

    refused = await client.get(f"/items/{item['id']}/batches/allocate", params={"qty": 20})
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "insufficient_batch_stock"


@pytest.mark.asyncio
async def test_expiring_soon_reports_what_needs_acting_on(shop):
    client = shop["client"]
    item = await _batched_item(client, "Ventolin Inhaler")

    await _batch(client, item["id"], "NEXT-WEEK", days=7, qty=12)
    await _batch(client, item["id"], "NEXT-YEAR", days=400, qty=12)

    soon = (await client.get("/items/batches/expiring", params={"within_days": 30})).json()
    numbers = {row["batch"]["batch_number"] for row in soon}

    assert "NEXT-WEEK" in numbers
    assert "NEXT-YEAR" not in numbers

    week = next(r for r in soon if r["batch"]["batch_number"] == "NEXT-WEEK")
    assert week["days_to_expiry"] == 7
    assert week["item_name"] == "Ventolin Inhaler"
    assert Decimal(week["value"]) > 0, "a shop needs to know what the loss would be"


@pytest.mark.asyncio
async def test_already_expired_stock_shows_up_too(shop):
    client = shop["client"]
    item = await _batched_item(client, "Disprin")

    await _batch(client, item["id"], "GONE-OFF", days=-30, qty=8)

    listed = (await client.get("/items/batches/expiring")).json()
    row = next(r for r in listed if r["batch"]["batch_number"] == "GONE-OFF")

    assert row["batch"]["is_expired"] is True
    assert row["days_to_expiry"] == -30


@pytest.mark.asyncio
async def test_an_expiry_before_manufacture_is_refused(shop):
    client = shop["client"]
    item = await _batched_item(client, "Flagyl 400mg")

    backwards = await client.post(
        "/items/batches",
        json={
            "item_id": item["id"],
            "batch_number": "IMPOSSIBLE",
            "manufacture_date": date.today().isoformat(),
            "expiry_date": (date.today() - timedelta(days=10)).isoformat(),
        },
    )
    assert backwards.status_code == 422, backwards.text


@pytest.mark.asyncio
async def test_the_same_batch_number_cannot_be_used_twice_for_one_item(shop):
    client = shop["client"]
    item = await _batched_item(client, "Zyrtec")

    await _batch(client, item["id"], "B-77", days=100, qty=5)
    clash = await client.post(
        "/items/batches", json={"item_id": item["id"], "batch_number": "b-77"}
    )
    assert clash.status_code == 409, clash.text


@pytest.mark.asyncio
async def test_a_batch_holding_stock_cannot_be_deleted(shop):
    client = shop["client"]
    item = await _batched_item(client, "Panadol Extra")
    batch = await _batch(client, item["id"], "B-500", days=200, qty=25)

    refused = await client.delete(f"/items/batches/{batch['id']}")
    assert refused.status_code == 422, refused.text
    assert "still holds" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_batch_quantity_cannot_be_edited_behind_the_ledger(shop):
    """Stock only moves through the ledger. An edit here would silently
    desynchronise the item total from its own history, so the field is not
    accepted at all rather than accepted and ignored."""
    client = shop["client"]
    item = await _batched_item(client, "Septran")
    batch = await _batch(client, item["id"], "B-900", days=200, qty=10)

    refused = await client.patch(f"/items/batches/{batch['id']}", json={"qty": 9999})
    assert refused.status_code == 422, refused.text
    assert "qty" in refused.json()["error"]["details"]["fields"]

    assert Decimal((await client.get(f"/items/{item['id']}")).json()["stock_qty"]) == Decimal("10")


@pytest.mark.asyncio
async def test_the_editable_parts_of_a_batch_still_change(shop):
    client = shop["client"]
    item = await _batched_item(client, "Ciproxin")
    batch = await _batch(client, item["id"], "B-901", days=200, qty=10)

    edited = await client.patch(
        f"/items/batches/{batch['id']}",
        json={"mrp": 300, "expiry_date": (date.today() + timedelta(days=45)).isoformat()},
    )
    assert edited.status_code == 200, edited.text
    assert Decimal(edited.json()["mrp"]) == Decimal("300")
    assert edited.json()["days_to_expiry"] == 45
