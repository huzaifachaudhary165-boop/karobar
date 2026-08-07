"""The reports beyond the obvious ones.

Each answers a question somebody asks out loud. A report nobody would ask for
is a screen nobody opens, so every test here is phrased as the question.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest


async def _sale(shop, *, item: str, qty: int, rate: int, discount: int = 0) -> dict:
    response = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "discount_type": "amount",
            "discount_value": discount,
            "lines": [{"item_id": item, "qty": qty, "rate": rate, "tax_rate": 0}],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── which goods are dead on the shelf ──────────────────────────────
@pytest.mark.asyncio
async def test_stock_that_has_never_sold_shows_up_as_dead(shop):
    rows = (await shop["client"].get("/reports/dead-stock")).json()
    names = {row["item_name"] for row in rows["items"]}

    assert "Sugar 50kg" in names, "opening stock that has never sold is dead stock"
    assert rows["never_sold_count"] >= 1


@pytest.mark.asyncio
async def test_dead_stock_is_sorted_by_what_it_ties_up(shop):
    """Forty slow items worth two hundred between them is not a problem; one
    worth eighty thousand is why the shop cannot pay its supplier."""
    rows = (await shop["client"].get("/reports/dead-stock")).json()["items"]
    values = [Decimal(row["stock_value"]) for row in rows]
    assert values == sorted(values, reverse=True)


@pytest.mark.asyncio
async def test_something_sold_today_is_not_dead_stock(shop):
    client = shop["client"]
    await _sale(shop, item=shop["sugar"]["id"], qty=1, rate=7400)

    rows = (await client.get("/reports/dead-stock")).json()["items"]
    sugar = [row for row in rows if row["item_name"] == "Sugar 50kg"]
    assert sugar == []


@pytest.mark.asyncio
async def test_stock_ageing_comes_out_in_bands(shop):
    """An average of sixty days hides that half the money is in goods nobody
    has touched in a year."""
    bands = (await shop["client"].get("/reports/stock-ageing")).json()["bands"]
    labels = [band["label"] for band in bands]

    assert labels == [
        "0-30 days", "31-90 days", "91-180 days", "181-365 days", "Over a year",
    ]
    assert sum(Decimal(band["value"]) for band in bands) > 0


# ── what actually makes money ──────────────────────────────────────
@pytest.mark.asyncio
async def test_profit_per_item_is_not_the_same_list_as_sales_per_item(shop):
    """The best-selling thing is often the one the shop makes least on."""
    client = shop["client"]
    # Sugar: high turnover, thin margin. Oil: fewer sold, better margin.
    await _sale(shop, item=shop["sugar"]["id"], qty=10, rate=7000)
    await _sale(shop, item=shop["oil"]["id"], qty=2, rate=2750)

    rows = (await client.get("/reports/item-profit")).json()["items"]
    assert rows, "nothing came back"

    by_name = {row["item_name"]: row for row in rows}
    assert Decimal(by_name["Sugar 50kg"]["revenue"]) > Decimal(
        by_name["Cooking Oil 5L"]["revenue"]
    )
    # Sorted by profit, so the order can differ from the revenue order.
    profits = [Decimal(row["profit"]) for row in rows]
    assert profits == sorted(profits, reverse=True)


@pytest.mark.asyncio
async def test_each_item_reports_its_margin(shop):
    client = shop["client"]
    await _sale(shop, item=shop["sugar"]["id"], qty=1, rate=7400)

    row = (await client.get("/reports/item-profit")).json()["items"][0]
    assert Decimal(row["revenue"]) - Decimal(row["cost"]) == Decimal(row["profit"])
    assert Decimal(row["margin_percent"]) > 0


@pytest.mark.asyncio
async def test_profit_per_customer(shop):
    client = shop["client"]
    await _sale(shop, item=shop["sugar"]["id"], qty=2, rate=7400)

    rows = (await client.get("/reports/party-profit")).json()["parties"]
    mine = next(row for row in rows if row["party_id"] == shop["customer"]["id"])

    assert mine["bill_count"] == 1
    assert Decimal(mine["revenue"]) == Decimal("14800.00")


# ── margin given away ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_discounts_are_totalled_because_nobody_sees_them_one_bill_at_a_time(shop):
    client = shop["client"]
    await _sale(shop, item=shop["sugar"]["id"], qty=1, rate=7400, discount=500)
    await _sale(shop, item=shop["sugar"]["id"], qty=1, rate=7400, discount=300)
    await _sale(shop, item=shop["sugar"]["id"], qty=1, rate=7400)

    figures = (await client.get("/reports/discounts")).json()
    assert Decimal(figures["total_discount"]) == Decimal("800.00")
    assert figures["bill_count"] == 3
    assert figures["discounted_bill_count"] == 2


@pytest.mark.asyncio
async def test_discount_is_set_against_profit_not_just_turnover(shop):
    """The comparison that lands: a share of what was actually earned."""
    client = shop["client"]
    await _sale(shop, item=shop["sugar"]["id"], qty=1, rate=7400, discount=200)

    figures = (await client.get("/reports/discounts")).json()
    assert Decimal(figures["share_of_profit"]) > 0
    assert Decimal(figures["discount_percent"]) > 0


@pytest.mark.asyncio
async def test_no_discounts_given_is_not_an_error(shop):
    figures = (await shop["client"].get("/reports/discounts")).json()
    assert Decimal(figures["total_discount"]) == Decimal("0")


# ── how customers pay ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_payment_modes_add_up_to_everything_that_came_in(shop):
    client = shop["client"]
    for mode, amount in (("cash", 5000), ("bank", 3000), ("easypaisa", 2000)):
        await client.post(
            "/payments",
            json={
                "direction": "in",
                "party_id": shop["customer"]["id"],
                "amount": amount,
                "mode": mode,
            },
        )

    rows = (await client.get("/reports/payment-modes")).json()["modes"]
    assert sum(Decimal(row["amount"]) for row in rows) == Decimal("10000.00")
    assert sum(Decimal(row["share_percent"]) for row in rows) == Decimal("100.00")


@pytest.mark.asyncio
async def test_payment_modes_are_biggest_first(shop):
    client = shop["client"]
    for mode, amount in (("cash", 1000), ("bank", 9000)):
        await client.post(
            "/payments",
            json={
                "direction": "in", "party_id": shop["customer"]["id"],
                "amount": amount, "mode": mode,
            },
        )

    rows = (await client.get("/reports/payment-modes")).json()["modes"]
    assert rows[0]["mode"] == "bank"


# ── registers ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_purchase_register_lists_supplier_bills(shop):
    client = shop["client"]
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "purchase",
            "party_id": shop["supplier"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 5, "rate": 6800}],
        },
    )

    register = (await client.get("/reports/purchase-register")).json()
    assert len(register["rows"]) == 1
    assert Decimal(register["total"]) == Decimal("34000.00")


@pytest.mark.asyncio
async def test_returns_are_listed_so_a_pattern_can_be_seen(shop):
    """A customer who returns half of what they buy is a pattern nobody
    notices one credit note at a time."""
    client = shop["client"]
    sale = await _sale(shop, item=shop["sugar"]["id"], qty=4, rate=7400)

    returned = await client.post(
        f"/vouchers/{sale['id']}/return",
        json={"reason": "Damaged bags"},
    )
    assert returned.status_code in (200, 201), returned.text

    register = (await client.get("/reports/returns")).json()
    assert len(register["rows"]) >= 1
    assert register["rows"][0]["reason"] is not None


# ── expenses against last time ─────────────────────────────────────
@pytest.mark.asyncio
async def test_expenses_are_shown_against_the_period_before(shop):
    """A category on its own is a number; against last month it is a
    decision."""
    client = shop["client"]
    today = date.today()
    await client.post(
        "/expenses",
        json={"title": "Shop rent", "amount": 25000, "expense_date": today.isoformat()},
    )

    rows = (
        await client.get(
            "/reports/expense-trend",
            params={
                "start_date": (today - timedelta(days=15)).isoformat(),
                "end_date": today.isoformat(),
            },
        )
    ).json()["categories"]

    assert rows
    assert "previous_amount" in rows[0]
    assert "change" in rows[0]


# ── stock movement ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_stock_movement_shows_in_out_and_closing(shop):
    client = shop["client"]
    await _sale(shop, item=shop["sugar"]["id"], qty=3, rate=7400)

    rows = (await client.get("/reports/stock-movement")).json()["items"]
    sugar = next(row for row in rows if row["item_name"] == "Sugar 50kg")

    assert Decimal(sugar["issued"]) == Decimal("3.0000")
    assert Decimal(sugar["received"]) == Decimal("100.0000"), "the opening stock"
    assert Decimal(sugar["closing"]) == Decimal("97.0000")


# ── who owes what ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_outstanding_balances_come_out_largest_first(shop):
    client = shop["client"]
    await _sale(shop, item=shop["sugar"]["id"], qty=5, rate=7400)

    balances = (await client.get("/reports/balances")).json()
    assert balances["parties"]
    amounts = [Decimal(row["balance"]) for row in balances["parties"]]
    assert amounts == sorted(amounts, reverse=True)
    assert Decimal(balances["total"]) > 0


@pytest.mark.asyncio
async def test_a_customer_over_their_credit_limit_is_flagged(shop):
    client = shop["client"]
    await client.patch(f"/parties/{shop['customer']['id']}", json={"credit_limit": 1000})
    await _sale(shop, item=shop["sugar"]["id"], qty=5, rate=7400)

    balances = (await client.get("/reports/balances")).json()
    assert balances["over_limit_count"] >= 1


# ── the catalogue ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_every_report_is_listed_in_one_place(shop):
    """So the reports screen is built from this rather than from a hard-coded
    menu that drifts out of step with what exists."""
    catalogue = (await shop["client"].get("/reports/catalogue")).json()
    reports = [r for group in catalogue["groups"] for r in group["reports"]]

    assert len(reports) >= 30
    assert all(r["key"] and r["name"] and r["about"] for r in reports)

    keys = [r["key"] for r in reports]
    assert len(keys) == len(set(keys)), "a report is listed twice"


@pytest.mark.asyncio
async def test_the_catalogue_is_grouped_the_way_a_shopkeeper_thinks(shop):
    catalogue = (await shop["client"].get("/reports/catalogue")).json()
    titles = [group["title"] for group in catalogue["groups"]]

    assert "Money" in titles
    assert "Stock" in titles
    assert "Owed" in titles
