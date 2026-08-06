"""Serial / IMEI tracking.

A serial is a physical object, not a quantity: it is here or it is not, and it
can only be sold once. A mobile shop buys this feature to be told, at the
counter, that the handset in their hand has already gone out the door.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest


async def _serialised_item(client, name: str = "Samsung A15") -> dict:
    response = await client.post(
        "/items",
        json={
            "name": name, "sale_price": 62000, "purchase_price": 55000,
            "unit_label": "Pcs", "track_serial": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_registering_units_reports_how_many_are_now_available(shop):
    client = shop["client"]
    item = await _serialised_item(client)

    added = await client.post(
        "/items/serials",
        json={"item_id": item["id"], "serials": ["IMEI-001", "IMEI-002", "IMEI-003"]},
    )
    assert added.status_code == 201, added.text
    body = added.json()

    assert body["added_count"] == 3
    assert body["available_count"] == 3
    assert body["duplicates"] == []


@pytest.mark.asyncio
async def test_one_duplicate_does_not_lose_the_rest_of_the_scan(shop):
    """A shopkeeper scanning thirty handsets must not be sent back to the start
    because the ninth was already on the books."""
    client = shop["client"]
    item = await _serialised_item(client, "Infinix Hot 40")

    await client.post("/items/serials", json={"item_id": item["id"], "serials": ["A-1"]})

    second = await client.post(
        "/items/serials",
        json={"item_id": item["id"], "serials": ["A-1", "A-2", "A-3"]},
    )
    assert second.status_code == 201, second.text
    body = second.json()

    assert body["added_count"] == 2
    assert body["duplicates"] == ["A-1"]
    assert body["available_count"] == 3


@pytest.mark.asyncio
async def test_the_same_serial_repeated_in_one_scan_is_only_taken_once(shop):
    client = shop["client"]
    item = await _serialised_item(client, "Vivo Y17")

    added = await client.post(
        "/items/serials",
        json={"item_id": item["id"], "serials": ["V-9", "v-9", " V-9 "]},
    )
    assert added.json()["added_count"] == 1


@pytest.mark.asyncio
async def test_a_serial_can_be_looked_up_at_the_counter(shop):
    client = shop["client"]
    item = await _serialised_item(client, "Oppo A78")

    await client.post(
        "/items/serials",
        json={
            "item_id": item["id"], "serials": ["OP-555"],
            "purchase_price": 48000, "warranty_months": 12,
        },
    )

    found = await client.get("/items/serials/lookup/op-555")
    assert found.status_code == 200, found.text
    body = found.json()

    assert body["item_name"] == "Oppo A78"
    assert body["serial"]["status"] == "in_stock"
    assert body["serial"]["in_warranty"] is True
    assert Decimal(body["serial"]["purchase_price"]) == Decimal("48000")
    assert body["serial"]["warranty_until"] > date.today().isoformat()


@pytest.mark.asyncio
async def test_an_unknown_serial_says_so(shop):
    client = shop["client"]
    missing = await client.get("/items/serials/lookup/NEVER-EXISTED")
    assert missing.status_code == 404, missing.text


@pytest.mark.asyncio
async def test_units_can_be_listed_and_filtered_by_state(shop):
    client = shop["client"]
    item = await _serialised_item(client, "Tecno Spark 20")

    await client.post(
        "/items/serials", json={"item_id": item["id"], "serials": ["T-1", "T-2", "T-3"]}
    )

    everything = (await client.get(f"/items/{item['id']}/serials")).json()
    assert [s["serial_number"] for s in everything] == ["T-1", "T-2", "T-3"]

    sold = (
        await client.get(f"/items/{item['id']}/serials", params={"serial_status": "sold"})
    ).json()
    assert sold == []


@pytest.mark.asyncio
async def test_warranty_is_dated_from_when_the_unit_was_received(shop):
    client = shop["client"]
    item = await _serialised_item(client, "Realme C55")

    await client.post(
        "/items/serials",
        json={
            "item_id": item["id"], "serials": ["R-1"],
            "warranty_months": 6, "received_on": "2020-01-01",
        },
    )

    body = (await client.get("/items/serials/lookup/R-1")).json()
    assert body["serial"]["warranty_until"].startswith("2020-")
    assert body["serial"]["in_warranty"] is False, "a 2020 warranty has long run out"


@pytest.mark.asyncio
async def test_a_serial_is_unique_across_the_whole_shop_not_just_one_item(shop):
    """Two different handsets cannot share an IMEI, so neither can two items."""
    client = shop["client"]
    first = await _serialised_item(client, "Xiaomi Redmi 13")
    second = await _serialised_item(client, "Xiaomi Redmi 14")

    await client.post("/items/serials", json={"item_id": first["id"], "serials": ["SHARED-1"]})
    clash = await client.post(
        "/items/serials", json={"item_id": second["id"], "serials": ["SHARED-1"]}
    )

    assert clash.status_code == 201, clash.text
    assert clash.json()["added_count"] == 0
    assert clash.json()["duplicates"] == ["SHARED-1"]


@pytest.mark.asyncio
async def test_an_empty_list_of_serials_is_refused(shop):
    client = shop["client"]
    item = await _serialised_item(client, "Nokia 105")

    empty = await client.post("/items/serials", json={"item_id": item["id"], "serials": []})
    assert empty.status_code == 422, empty.text
