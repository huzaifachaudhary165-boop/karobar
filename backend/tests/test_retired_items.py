"""Retiring an item that cannot be deleted.

An item that appears on old bills cannot be deleted without taking the history
with it, so the app tells the shopkeeper to mark it inactive instead. That
advice is only worth giving if retiring actually stops the item turning up.
"""

from __future__ import annotations

import pytest


async def _item(client, name: str) -> dict:
    response = await client.post(
        "/items",
        json={
            "name": name, "sale_price": 100, "purchase_price": 60,
            "unit_label": "Pcs", "opening_stock": 5,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _retire(client, item: dict):
    response = await client.patch(f"/items/{item['id']}", json={"is_active": False})
    assert response.status_code == 200, response.text
    return response.json()


def _names(payload) -> list[str]:
    rows = payload["items"] if isinstance(payload, dict) else payload
    return [row["name"] for row in rows]


@pytest.mark.asyncio
async def test_a_retired_item_is_off_the_list_the_app_asks_for(shop):
    client = shop["client"]
    item = await _item(client, "Discontinued Soap")
    await _retire(client, item)

    live = _names((await client.get("/items", params={"is_active": True})).json())
    assert "Discontinued Soap" not in live


@pytest.mark.asyncio
async def test_it_can_still_be_found_when_looked_for(shop):
    """A shop that cannot see what it put away cannot bring it back when the
    supplier starts stocking it again."""
    client = shop["client"]
    item = await _item(client, "Seasonal Mango Drink")
    await _retire(client, item)

    retired = _names((await client.get("/items", params={"is_active": False})).json())
    assert "Seasonal Mango Drink" in retired


@pytest.mark.asyncio
async def test_bringing_it_back_puts_it_on_the_list_again(shop):
    client = shop["client"]
    item = await _item(client, "Winter Cream")
    await _retire(client, item)

    restored = await client.patch(f"/items/{item['id']}", json={"is_active": True})
    assert restored.status_code == 200, restored.text

    live = _names((await client.get("/items", params={"is_active": True})).json())
    assert "Winter Cream" in live


@pytest.mark.asyncio
async def test_fuzzy_search_does_not_offer_a_retired_item(shop):
    """Search feeds the AI and the bill-photo reader. Offering a retired item
    there would put it back on a bill by the back door."""
    client = shop["client"]
    item = await _item(client, "Old Brand Tea")
    before = (await client.get("/items/search", params={"q": "Old Brand"})).json()
    assert "Old Brand Tea" in _names(before)

    await _retire(client, item)

    after = (await client.get("/items/search", params={"q": "Old Brand"})).json()
    assert "Old Brand Tea" not in _names(after)


@pytest.mark.asyncio
async def test_retiring_does_not_touch_the_bills_it_is_already_on(shop):
    """The history is the reason it could not be deleted. Retiring must not
    quietly do what deleting was refused for."""
    client = shop["client"]
    item = await _item(client, "Sold Once Then Retired")

    bill = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": item["id"], "qty": 1, "rate": 100, "tax_rate": 0}],
        },
    )
    assert bill.status_code == 201, bill.text

    await _retire(client, item)

    after = (await client.get(f"/vouchers/{bill.json()['id']}")).json()
    assert after["lines"][0]["item_name"] == "Sold Once Then Retired"
    assert float(after["total"]) == 100.0


@pytest.mark.asyncio
async def test_an_item_whose_only_bill_was_deleted_can_be_deleted_too(shop):
    """The count used to include every line ever written.

    So a shopkeeper who raised a bill by mistake, deleted it, and then tried to
    tidy up the item was told it appears on a transaction — one they could no
    longer find anywhere in the app. There was no way to win that argument and
    no way to remove the item.
    """
    client = shop["client"]
    item = await _item(client, "Raised By Mistake")

    bill = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": item["id"], "qty": 1, "rate": 100, "tax_rate": 0}],
        },
    )
    assert bill.status_code == 201, bill.text

    refused = await client.delete(f"/items/{item['id']}")
    assert refused.status_code == 422, "a live bill should still protect it"

    gone = await client.delete(f"/vouchers/{bill.json()['id']}")
    assert gone.status_code == 200, gone.text

    now = await client.delete(f"/items/{item['id']}")
    assert now.status_code == 200, now.text


@pytest.mark.asyncio
async def test_a_cancelled_bill_still_protects_the_item(shop):
    """Cancelling is not deleting.

    A cancelled bill stays in the books — the customer has a copy and the
    numbering is unbroken — so the item on it has to stay too.
    """
    client = shop["client"]
    item = await _item(client, "Sold Then Cancelled")

    bill = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": item["id"], "qty": 1, "rate": 100, "tax_rate": 0}],
        },
    )
    await client.post(f"/vouchers/{bill.json()['id']}/cancel", json={"reason": "Returned"})

    refused = await client.delete(f"/items/{item['id']}")
    assert refused.status_code == 422, refused.text
