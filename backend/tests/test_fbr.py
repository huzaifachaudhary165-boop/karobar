"""Pakistani sales tax on real bills, and the monthly return.

The whole feature is off unless a shop turns it on, and the tests start there:
a shop that is not registered for sales tax must see no trace of it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


async def _turn_on(client, **kw) -> None:
    response = await client.patch(
        "/businesses/current/settings",
        json={"fbr_enabled": True, "sales_tax_rate": 18, **kw},
    )
    assert response.status_code == 200, response.text


async def _registered_buyer(shop) -> dict:
    response = await shop["client"].post(
        "/parties",
        json={
            "name": "Registered Traders",
            "party_type": "customer",
            "strn": "1234567890123",
            "ntn": "1234567-8",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _sale(shop, party_id: str | None, amount: int = 10000) -> dict:
    response = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            **({"party_id": party_id} if party_id else {"party_name": "Walk-in"}),
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 1, "rate": amount, "tax_rate": 18}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── the switch ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_shop_that_has_not_turned_it_on_is_charged_no_further_tax(shop):
    """Most small shops are not registered for sales tax at all."""
    sale = await _sale(shop, shop["customer"]["id"])
    assert Decimal(sale["further_tax_amount"]) == Decimal("0")
    assert Decimal(sale["total"]) == Decimal("11800.00")


@pytest.mark.asyncio
async def test_the_settings_carry_the_defaults_until_changed(shop):
    settings = (await shop["client"].get("/businesses/current/settings")).json()
    assert settings["fbr_enabled"] is False
    assert Decimal(settings["sales_tax_rate"]) == Decimal("18")
    assert Decimal(settings["further_tax_rate"]) == Decimal("3")


# ── further tax ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_an_unregistered_buyer_is_charged_further_tax(shop):
    """Three percent of every sale to every walk-in customer. A shop that has
    never heard of it is assessed for the difference years later."""
    await _turn_on(shop["client"])
    sale = await _sale(shop, shop["customer"]["id"])

    assert Decimal(sale["further_tax_amount"]) == Decimal("300.00")
    assert Decimal(sale["total"]) == Decimal("12100.00")


@pytest.mark.asyncio
async def test_a_registered_buyer_is_not(shop):
    await _turn_on(shop["client"])
    buyer = await _registered_buyer(shop)
    sale = await _sale(shop, buyer["id"])

    assert Decimal(sale["further_tax_amount"]) == Decimal("0")
    assert Decimal(sale["total"]) == Decimal("11800.00")


@pytest.mark.asyncio
async def test_a_walk_in_with_no_party_at_all_is_unregistered(shop):
    """Which is precisely the case further tax exists for."""
    await _turn_on(shop["client"])
    sale = await _sale(shop, None)
    assert Decimal(sale["further_tax_amount"]) == Decimal("300.00")


@pytest.mark.asyncio
async def test_an_ntn_alone_does_not_exempt_a_buyer(shop):
    """Income tax registration is not sales tax registration, and treating the
    two as the same is exactly how a shop under-charges."""
    await _turn_on(shop["client"])
    buyer = (
        await shop["client"].post(
            "/parties",
            json={"name": "NTN only", "party_type": "customer", "ntn": "1234567-8"},
        )
    ).json()

    sale = await _sale(shop, buyer["id"])
    assert Decimal(sale["further_tax_amount"]) == Decimal("300.00")


@pytest.mark.asyncio
async def test_a_shop_can_switch_further_tax_off_on_its_own(shop):
    await _turn_on(shop["client"], further_tax_enabled=False)
    sale = await _sale(shop, shop["customer"]["id"])
    assert Decimal(sale["further_tax_amount"]) == Decimal("0")


@pytest.mark.asyncio
async def test_the_further_tax_rate_is_a_setting(shop):
    await _turn_on(shop["client"], further_tax_rate=4)
    sale = await _sale(shop, shop["customer"]["id"])
    assert Decimal(sale["further_tax_amount"]) == Decimal("400.00")


@pytest.mark.asyncio
async def test_a_purchase_never_carries_further_tax(shop):
    """A shop does not levy it on its own buying."""
    await _turn_on(shop["client"])
    purchase = (
        await shop["client"].post(
            "/vouchers",
            json={
                "voucher_type": "purchase",
                "party_id": shop["supplier"]["id"],
                "lines": [
                    {"item_id": shop["sugar"]["id"], "qty": 1, "rate": 10000, "tax_rate": 18}
                ],
            },
        )
    ).json()
    assert Decimal(purchase["further_tax_amount"]) == Decimal("0")


# ── the monthly return ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_return_separates_registered_from_unregistered_sales(shop):
    client = shop["client"]
    await _turn_on(client)
    buyer = await _registered_buyer(shop)

    await _sale(shop, buyer["id"], amount=10000)
    await _sale(shop, shop["customer"]["id"], amount=5000)

    figures = (await client.get("/fbr/return")).json()
    assert Decimal(figures["registered_sales"]) == Decimal("10000.00")
    assert Decimal(figures["unregistered_sales"]) == Decimal("5000.00")
    assert Decimal(figures["total_sales"]) == Decimal("15000.00")


@pytest.mark.asyncio
async def test_the_return_adds_up_the_output_and_further_tax(shop):
    client = shop["client"]
    await _turn_on(client)
    await _sale(shop, shop["customer"]["id"], amount=10000)

    figures = (await client.get("/fbr/return")).json()
    assert Decimal(figures["output_tax"]) == Decimal("1800.00")
    assert Decimal(figures["further_tax"]) == Decimal("300.00")


@pytest.mark.asyncio
async def test_tax_paid_to_an_unregistered_supplier_is_not_claimable(shop):
    """Counting it would overstate the credit and understate what is owed —
    and a shop losing this every month has a reason to change supplier."""
    client = shop["client"]
    await _turn_on(client)

    await client.post(
        "/vouchers",
        json={
            "voucher_type": "purchase",
            "party_id": shop["supplier"]["id"],   # no STRN
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 1, "rate": 10000, "tax_rate": 18}
            ],
        },
    )

    figures = (await client.get("/fbr/return")).json()
    assert Decimal(figures["input_tax"]) == Decimal("0.00")
    assert Decimal(figures["unclaimable_input_tax"]) == Decimal("1800.00")


@pytest.mark.asyncio
async def test_tax_paid_to_a_registered_supplier_is_claimable(shop):
    client = shop["client"]
    await _turn_on(client)
    await client.patch(
        f"/parties/{shop['supplier']['id']}", json={"strn": "9876543210987"}
    )

    await client.post(
        "/vouchers",
        json={
            "voucher_type": "purchase",
            "party_id": shop["supplier"]["id"],
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 1, "rate": 10000, "tax_rate": 18}
            ],
        },
    )

    figures = (await client.get("/fbr/return")).json()
    assert Decimal(figures["input_tax"]) == Decimal("1800.00")


@pytest.mark.asyncio
async def test_more_input_than_output_carries_forward_rather_than_refunds(shop):
    """A shop shown 'refund due' would go looking for money that is not
    coming."""
    client = shop["client"]
    await _turn_on(client)
    await client.patch(
        f"/parties/{shop['supplier']['id']}", json={"strn": "9876543210987"}
    )

    await client.post(
        "/vouchers",
        json={
            "voucher_type": "purchase",
            "party_id": shop["supplier"]["id"],
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 5, "rate": 10000, "tax_rate": 18}
            ],
        },
    )
    await _sale(shop, shop["customer"]["id"], amount=1000)

    figures = (await client.get("/fbr/return")).json()
    assert Decimal(figures["net_payable"]) == Decimal("0")
    assert Decimal(figures["carried_forward"]) > 0


@pytest.mark.asyncio
async def test_a_cancelled_bill_is_out_of_the_return(shop):
    client = shop["client"]
    await _turn_on(client)
    sale = await _sale(shop, shop["customer"]["id"], amount=10000)
    await client.post(f"/vouchers/{sale['id']}/cancel", json={"reason": "Returned"})

    figures = (await client.get("/fbr/return")).json()
    assert Decimal(figures["total_sales"]) == Decimal("0.00")


# ── Annexure C ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_annexure_c_comes_out_in_the_portal_s_own_columns(shop):
    """So it can be pasted in rather than re-typed."""
    client = shop["client"]
    await _turn_on(client)
    await _sale(shop, shop["customer"]["id"], amount=10000)

    response = await client.get("/fbr/annexure-c")
    assert response.status_code == 200, response.text
    assert "text/csv" in response.headers["content-type"]

    header = response.text.splitlines()[0]
    assert "Buyer STRN" in header
    assert "Further Tax" in header
    assert "Value of Sales Excluding Sales Tax" in header


@pytest.mark.asyncio
async def test_annexure_c_states_the_buyer_type_on_every_row(shop):
    """It is what decides further tax, so whoever reads the file should not
    have to work it out."""
    client = shop["client"]
    await _turn_on(client)
    buyer = await _registered_buyer(shop)
    await _sale(shop, buyer["id"], amount=10000)
    await _sale(shop, shop["customer"]["id"], amount=5000)

    body = (await client.get("/fbr/annexure-c")).text
    assert "Registered" in body
    assert "Unregistered" in body


@pytest.mark.asyncio
async def test_annexure_c_is_downloadable_as_a_file(shop):
    client = shop["client"]
    await _turn_on(client)
    response = await client.get("/fbr/annexure-c")
    assert "attachment" in response.headers["content-disposition"]
    assert "annexure-c-" in response.headers["content-disposition"]


# ── suggested rates ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_suggested_rates_are_offered_for_setup(shop):
    rates = (await shop["client"].get("/fbr/rates")).json()
    assert Decimal(rates["standard_rate"]) == Decimal("18")
    assert Decimal(rates["further_tax_rate"]) == Decimal("3")
    assert "punjab" in rates["provinces"]
    assert rates["provinces"]["sindh"] == "Sindh Revenue Board"


@pytest.mark.asyncio
async def test_the_province_decides_which_authority_is_named(shop):
    client = shop["client"]
    await _turn_on(client, province="sindh")
    figures = (await client.get("/fbr/return")).json()
    assert figures["provincial_authority"] == "Sindh Revenue Board"
