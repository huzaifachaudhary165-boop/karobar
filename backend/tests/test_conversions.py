"""Order documents, and what each one is allowed to become.

A quotation, an order and a challan are all promises. They turn into
transactions, and only ever on their own side of the trade. Converting a
purchase order into a sale invoice would bill the shop's own supplier as a
customer at the shop's own buying prices — and SALE was the default target, so
it was one careless tap away.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


async def _document(shop, voucher_type: str, *, party: str = "customer") -> dict:
    client = shop["client"]
    response = await client.post(
        "/vouchers",
        json={
            "voucher_type": voucher_type,
            "party_id": shop[party]["id"],
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 4, "rate": 7400, "tax_rate": 0}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── the documents themselves ───────────────────────────────────────
@pytest.mark.parametrize(
    "voucher_type,party",
    [
        ("quotation", "customer"),
        ("proforma", "customer"),
        ("sale_order", "customer"),
        ("delivery_challan", "customer"),
        ("purchase_order", "supplier"),
    ],
)
@pytest.mark.asyncio
async def test_every_order_document_can_be_created(shop, voucher_type, party):
    created = await _document(shop, voucher_type, party=party)
    assert created["voucher_type"] == voucher_type
    assert Decimal(created["total"]) == Decimal("29600.00")


@pytest.mark.asyncio
async def test_an_order_does_not_move_stock(shop):
    """Ordering goods is not receiving them. Stock moves on the bill."""
    client = shop["client"]
    before = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])

    await _document(shop, "sale_order")

    after = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    assert after == before


@pytest.mark.asyncio
async def test_a_delivery_challan_does_move_stock(shop):
    """The goods have physically left the shop, whether or not it is billed yet."""
    client = shop["client"]
    before = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])

    await _document(shop, "delivery_challan")

    after = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    assert after == before - 4


@pytest.mark.asyncio
async def test_an_order_does_not_put_the_customer_in_debt(shop):
    client = shop["client"]
    before = Decimal((await client.get(f"/parties/{shop['customer']['id']}")).json()["balance"])

    await _document(shop, "sale_order")

    after = Decimal((await client.get(f"/parties/{shop['customer']['id']}")).json()["balance"])
    assert after == before, "nothing is owed until it is billed"


# ── what may become what ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_purchase_order_cannot_become_a_sale(shop):
    """The whole reason this rule exists."""
    client = shop["client"]
    order = await _document(shop, "purchase_order", party="supplier")

    refused = await client.post(
        f"/vouchers/{order['id']}/convert", json={"target_type": "sale"}
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "invalid_conversion"
    assert "purchase order" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_purchase_order_becomes_a_purchase_bill(shop):
    client = shop["client"]
    order = await _document(shop, "purchase_order", party="supplier")

    billed = await client.post(
        f"/vouchers/{order['id']}/convert", json={"target_type": "purchase"}
    )
    assert billed.status_code == 200, billed.text
    assert billed.json()["voucher_type"] == "purchase"
    assert billed.json()["party_id"] == shop["supplier"]["id"]


@pytest.mark.asyncio
async def test_a_sale_order_becomes_an_invoice(shop):
    client = shop["client"]
    order = await _document(shop, "sale_order")

    invoiced = await client.post(
        f"/vouchers/{order['id']}/convert", json={"target_type": "sale"}
    )
    assert invoiced.status_code == 200, invoiced.text
    assert Decimal(invoiced.json()["total"]) == Decimal("29600.00"), "the figures carry over"


@pytest.mark.asyncio
async def test_converting_marks_the_original_as_converted(shop):
    client = shop["client"]
    quote = await _document(shop, "quotation")

    await client.post(f"/vouchers/{quote['id']}/convert", json={"target_type": "sale"})

    after = (await client.get(f"/vouchers/{quote['id']}")).json()
    assert after["status"] == "converted"
    assert after["convertible_to"] == [], "a converted document is finished"


@pytest.mark.asyncio
async def test_the_same_document_cannot_be_converted_twice(shop):
    client = shop["client"]
    quote = await _document(shop, "quotation")

    await client.post(f"/vouchers/{quote['id']}/convert", json={"target_type": "sale"})
    again = await client.post(
        f"/vouchers/{quote['id']}/convert", json={"target_type": "sale"}
    )
    assert again.status_code == 409, again.text


@pytest.mark.asyncio
async def test_a_sale_invoice_is_not_convertible_at_all(shop):
    """It is already the transaction. There is nothing left for it to become."""
    client = shop["client"]
    invoice = await _document(shop, "sale")

    assert invoice["convertible_to"] == []

    refused = await client.post(
        f"/vouchers/{invoice['id']}/convert", json={"target_type": "quotation"}
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_a_cancelled_document_cannot_be_converted(shop):
    client = shop["client"]
    order = await _document(shop, "sale_order")
    await client.post(f"/vouchers/{order['id']}/cancel", json={"reason": "Customer changed mind"})

    refused = await client.post(
        f"/vouchers/{order['id']}/convert", json={"target_type": "sale"}
    )
    assert refused.status_code == 422, refused.text


# ── the app holds the same three facts about each document ─────────
#
# `mobile/lib/core/utils/document_types.dart` decides which party to pick,
# whether to show a payment field and whether to warn that stock will move.
# Those answers have to be the ones below. If a document changes here and not
# there, the form prices a purchase at retail or collects money the ledger has
# nowhere to put — so pin both ends and let this fail loudly.
def test_which_documents_move_stock():
    from app.models.enums import VoucherType

    assert {t.value for t in VoucherType if t.affects_stock} == {
        "sale", "purchase", "sale_return", "purchase_return", "delivery_challan",
    }


def test_which_documents_touch_the_ledger():
    from app.models.enums import VoucherType

    assert {t.value for t in VoucherType if t.affects_ledger} == {
        "sale", "purchase", "sale_return", "purchase_return",
    }


def test_which_documents_are_raised_against_a_supplier():
    from app.models.enums import VoucherType

    assert {t.value for t in VoucherType if t.party_kind == "supplier"} == {
        "purchase", "purchase_return", "purchase_order",
    }


# ── what the app is told it may offer ──────────────────────────────
@pytest.mark.parametrize(
    "voucher_type,party,expected",
    [
        ("quotation", "customer",
         ["delivery_challan", "proforma", "sale", "sale_order"]),
        ("proforma", "customer", ["delivery_challan", "sale", "sale_order"]),
        ("sale_order", "customer", ["delivery_challan", "sale"]),
        ("delivery_challan", "customer", ["sale"]),
        ("purchase_order", "supplier", ["purchase"]),
        ("sale", "customer", []),
        ("purchase", "supplier", []),
    ],
)
@pytest.mark.asyncio
async def test_each_document_advertises_exactly_what_it_may_become(
    shop, voucher_type, party, expected
):
    """The app builds its convert menu from this, so a conversion the server
    would refuse is never on screen to be tapped."""
    created = await _document(shop, voucher_type, party=party)
    assert sorted(created["convertible_to"]) == expected
