"""Loyalty points over the API.

Points are a promise to a customer. Everything here is about that promise being
kept exactly — earned when it should be, spendable when it should be, and taken
back only when the sale that gave them is undone.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


async def _scheme(client, **kw) -> dict:
    response = await client.put(
        "/loyalty/program",
        json={"earn_rate": 0.01, "point_value": 1, "is_active": True, **kw},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _sale(shop, amount: int = 10000) -> dict:
    response = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [
                {
                    "item_id": shop["sugar"]["id"],
                    "qty": 1,
                    "rate": amount,
                    "tax_rate": 0,
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _balance(shop) -> int:
    response = await shop["client"].get(f"/loyalty/balance/{shop['customer']['id']}")
    assert response.status_code == 200, response.text
    return response.json()["balance"]


# ── the scheme ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_shop_with_no_scheme_says_so_rather_than_erroring(shop):
    response = await shop["client"].get("/loyalty/program")
    assert response.status_code == 200
    assert response.json() is None


@pytest.mark.asyncio
async def test_the_scheme_says_what_it_costs(shop):
    """One point per hundred, each worth a rupee, is 1% of every sale. A
    shopkeeper should see that before saving it."""
    program = await _scheme(shop["client"])
    assert Decimal(program["cost_percent"]) == Decimal("1.00")
    assert "1.00% of every sale" in program["summary"]


@pytest.mark.asyncio
async def test_a_scheme_that_gives_away_the_shop_is_refused(shop):
    """Almost always a typo in one of the two rates, and it would be found in
    the accounts months later rather than here."""
    refused = await shop["client"].put(
        "/loyalty/program", json={"earn_rate": 1, "point_value": 1}
    )
    assert refused.status_code == 422, refused.text
    assert "Check the earn rate" in refused.json()["error"]["message"]


# ── earning ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_sale_earns_points_without_anyone_asking(shop):
    """A scheme a customer only gets credit for some of the time is worse
    than none, so the server gives them rather than the caller."""
    await _scheme(shop["client"])
    await _sale(shop, amount=10000)
    assert await _balance(shop) == 100


@pytest.mark.asyncio
async def test_points_round_down(shop):
    await _scheme(shop["client"])
    await _sale(shop, amount=10099)
    assert await _balance(shop) == 100


@pytest.mark.asyncio
async def test_no_scheme_means_no_points(shop):
    await _sale(shop, amount=10000)
    assert await _balance(shop) == 0


@pytest.mark.asyncio
async def test_a_paused_scheme_earns_nothing(shop):
    await _scheme(shop["client"], is_active=False)
    await _sale(shop, amount=10000)
    assert await _balance(shop) == 0


@pytest.mark.asyncio
async def test_a_bill_below_the_threshold_earns_nothing(shop):
    await _scheme(shop["client"], min_bill_to_earn=5000)
    await _sale(shop, amount=1000)
    assert await _balance(shop) == 0

    await _sale(shop, amount=5000)
    assert await _balance(shop) == 50


@pytest.mark.asyncio
async def test_the_history_shows_where_the_points_came_from(shop):
    """The list a customer is entitled to when they ask."""
    await _scheme(shop["client"])
    sale = await _sale(shop, amount=10000)

    history = (
        await shop["client"].get(f"/loyalty/history/{shop['customer']['id']}")
    ).json()
    earned = next(row for row in history if row["kind"] == "earned")

    assert earned["points"] == 100
    assert earned["voucher_number"] == sale["number"]


# ── spending ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_quote_says_what_can_be_used_on_this_bill(shop):
    await _scheme(shop["client"])
    await _sale(shop, amount=10000)

    quote = (
        await shop["client"].post(
            "/loyalty/quote",
            json={"party_id": shop["customer"]["id"], "bill_total": 5000},
        )
    ).json()

    assert quote["enabled"] is True
    assert quote["balance"] == 100
    assert quote["redeemable"] == 100
    assert Decimal(quote["value"]) == Decimal("100.00")


@pytest.mark.asyncio
async def test_a_quote_never_offers_more_than_the_bill(shop):
    await _scheme(shop["client"])
    await _sale(shop, amount=100000)

    quote = (
        await shop["client"].post(
            "/loyalty/quote",
            json={"party_id": shop["customer"]["id"], "bill_total": 300},
        )
    ).json()
    assert quote["redeemable"] == 300


@pytest.mark.asyncio
async def test_a_cap_holds_back_how_much_one_bill_can_be_paid_with(shop):
    await _scheme(shop["client"], max_redeem_percent=20)
    await _sale(shop, amount=100000)

    quote = (
        await shop["client"].post(
            "/loyalty/quote",
            json={"party_id": shop["customer"]["id"], "bill_total": 1000},
        )
    ).json()
    assert quote["redeemable"] == 200


@pytest.mark.asyncio
async def test_spending_points_reduces_the_balance(shop):
    await _scheme(shop["client"])
    await _sale(shop, amount=10000)

    spent = await shop["client"].post(
        "/loyalty/redeem",
        json={"party_id": shop["customer"]["id"], "points": 60, "bill_total": 5000},
    )
    assert spent.status_code == 201, spent.text
    assert spent.json()["points"] == -60
    assert await _balance(shop) == 40


@pytest.mark.asyncio
async def test_spending_more_than_is_held_is_refused(shop):
    await _scheme(shop["client"])
    await _sale(shop, amount=10000)

    refused = await shop["client"].post(
        "/loyalty/redeem",
        json={"party_id": shop["customer"]["id"], "points": 500, "bill_total": 5000},
    )
    assert refused.status_code == 422, refused.text
    assert "At most 100" in refused.json()["error"]["message"]


@pytest.mark.asyncio
async def test_a_minimum_stops_a_handful_of_points_being_spent(shop):
    await _scheme(shop["client"], min_points_to_redeem=50)
    await _sale(shop, amount=2000)   # 20 points

    quote = (
        await shop["client"].post(
            "/loyalty/quote",
            json={"party_id": shop["customer"]["id"], "bill_total": 5000},
        )
    ).json()
    assert quote["redeemable"] == 0


@pytest.mark.asyncio
async def test_the_value_spent_is_recorded_at_the_time(shop):
    """So a later change to what a point is worth cannot rewrite what a
    customer was actually given."""
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=10000)

    spent = (
        await client.post(
            "/loyalty/redeem",
            json={"party_id": shop["customer"]["id"], "points": 50, "bill_total": 5000},
        )
    ).json()
    assert Decimal(spent["value"]) == Decimal("50.00")

    await _scheme(client, point_value=0.5)
    history = (await client.get(f"/loyalty/history/{shop['customer']['id']}")).json()
    still = next(row for row in history if row["kind"] == "redeemed")
    assert Decimal(still["value"]) == Decimal("50.00")


# ── undoing a sale ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cancelling_a_bill_takes_its_points_back(shop):
    """A cancelled bill that leaves the points as they were is a bill that
    gave something away for nothing."""
    client = shop["client"]
    await _scheme(client)
    sale = await _sale(shop, amount=10000)
    assert await _balance(shop) == 100

    cancelled = await client.post(
        f"/vouchers/{sale['id']}/cancel", json={"reason": "Customer returned it"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert await _balance(shop) == 0


@pytest.mark.asyncio
async def test_points_already_spent_elsewhere_are_not_clawed_back(shop):
    """Clawing them back would make a second customer's bill wrong to fix the
    first."""
    client = shop["client"]
    await _scheme(client)
    sale = await _sale(shop, amount=10000)

    await client.post(
        "/loyalty/redeem",
        json={"party_id": shop["customer"]["id"], "points": 80, "bill_total": 5000},
    )
    await client.post(f"/vouchers/{sale['id']}/cancel", json={"reason": "Returned"})

    # 20 unspent points came back off; the 80 already spent stayed spent.
    assert await _balance(shop) == 0


@pytest.mark.asyncio
async def test_cancelling_a_bill_that_used_points_gives_them_back(shop):
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=10000)

    second = await _sale(shop, amount=5000)
    await client.post(
        "/loyalty/redeem",
        json={
            "party_id": shop["customer"]["id"],
            "points": 40,
            "bill_total": 5000,
            "voucher_id": second["id"],
        },
    )
    assert await _balance(shop) == 110   # 100 + 50 earned, 40 spent

    await client.post(f"/vouchers/{second['id']}/cancel", json={"reason": "Returned"})
    # The 50 it earned came off, and the 40 it spent came back.
    assert await _balance(shop) == 100


# ── points as a tender ─────────────────────────────────────────────
# A customer who watches 200 rupees of points come off at the counter has paid
# 200 rupees of that bill. If the bill still says they owe it, the shopkeeper
# chases them for money the shop itself took off, and the customer argues —
# correctly. So points settle the bill they were spent on.
@pytest.mark.asyncio
async def test_points_pay_down_the_bill_they_were_spent_on(shop):
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=20000)          # earns 200

    bill = await _sale(shop, amount=5000)
    await client.post(
        "/loyalty/redeem",
        json={
            "party_id": shop["customer"]["id"],
            "points": 150,
            "bill_total": 5000,
            "voucher_id": bill["id"],
        },
    )

    response = await client.get(f"/vouchers/{bill['id']}")
    after = response.json()
    assert Decimal(after["paid_amount"]) == Decimal("150")
    assert Decimal(after["balance_amount"]) == Decimal("4850")


@pytest.mark.asyncio
async def test_the_bill_still_counts_as_a_full_sale(shop):
    """The 150 is what the reward scheme cost, not revenue the shop never made.

    Recorded as a discount it would quietly shrink every sales figure the shop
    has by the value of every reward it has ever given.
    """
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=20000)

    bill = await _sale(shop, amount=5000)
    await client.post(
        "/loyalty/redeem",
        json={
            "party_id": shop["customer"]["id"],
            "points": 150,
            "bill_total": 5000,
            "voucher_id": bill["id"],
        },
    )

    after = (await client.get(f"/vouchers/{bill['id']}")).json()
    assert Decimal(after["total"]) == Decimal("5000")


@pytest.mark.asyncio
async def test_points_do_not_put_money_in_the_bank(shop):
    """No cash arrived and nothing hit the account. Points are a tender, not a
    payment — defaulting them into the bank the way every other mode does would
    inflate the balance by every reward the shop has ever handed out."""
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=20000)

    before = (await client.get("/payments/accounts")).json()
    bill = await _sale(shop, amount=5000)
    await client.post(
        "/loyalty/redeem",
        json={
            "party_id": shop["customer"]["id"],
            "points": 150,
            "bill_total": 5000,
            "voucher_id": bill["id"],
        },
    )
    after = (await client.get("/payments/accounts")).json()

    def totals(rows):
        return sorted((row["id"], Decimal(row["balance"])) for row in rows)

    assert totals(after) == totals(before)


@pytest.mark.asyncio
async def test_redeeming_without_a_bill_settles_nothing(shop):
    """Points given back over the counter with no bill in front of them have no
    invoice to pay down, and inventing one would be a payment against nothing."""
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=20000)

    response = await client.post(
        "/loyalty/redeem",
        json={"party_id": shop["customer"]["id"], "points": 50, "bill_total": 5000},
    )
    assert response.status_code in (200, 201), response.text

    payments = (await client.get("/payments")).json()
    rows = payments["items"] if isinstance(payments, dict) else payments
    assert not [row for row in rows if row["mode"] == "points"]


@pytest.mark.asyncio
async def test_cancelling_takes_the_points_tender_back_off_the_bill(shop):
    """Cancelling refuses to run while a bill has payments against it, and
    rightly so — a real payment is somebody's money and the shopkeeper has to
    decide where it goes. This one is the shop's own machinery, so it clears
    itself rather than sending them looking for a payment they never made."""
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=20000)

    bill = await _sale(shop, amount=5000)
    await client.post(
        "/loyalty/redeem",
        json={
            "party_id": shop["customer"]["id"],
            "points": 150,
            "bill_total": 5000,
            "voucher_id": bill["id"],
        },
    )

    response = await client.post(
        f"/vouchers/{bill['id']}/cancel", json={"reason": "Returned"}
    )
    assert response.status_code == 200, response.text

    after = (await client.get(f"/vouchers/{bill['id']}")).json()
    assert after["status"] == "cancelled"
    assert Decimal(after["paid_amount"]) == Decimal("0")


# ── corrections ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_points_can_be_given_by_hand_with_a_reason(shop):
    client = shop["client"]
    await _scheme(client)

    given = await client.post(
        "/loyalty/adjust",
        json={
            "party_id": shop["customer"]["id"],
            "points": 200,
            "note": "Goodwill after a late delivery",
        },
    )
    assert given.status_code == 201, given.text
    assert await _balance(shop) == 200


@pytest.mark.asyncio
async def test_an_adjustment_without_a_reason_is_refused(shop):
    """An unexplained adjustment is what a customer points at when they
    dispute their balance."""
    await _scheme(shop["client"])
    refused = await shop["client"].post(
        "/loyalty/adjust",
        json={"party_id": shop["customer"]["id"], "points": 100, "note": ""},
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_taking_away_more_than_is_held_is_refused(shop):
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=10000)

    refused = await client.post(
        "/loyalty/adjust",
        json={"party_id": shop["customer"]["id"], "points": -500, "note": "Correction"},
    )
    assert refused.status_code == 422, refused.text


# ── the balance is the ledger ──────────────────────────────────────
@pytest.mark.asyncio
async def test_the_balance_always_equals_the_sum_of_the_ledger(shop):
    client = shop["client"]
    await _scheme(client)

    await _sale(shop, amount=10000)
    await _sale(shop, amount=7000)
    await client.post(
        "/loyalty/redeem",
        json={"party_id": shop["customer"]["id"], "points": 60, "bill_total": 5000},
    )
    await client.post(
        "/loyalty/adjust",
        json={"party_id": shop["customer"]["id"], "points": 25, "note": "Goodwill"},
    )

    history = (await client.get(f"/loyalty/history/{shop['customer']['id']}")).json()
    assert sum(row["points"] for row in history) == await _balance(shop)


@pytest.mark.asyncio
async def test_the_top_holders_can_be_listed(shop):
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=10000)

    top = (await client.get("/loyalty/top")).json()
    mine = next(row for row in top if row["party_id"] == shop["customer"]["id"])
    assert mine["points"] == 100
    assert Decimal(mine["value"]) == Decimal("100.00")


@pytest.mark.asyncio
async def test_pausing_the_scheme_leaves_points_already_given(shop):
    """Points already given are a promise to a customer."""
    client = shop["client"]
    await _scheme(client)
    await _sale(shop, amount=10000)

    stopped = await client.delete("/loyalty/program")
    assert stopped.status_code == 200, stopped.text
    assert await _balance(shop) == 100
