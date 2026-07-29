"""The arithmetic a shopkeeper checks by hand against the printed bill.

Every expected figure below is worked out longhand in the test, not copied from
what the code happened to produce. A test that records current behaviour cannot
catch a wrong total — it only pins the mistake in place.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import money, rupee


def D(value) -> Decimal:
    """Compare against the API's string-encoded decimals without float error."""
    return Decimal(str(value))


# ── round-off ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("9652.50", "9653"),   # was 9652 under banker's rounding
        ("9653.50", "9654"),
        ("1234.50", "1235"),   # was 1234
        ("1235.50", "1236"),
        ("0.50", "1"),
        ("1199.49", "1199"),
        ("1199.51", "1200"),
        ("-0.50", "-1"),       # HALF_UP is away from zero
    ],
)
def test_half_a_rupee_always_rounds_up(raw, expected):
    """Two bills ending in .50 must round the same way.

    `.quantize()` without an explicit mode uses ROUND_HALF_EVEN, so 9652.50 went
    down and 9653.50 went up — a difference a shopkeeper cannot explain to a
    customer holding both receipts.
    """
    assert rupee(Decimal(raw)) == Decimal(expected)


def test_money_and_rupee_agree_about_direction():
    """Both round half away from zero; only the precision differs."""
    assert money("2.345") == Decimal("2.35")
    assert money("2.335") == Decimal("2.34")
    assert rupee("2.5") == Decimal("3")


# ── tax-inclusive pricing ────────────────────────────────────────
@pytest.mark.asyncio
async def test_an_item_priced_inclusive_of_tax_is_not_taxed_twice(shop):
    """Rs 1180 quoted inclusive of 18% is Rs 1000 + Rs 180, total Rs 1180.

    `Item.price_includes_tax` was accepted by the API, stored, and echoed back
    in every response, but the invoice engine never read it — so this same bill
    came to 1392: the shopkeeper's setting was ignored and the customer was
    overcharged by the full 18%.
    """
    client = shop["client"]
    item = (
        await client.post(
            "/items",
            json={
                "name": "Inclusive Widget",
                "sale_price": 1180,
                "purchase_price": 800,
                "opening_stock": 50,
                "tax_rate": 18,
                "price_includes_tax": True,
            },
        )
    ).json()
    assert item["price_includes_tax"] is True

    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "lines": [{"item_id": item["id"], "qty": 1, "rate": 1180}],
            },
        )
    ).json()

    assert D(invoice["taxable_amount"]) == Decimal("1000.00")
    assert D(invoice["tax_amount"]) == Decimal("180.00")
    assert D(invoice["total"]) == Decimal("1180.00")
    # Profit is measured on the net, not the tax-inclusive rate.
    assert D(invoice["profit"]) == Decimal("200.00")


@pytest.mark.asyncio
async def test_a_normal_item_is_still_taxed_on_top(shop):
    """The fix must not make every item inclusive."""
    invoice = (
        await client_post_sale(shop, shop["oil"]["id"], qty=1, rate=1000)
    )
    # Oil carries 17%.
    assert D(invoice["taxable_amount"]) == Decimal("1000.00")
    assert D(invoice["tax_amount"]) == Decimal("170.00")
    assert D(invoice["total"]) == Decimal("1170.00")


async def client_post_sale(shop, item_id, *, qty, rate, **extra):
    response = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": item_id, "qty": qty, "rate": rate}],
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── line and document arithmetic ─────────────────────────────────
@pytest.mark.asyncio
async def test_a_line_discount_comes_off_before_tax(shop):
    """3 × 2750 = 8250, less 10% = 7425, +17% = 1262.25, total 8687.25 → 8687."""
    invoice = await client_post_sale_lines(
        shop,
        [
            {
                "item_id": shop["oil"]["id"],
                "qty": 3,
                "rate": 2750,
                "discount_type": "percent",
                "discount_value": 10,
            }
        ],
    )
    assert D(invoice["subtotal"]) == Decimal("8250.00")
    assert D(invoice["discount_amount"]) == Decimal("825.00")
    assert D(invoice["taxable_amount"]) == Decimal("7425.00")
    # 17% of 7425 = 1262.25, split 8.5% + 8.5% = 631.125 → 631.13 each.
    assert D(invoice["tax_amount"]) == Decimal("1262.26")
    assert D(invoice["total"]) == Decimal("8687.00")
    assert D(invoice["round_off"]) == Decimal("-0.26")


