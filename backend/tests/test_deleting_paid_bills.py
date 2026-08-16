"""Deleting a bill that money has already come in against.

Refusing by default is right: a payment records cash that genuinely changed
hands, and deleting the bill underneath it would leave the books saying the
money was never received.

Refusing and stopping there is not. The message said to remove the payments
first, and there was nowhere to do that from the bill in front of the
shopkeeper — so "delete does not work, I just get warnings" was the whole
experience of trying.
"""

from __future__ import annotations

import pytest


async def _paid_bill(shop, amount: int = 500, paid: int | None = None) -> dict:
    response = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 1, "rate": amount, "tax_rate": 0}
            ],
            "payment": {"amount": paid if paid is not None else amount, "mode": "cash"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_an_unpaid_bill_deletes_without_ceremony(shop):
    bill = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 1, "rate": 500, "tax_rate": 0}
            ],
        },
    )
    gone = await shop["client"].delete(f"/vouchers/{bill.json()['id']}")
    assert gone.status_code == 200, gone.text


@pytest.mark.asyncio
async def test_a_paid_bill_is_refused_until_it_is_asked_for_properly(shop):
    bill = await _paid_bill(shop)

    refused = await shop["client"].delete(f"/vouchers/{bill['id']}")
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_the_refusal_carries_what_the_app_needs_to_offer_a_way_through(shop):
    """Without this the app can only repeat a refusal the shopkeeper cannot act
    on, which is where the dead end was."""
    bill = await _paid_bill(shop)

    refused = await shop["client"].delete(f"/vouchers/{bill['id']}")
    details = refused.json()["error"]["details"]

    assert details["can_release_payments"] is True
    assert details["can_delete_payments"] is True
    assert details["paid_amount"].startswith("500")
    assert details["party_name"]


@pytest.mark.asyncio
async def test_asking_for_it_properly_deletes_the_bill(shop):
    bill = await _paid_bill(shop)

    gone = await shop["client"].delete(
        f"/vouchers/{bill['id']}", params={"payments": "release"}
    )
    assert gone.status_code == 200, gone.text

    assert (await shop["client"].get(f"/vouchers/{bill['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_the_money_is_not_deleted_with_the_bill(shop):
    """The shop received that cash. The record of receiving it is not this
    bill's to destroy — it becomes an advance on the account instead."""
    client = shop["client"]
    bill = await _paid_bill(shop, amount=500)

    before = (await client.get("/payments")).json()
    count_before = len(before["items"] if isinstance(before, dict) else before)

    await client.delete(f"/vouchers/{bill['id']}", params={"payments": "release"})

    after = (await client.get("/payments")).json()
    rows = after["items"] if isinstance(after, dict) else after
    assert len(rows) == count_before, "the payment must survive the bill"

    freed = [r for r in rows if float(r["unallocated_amount"]) > 0]
    assert freed, "the money should now be sitting unallocated"
    assert any(float(r["unallocated_amount"]) == 500 for r in freed)


@pytest.mark.asyncio
async def test_the_customer_is_not_left_owing_a_bill_that_no_longer_exists(shop):
    client = shop["client"]
    party_id = shop["customer"]["id"]

    opening = float((await client.get(f"/parties/{party_id}")).json()["balance"])
    bill = await _paid_bill(shop, amount=500, paid=200)

    await client.delete(f"/vouchers/{bill['id']}", params={"payments": "release"})

    after = float((await client.get(f"/parties/{party_id}")).json()["balance"])
    assert after == pytest.approx(opening - 200), (
        "the bill is gone, so only the 200 they actually handed over should remain"
    )


@pytest.mark.asyncio
async def test_stock_comes_back(shop):
    client = shop["client"]
    before = float((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])

    bill = await _paid_bill(shop)
    await client.delete(f"/vouchers/{bill['id']}", params={"payments": "release"})

    after = float((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    assert after == before


# ── the second option: the entry that never happened ───────────────
@pytest.mark.asyncio
async def test_deleting_the_payments_too(shop):
    """For a duplicate, a test, or somebody else's bill keyed by mistake.

    The cash it claims to have received never arrived, so leaving the receipt
    behind would put money in the shop's books that nobody ever handed over.
    """
    client = shop["client"]
    bill = await _paid_bill(shop, amount=500)

    before = (await client.get("/payments")).json()
    count_before = len(before["items"] if isinstance(before, dict) else before)

    gone = await client.delete(
        f"/vouchers/{bill['id']}", params={"payments": "delete"}
    )
    assert gone.status_code == 200, gone.text

    after = (await client.get("/payments")).json()
    rows = after["items"] if isinstance(after, dict) else after
    assert len(rows) == count_before - 1, "the receipt must go with the bill"


@pytest.mark.asyncio
async def test_deleting_the_payments_puts_the_cash_back(shop):
    """The money never arrived, so the drawer must not still be counting it."""
    client = shop["client"]

    accounts = (await client.get("/payments/accounts")).json()
    before = {a["id"]: float(a["balance"]) for a in accounts}

    bill = await _paid_bill(shop, amount=500)
    await client.delete(f"/vouchers/{bill['id']}", params={"payments": "delete"})

    accounts = (await client.get("/payments/accounts")).json()
    after = {a["id"]: float(a["balance"]) for a in accounts}
    assert after == before


@pytest.mark.asyncio
async def test_the_customer_owes_nothing_from_a_bill_that_never_happened(shop):
    client = shop["client"]
    party_id = shop["customer"]["id"]

    opening = float((await client.get(f"/parties/{party_id}")).json()["balance"])
    bill = await _paid_bill(shop, amount=500, paid=200)

    await client.delete(f"/vouchers/{bill['id']}", params={"payments": "delete"})

    after = float((await client.get(f"/parties/{party_id}")).json()["balance"])
    assert after == pytest.approx(opening), (
        "neither the bill nor the 200 happened, so the balance is untouched"
    )


@pytest.mark.asyncio
async def test_a_payment_that_settled_other_bills_is_not_destroyed(shop):
    """Somebody's real money for those other bills.

    This bill has no claim to take it away from them, so the payment is only
    unlinked from this one however the delete was asked for.
    """
    client = shop["client"]

    first = await _paid_bill(shop, amount=500, paid=0) if False else None
    bill_a = (await client.post("/vouchers", json={
        "voucher_type": "sale",
        "party_id": shop["customer"]["id"],
        "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 300, "tax_rate": 0}],
    })).json()
    bill_b = (await client.post("/vouchers", json={
        "voucher_type": "sale",
        "party_id": shop["customer"]["id"],
        "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 200, "tax_rate": 0}],
    })).json()

    # One payment covering both, oldest first.
    settle = await client.post("/payments/settle", json={
        "party_id": shop["customer"]["id"], "amount": 500, "direction": "in",
    })
    assert settle.status_code in (200, 201), settle.text

    gone = await client.delete(
        f"/vouchers/{bill_a['id']}", params={"payments": "delete"}
    )
    assert gone.status_code == 200, gone.text

    # The other bill still has its share.
    other = (await client.get(f"/vouchers/{bill_b['id']}")).json()
    assert float(other["paid_amount"]) > 0, (
        "deleting one bill must not strip the payment off another"
    )
    assert first is None
