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


# ── selling a particular piece ─────────────────────────────────────
# Registering a serial says "this piece exists", not "one more arrived" — the
# stock came in on the purchase. So these start from an item that has stock and
# serials for it, which is what a real shop has after a delivery.
async def _stocked(client, name: str, serials: list[str]) -> dict:
    response = await client.post(
        "/items",
        json={
            "name": name, "sale_price": 62000, "purchase_price": 55000,
            "unit_label": "Pcs", "track_serial": True,
            "opening_stock": len(serials),
        },
    )
    assert response.status_code == 201, response.text
    item = response.json()

    added = await client.post(
        "/items/serials", json={"item_id": item["id"], "serials": serials}
    )
    assert added.status_code == 201, added.text
    return item


async def _sell(client, shop, item: dict, serials: list[str], rate: int = 62000):
    return await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [
                {
                    "item_id": item["id"],
                    "qty": len(serials),
                    "rate": rate,
                    "tax_rate": 0,
                    "serial_numbers": serials,
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_selling_a_handset_marks_that_handset_sold(shop):
    client = shop["client"]
    item = await _stocked(client, "Redmi 13", ["R-01", "R-02"])

    sold = await _sell(client, shop, item, ["R-01"])
    assert sold.status_code == 201, sold.text

    found = (await client.get("/items/serials/lookup/R-01")).json()
    assert found["serial"]["status"] == "sold"

    # The other one is untouched — a bill takes the pieces named on it, not the
    # first of everything on the shelf.
    other = (await client.get("/items/serials/lookup/R-02")).json()
    assert other["serial"]["status"] == "in_stock"


@pytest.mark.asyncio
async def test_the_same_handset_cannot_go_out_twice(shop):
    """The whole reason a mobile shop buys this: being told at the counter that
    the phone in their hand has already gone out the door."""
    client = shop["client"]
    # Two handsets on the shelf, so stock is not what stops the second sale —
    # the shopkeeper has another one to sell, they just scanned the wrong box.
    item = await _stocked(client, "Vivo Y17", ["V-01", "V-02"])

    first = await _sell(client, shop, item, ["V-01"])
    assert first.status_code == 201, first.text

    again = await _sell(client, shop, item, ["V-01"])
    assert again.status_code == 422, again.text
    assert "V-01" in again.text


@pytest.mark.asyncio
async def test_a_serial_the_shop_does_not_have_is_refused(shop):
    client = shop["client"]
    item = await _stocked(client, "Oppo A18", ["O-01"])

    response = await _sell(client, shop, item, ["O-99"])
    assert response.status_code == 422, response.text
    assert "O-99" in response.text


@pytest.mark.asyncio
async def test_cancelling_the_bill_puts_the_handset_back_on_the_shelf(shop):
    """Left marked sold it would be stock the shop owns and cannot shift."""
    client = shop["client"]
    item = await _stocked(client, "Infinix Hot 40", ["I-01"])

    sold = await _sell(client, shop, item, ["I-01"])
    bill = sold.json()

    cancelled = await client.post(
        f"/vouchers/{bill['id']}/cancel", json={"reason": "Customer changed mind"}
    )
    assert cancelled.status_code == 200, cancelled.text

    back = (await client.get("/items/serials/lookup/I-01")).json()
    assert back["serial"]["status"] == "in_stock"

    # And it can go out again, to somebody else.
    resold = await _sell(client, shop, item, ["I-01"])
    assert resold.status_code == 201, resold.text


@pytest.mark.asyncio
async def test_the_bill_remembers_which_pieces_went_out(shop):
    client = shop["client"]
    item = await _stocked(client, "Tecno Spark", ["T-01", "T-02"])

    bill = (await _sell(client, shop, item, ["T-01", "T-02"])).json()
    line = (await client.get(f"/vouchers/{bill['id']}")).json()["lines"][0]
    assert sorted(line["serial_numbers"]) == ["T-01", "T-02"]