@pytest.mark.asyncio
async def test_a_document_discount_applies_after_line_discounts(shop):
    """2 × 1000 = 2000, less 5% document discount = 1900, +17% = 323."""
    invoice = await client_post_sale_lines(
        shop,
        [{"item_id": shop["oil"]["id"], "qty": 2, "rate": 1000}],
        discount_type="percent",
        discount_value=5,
    )
    assert D(invoice["discount_amount"]) == Decimal("100.00")
    assert D(invoice["taxable_amount"]) == Decimal("1900.00")
    assert D(invoice["tax_amount"]) == Decimal("323.00")
    assert D(invoice["total"]) == Decimal("2223.00")


@pytest.mark.asyncio
async def test_charges_are_added_after_tax_and_do_not_attract_it(shop):
    """Sugar is zero-rated: 1000 + 150 shipping + 49.50 packaging = 1199.50."""
    invoice = await client_post_sale_lines(
        shop,
        [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 1000}],
        shipping_charge=150,
        packaging_charge="49.50",
    )
    assert D(invoice["tax_amount"]) == Decimal("0.00")
    assert D(invoice["total"]) == Decimal("1200.00")
    assert D(invoice["round_off"]) == Decimal("0.50")


@pytest.mark.asyncio
async def test_the_lines_add_up_to_the_subtotal_exactly(shop):
    """Fractional quantities and awkward rates must not drift.

    Decimal all the way through is the reason this holds; a float pipeline
    would land a paisa or two out and the bill would not foot.
    """
    lines = [
        {"item_id": shop["sugar"]["id"], "qty": "1.333", "rate": "333.33"},
        {"item_id": shop["oil"]["id"], "qty": "2.5", "rate": "111.11"},
        {"item_id": shop["sugar"]["id"], "qty": "0.777", "rate": "9.99"},
    ]
    invoice = await client_post_sale_lines(shop, lines)

    # 1.333 × 333.33 = 444.328  → 444.33
    # 2.5   × 111.11 = 277.775  → 277.78
    # 0.777 ×   9.99 =   7.7622 →   7.76
    assert D(invoice["subtotal"]) == Decimal("729.87")

    by_line = sum(D(line["taxable_amount"]) for line in invoice["lines"])
    assert by_line == D(invoice["taxable_amount"])

    stated = (
        D(invoice["taxable_amount"])
        + D(invoice["tax_amount"])
        + D(invoice["round_off"])
    )
    assert stated == D(invoice["total"]), "the printed bill must foot"


@pytest.mark.asyncio
async def test_a_discount_cannot_exceed_the_line(shop):
    """A fat-fingered discount must not turn into a negative bill."""
    invoice = await client_post_sale_lines(
        shop,
        [
            {
                "item_id": shop["sugar"]["id"],
                "qty": 1,
                "rate": 100,
                "discount_type": "amount",
                "discount_value": 500,
            }
        ],
    )
    assert D(invoice["discount_amount"]) == Decimal("100.00")
    assert D(invoice["total"]) >= Decimal("0")


@pytest.mark.asyncio
async def test_a_partial_payment_leaves_the_exact_balance(shop):
    invoice = await client_post_sale_lines(
        shop,
        [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 1000}],
    )
    total = D(invoice["total"])

    # No voucher is named: this is the "received 400.50 from Ahmed" flow, which
    # allocates oldest-invoice-first.
    paid = await shop["client"].post(
        "/payments",
        json={
            "party_id": shop["customer"]["id"],
            "amount": "400.50",
            "direction": "in",
            "mode": "cash",
        },
    )
    assert paid.status_code == 201, paid.text
    refreshed = (await shop["client"].get(f"/vouchers/{invoice['id']}")).json()

    assert D(refreshed["paid_amount"]) == Decimal("400.50")
    assert D(refreshed["balance_amount"]) == total - Decimal("400.50")


async def client_post_sale_lines(shop, lines, **extra):
    response = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": lines,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
