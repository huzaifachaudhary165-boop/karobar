"""Price lists and discount offers, over the API.

Thok and parchoon are genuinely different prices for the same sack of sugar.
What matters is that the rate the app quotes is one the shopkeeper can explain
to whoever is standing at the counter.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest


async def _list(client, name: str, **kw) -> dict:
    response = await client.post("/pricing/lists", json={"name": name, **kw})
    assert response.status_code == 201, response.text
    return response.json()


async def _quote(client, item_id: str, *, party_id: str | None = None, qty: int = 1) -> dict:
    response = await client.post(
        "/pricing/quote",
        json={
            "lines": [{"item_id": item_id, "qty": qty}],
            **({"party_id": party_id} if party_id else {}),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()[0]


# ── the lists themselves ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_price_list_can_be_created_and_listed(shop):
    client = shop["client"]
    await _list(client, "Wholesale", adjust_percent=-8, description="Thok rate")

    rows = (await client.get("/pricing/lists")).json()
    row = next(r for r in rows if r["name"] == "Wholesale")
    assert Decimal(row["adjust_percent"]) == Decimal("-8")
    assert row["item_count"] == 0


@pytest.mark.asyncio
async def test_two_lists_cannot_share_a_name(shop):
    client = shop["client"]
    await _list(client, "Wholesale")
    clash = await client.post("/pricing/lists", json={"name": "wholesale"})
    assert clash.status_code == 409, clash.text


@pytest.mark.asyncio
async def test_only_one_list_is_the_default(shop):
    client = shop["client"]
    first = await _list(client, "Retail", is_default=True)
    second = await _list(client, "Wholesale", is_default=True)

    rows = {r["id"]: r for r in (await client.get("/pricing/lists")).json()}
    assert rows[second["id"]]["is_default"] is True
    assert rows[first["id"]]["is_default"] is False


# ── what a line costs ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_with_no_list_an_item_quotes_its_own_price(shop):
    quoted = await _quote(shop["client"], shop["sugar"]["id"])
    assert Decimal(quoted["rate"]) == Decimal("7400.00")
    assert quoted["source"] == "item"


@pytest.mark.asyncio
async def test_a_customer_on_a_list_gets_that_list_s_rate(shop):
    client = shop["client"]
    wholesale = await _list(client, "Wholesale", adjust_percent=-8)
    await client.patch(
        f"/parties/{shop['customer']['id']}", json={"price_list": wholesale["id"]}
    )

    quoted = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"])
    assert Decimal(quoted["rate"]) == Decimal("6808.00")
    assert quoted["price_list_name"] == "Wholesale"


@pytest.mark.asyncio
async def test_a_named_rate_beats_the_list_s_blanket_rule(shop):
    """'Everything at 8% off, except sugar which is fixed.'"""
    client = shop["client"]
    wholesale = await _list(client, "Wholesale", adjust_percent=-8)
    await client.put(
        f"/pricing/lists/{wholesale['id']}/items",
        json={"item_id": shop["sugar"]["id"], "price": 7000},
    )
    await client.patch(
        f"/parties/{shop['customer']['id']}", json={"price_list": wholesale["id"]}
    )

    quoted = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"])
    assert Decimal(quoted["rate"]) == Decimal("7000.00")
    assert quoted["source"] == "list_entry"


@pytest.mark.asyncio
async def test_a_tiered_rate_only_applies_once_enough_is_bought(shop):
    client = shop["client"]
    bulk = await _list(client, "Bulk")
    await client.put(
        f"/pricing/lists/{bulk['id']}/items",
        json={"item_id": shop["sugar"]["id"], "price": 6900, "min_qty": 10},
    )
    await client.patch(
        f"/parties/{shop['customer']['id']}", json={"price_list": bulk["id"]}
    )

    few = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"], qty=5)
    many = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"], qty=10)

    assert Decimal(few["rate"]) == Decimal("7400.00")
    assert Decimal(many["rate"]) == Decimal("6900.00")


@pytest.mark.asyncio
async def test_the_shop_default_applies_to_a_customer_with_no_list(shop):
    client = shop["client"]
    await _list(client, "Everyday", adjust_percent=-3, is_default=True)

    quoted = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"])
    assert Decimal(quoted["rate"]) == Decimal("7178.00")


@pytest.mark.asyncio
async def test_a_rate_is_held_at_the_item_s_floor_and_says_so(shop):
    """Silently honouring a below-cost rate defeats the setting; silently
    refusing the sale strands a customer at the counter."""
    client = shop["client"]
    await client.patch(f"/items/{shop['sugar']['id']}", json={"min_sale_price": 7200})
    deep = await _list(client, "Too deep", adjust_percent=-30, is_default=True)
    assert deep["id"]

    quoted = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"])
    assert Decimal(quoted["rate"]) == Decimal("7200.00")
    assert quoted["held_at_minimum"] is True


# ── offers ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_bill_wide_offer_comes_off_the_line(shop):
    client = shop["client"]
    made = await client.post(
        "/pricing/schemes",
        json={"name": "Eid 10%", "scope": "bill", "discount_value": 10},
    )
    assert made.status_code == 201, made.text

    quoted = await _quote(client, shop["sugar"]["id"])
    assert Decimal(quoted["discount"]) == Decimal("740.00")
    assert quoted["scheme_name"] == "Eid 10%"
    assert Decimal(quoted["net"]) == Decimal("6660.00")


@pytest.mark.asyncio
async def test_an_item_offer_reaches_only_that_item(shop):
    client = shop["client"]
    await client.post(
        "/pricing/schemes",
        json={
            "name": "Sugar 5%", "scope": "item",
            "item_id": shop["sugar"]["id"], "discount_value": 5,
        },
    )

    sugar = await _quote(client, shop["sugar"]["id"])
    oil = await _quote(client, shop["oil"]["id"])

    assert Decimal(sugar["discount"]) > 0
    assert Decimal(oil["discount"]) == 0


@pytest.mark.asyncio
async def test_an_offer_aimed_at_one_customer_does_not_reach_others(shop):
    client = shop["client"]
    await client.post(
        "/pricing/schemes",
        json={
            "name": "Ahmed only", "scope": "party",
            "party_id": shop["customer"]["id"], "discount_value": 15,
        },
    )

    theirs = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"])
    walkin = await _quote(client, shop["sugar"]["id"])

    assert Decimal(theirs["discount"]) > 0
    assert Decimal(walkin["discount"]) == 0


@pytest.mark.asyncio
async def test_an_offer_below_its_threshold_does_not_fire(shop):
    client = shop["client"]
    await client.post(
        "/pricing/schemes",
        json={"name": "Over 20k", "discount_value": 5, "min_amount": 20000},
    )

    one = await _quote(client, shop["sugar"]["id"], qty=1)
    three = await _quote(client, shop["sugar"]["id"], qty=3)

    assert Decimal(one["discount"]) == 0
    assert Decimal(three["discount"]) > 0


@pytest.mark.asyncio
async def test_an_expired_offer_does_not_fire(shop):
    client = shop["client"]
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    await client.post(
        "/pricing/schemes",
        json={"name": "Ended", "discount_value": 20, "ends_on": yesterday},
    )

    quoted = await _quote(client, shop["sugar"]["id"])
    assert Decimal(quoted["discount"]) == 0


@pytest.mark.asyncio
async def test_only_one_offer_applies_never_two_stacked(shop):
    client = shop["client"]
    await client.post("/pricing/schemes", json={"name": "A 10%", "discount_value": 10})
    await client.post("/pricing/schemes", json={"name": "B 5%", "discount_value": 5})

    quoted = await _quote(client, shop["sugar"]["id"])
    assert Decimal(quoted["discount"]) in (Decimal("740.00"), Decimal("370.00"))
    assert Decimal(quoted["discount"]) != Decimal("1110.00")


@pytest.mark.asyncio
async def test_a_party_s_agreed_discount_is_the_fallback(shop):
    """It is what was agreed with them, not a promotion — so it applies only
    when no offer does."""
    client = shop["client"]
    await client.patch(
        f"/parties/{shop['customer']['id']}", json={"default_discount_percent": 4}
    )

    quoted = await _quote(client, shop["sugar"]["id"], party_id=shop["customer"]["id"])
    assert Decimal(quoted["discount"]) == Decimal("296.00")
    assert quoted["scheme_name"] == "Agreed discount"


# ── refusals ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_an_offer_taking_nothing_off_is_refused(shop):
    refused = await shop["client"].post(
        "/pricing/schemes", json={"name": "Nothing", "discount_value": 0}
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_a_percentage_over_a_hundred_is_refused(shop):
    refused = await shop["client"].post(
        "/pricing/schemes", json={"name": "Free", "discount_value": 150}
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_an_offer_that_ends_before_it_starts_is_refused(shop):
    refused = await shop["client"].post(
        "/pricing/schemes",
        json={
            "name": "Backwards", "discount_value": 10,
            "starts_on": "2026-09-01", "ends_on": "2026-08-01",
        },
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_an_item_offer_without_an_item_is_refused(shop):
    refused = await shop["client"].post(
        "/pricing/schemes",
        json={"name": "Which item?", "scope": "item", "discount_value": 10},
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_a_list_in_use_cannot_be_deleted(shop):
    client = shop["client"]
    wholesale = await _list(client, "In use")
    await client.patch(
        f"/parties/{shop['customer']['id']}", json={"price_list": wholesale["id"]}
    )

    refused = await client.delete(f"/pricing/lists/{wholesale['id']}")
    assert refused.status_code == 422, refused.text
    assert "customer" in refused.json()["error"]["message"]


# ── quoting a whole bill ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_whole_bill_can_be_quoted_at_once(shop):
    client = shop["client"]
    quoted = await client.post(
        "/pricing/quote",
        json={
            "party_id": shop["customer"]["id"],
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 2},
                {"item_id": shop["oil"]["id"], "qty": 3},
            ],
        },
    )
    assert quoted.status_code == 200, quoted.text
    rows = quoted.json()
    assert len(rows) == 2
    assert Decimal(rows[0]["line_total"]) == Decimal("14800.00")
    assert Decimal(rows[1]["line_total"]) == Decimal("8250.00")


@pytest.mark.asyncio
async def test_quoting_an_unknown_item_is_refused(shop):
    refused = await shop["client"].post(
        "/pricing/quote",
        json={"lines": [{"item_id": "00000000-0000-0000-0000-000000000000"}]},
    )
    assert refused.status_code == 404, refused.text
