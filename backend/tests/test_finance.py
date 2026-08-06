"""Account transfers, cheques and loans, over the API.

Three separate promises, all about the same thing: an account balance that a
shopkeeper can put next to a bank statement without flinching.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest


async def _account(client, name: str, kind: str = "bank", opening: int = 0) -> dict:
    response = await client.post(
        "/payments/accounts",
        json={"name": name, "account_type": kind, "opening_balance": opening},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _balance(client, account_id: str) -> Decimal:
    accounts = (await client.get("/payments/accounts")).json()
    return Decimal(next(a for a in accounts if a["id"] == account_id)["balance"])


# ── transfers ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_banking_the_day_s_cash_moves_it_out_of_the_drawer(shop):
    client = shop["client"]
    drawer = await _account(client, "Counter Cash", "cash", opening=50000)
    bank = await _account(client, "Meezan Bank", "bank", opening=200000)

    moved = await client.post(
        "/finance/transfers",
        json={"from_account_id": drawer["id"], "to_account_id": bank["id"], "amount": 30000},
    )
    assert moved.status_code == 201, moved.text

    assert await _balance(client, drawer["id"]) == Decimal("20000.00")
    assert await _balance(client, bank["id"]) == Decimal("230000.00")


@pytest.mark.asyncio
async def test_a_transfer_does_not_make_the_business_any_richer(shop):
    client = shop["client"]
    drawer = await _account(client, "Cash Box", "cash", opening=80000)
    bank = await _account(client, "HBL Current", "bank", opening=120000)
    before = await _balance(client, drawer["id"]) + await _balance(client, bank["id"])

    await client.post(
        "/finance/transfers",
        json={"from_account_id": drawer["id"], "to_account_id": bank["id"], "amount": 45000},
    )

    after = await _balance(client, drawer["id"]) + await _balance(client, bank["id"])
    assert after == before


@pytest.mark.asyncio
async def test_bank_charges_leave_the_sending_account_and_arrive_nowhere(shop):
    """Without this the two balances refuse to match the statement."""
    client = shop["client"]
    source = await _account(client, "UBL Business", "bank", opening=100000)
    target = await _account(client, "Easypaisa", "wallet", opening=0)

    sent = await client.post(
        "/finance/transfers",
        json={
            "from_account_id": source["id"], "to_account_id": target["id"],
            "amount": 25000, "charges": 150,
        },
    )
    assert sent.status_code == 201, sent.text
    assert Decimal(sent.json()["total_debited"]) == Decimal("25150.00")

    assert await _balance(client, source["id"]) == Decimal("74850.00")
    assert await _balance(client, target["id"]) == Decimal("25000.00")


@pytest.mark.asyncio
async def test_undoing_a_transfer_puts_both_balances_back(shop):
    client = shop["client"]
    source = await _account(client, "Askari Bank", "bank", opening=90000)
    target = await _account(client, "Petty Cash", "cash", opening=5000)

    sent = (
        await client.post(
            "/finance/transfers",
            json={
                "from_account_id": source["id"], "to_account_id": target["id"],
                "amount": 10000, "charges": 100,
            },
        )
    ).json()

    removed = await client.delete(f"/finance/transfers/{sent['id']}")
    assert removed.status_code == 200, removed.text

    assert await _balance(client, source["id"]) == Decimal("90000.00")
    assert await _balance(client, target["id"]) == Decimal("5000.00")


@pytest.mark.asyncio
async def test_transferring_into_the_same_account_is_refused(shop):
    client = shop["client"]
    only = await _account(client, "Single Account", "bank", opening=1000)

    same = await client.post(
        "/finance/transfers",
        json={"from_account_id": only["id"], "to_account_id": only["id"], "amount": 100},
    )
    assert same.status_code == 422, same.text


@pytest.mark.asyncio
async def test_transfers_are_listed_with_both_account_names(shop):
    client = shop["client"]
    source = await _account(client, "Faysal Bank", "bank", opening=60000)
    target = await _account(client, "Shop Drawer", "cash", opening=0)

    await client.post(
        "/finance/transfers",
        json={"from_account_id": source["id"], "to_account_id": target["id"], "amount": 7000},
    )

    listed = (await client.get("/finance/transfers")).json()
    row = next(r for r in listed if r["from_account_id"] == source["id"])
    assert row["from_account_name"] == "Faysal Bank"
    assert row["to_account_name"] == "Shop Drawer"


# ── cheques ────────────────────────────────────────────────────────
async def _cheque_payment(shop, *, amount: int, days: int) -> dict:
    client = shop["client"]
    response = await client.post(
        "/payments",
        json={
            "direction": "in",
            "party_id": shop["customer"]["id"],
            "amount": amount,
            "mode": "cheque",
            "reference_number": f"CHQ-{amount}",
            "cheque_date": (date.today() + timedelta(days=days)).isoformat(),

        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_a_cheque_in_hand_shows_up_as_still_open(shop):
    client = shop["client"]
    await _cheque_payment(shop, amount=45000, days=10)

    open_cheques = (await client.get("/finance/cheques")).json()
    assert any(c["reference_number"] == "CHQ-45000" for c in open_cheques)


@pytest.mark.asyncio
async def test_a_cheque_dated_in_the_past_is_flagged_overdue(shop):
    client = shop["client"]
    await _cheque_payment(shop, amount=31000, days=-4)

    row = next(
        c for c in (await client.get("/finance/cheques")).json()
        if c["reference_number"] == "CHQ-31000"
    )
    assert row["is_overdue"] is True
    assert row["days_until_due"] == -4


@pytest.mark.asyncio
async def test_a_cheque_only_becomes_money_when_the_bank_clears_it(shop):
    client = shop["client"]
    account = await _account(client, "Bank Al Habib", "bank", opening=0)

    written = await client.post(
        "/payments",
        json={
            "direction": "in", "party_id": shop["customer"]["id"], "amount": 60000,
            "mode": "cheque", "account_id": account["id"],
        },
    )
    assert written.status_code == 201, written.text

    assert await _balance(client, account["id"]) == Decimal("0.00"), (
        "a promise is not money — the balance must not move on writing"
    )

    cleared = await client.patch(
        f"/finance/cheques/{written.json()['id']}", json={"status": "cleared"}
    )
    assert cleared.status_code == 200, cleared.text
    assert await _balance(client, account["id"]) == Decimal("60000.00")


@pytest.mark.asyncio
async def test_a_bounced_cheque_takes_the_money_back_out(shop):
    """The exact failure this feature exists to catch."""
    client = shop["client"]
    account = await _account(client, "Standard Chartered", "bank", opening=10000)

    written = (
        await client.post(
            "/payments",
            json={
                "direction": "in", "party_id": shop["customer"]["id"], "amount": 25000,
                "mode": "cheque", "account_id": account["id"],
            },
        )
    ).json()

    await client.patch(f"/finance/cheques/{written['id']}", json={"status": "cleared"})
    assert await _balance(client, account["id"]) == Decimal("35000.00")

    bounced = await client.patch(
        f"/finance/cheques/{written['id']}",
        json={"status": "bounced", "note": "Returned — insufficient funds"},
    )
    assert bounced.status_code == 200, bounced.text
    assert await _balance(client, account["id"]) == Decimal("10000.00")


@pytest.mark.asyncio
async def test_a_cleared_cheque_cannot_quietly_go_back_to_pending(shop):
    client = shop["client"]
    written = await _cheque_payment(shop, amount=12000, days=3)
    await client.patch(f"/finance/cheques/{written['id']}", json={"status": "cleared"})

    reverted = await client.patch(
        f"/finance/cheques/{written['id']}", json={"status": "pending"}
    )
    assert reverted.status_code == 422, reverted.text


@pytest.mark.asyncio
async def test_a_payment_made_in_cash_is_not_a_cheque(shop):
    client = shop["client"]
    cash = (
        await client.post(
            "/payments",
            json={
                "direction": "in", "party_id": shop["customer"]["id"],
                "amount": 5000, "mode": "cash",
            },
        )
    ).json()

    refused = await client.patch(f"/finance/cheques/{cash['id']}", json={"status": "cleared"})
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_taking_a_payment_then_making_one_does_not_collide(shop):
    """Receipts and payments are counted in separate series. Sharing a prefix
    gave both a first document numbered RCP-0001, and the second one written
    was refused outright."""
    client = shop["client"]

    received = await client.post(
        "/payments",
        json={"direction": "in", "party_id": shop["customer"]["id"], "amount": 5000},
    )
    assert received.status_code == 201, received.text

    paid = await client.post(
        "/payments",
        json={"direction": "out", "party_id": shop["supplier"]["id"], "amount": 3000},
    )
    assert paid.status_code == 201, paid.text
    assert paid.json()["number"] != received.json()["number"]


@pytest.mark.asyncio
async def test_the_cheque_summary_separates_incoming_from_outgoing(shop):
    client = shop["client"]
    await _cheque_payment(shop, amount=70000, days=5)
    written = await client.post(
        "/payments",
        json={
            "direction": "out", "party_id": shop["supplier"]["id"], "amount": 20000,
            "mode": "cheque",
        },
    )
    assert written.status_code == 201, written.text

    summary = (await client.get("/finance/cheques/summary")).json()
    assert summary["to_deposit_count"] >= 1
    assert Decimal(summary["to_deposit_amount"]) >= Decimal("70000")
    assert summary["to_clear_count"] >= 1
    assert Decimal(summary["to_clear_amount"]) >= Decimal("20000")


# ── loans ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_recording_a_loan_works_out_the_instalment(shop):
    client = shop["client"]
    created = await client.post(
        "/finance/loans",
        json={
            "lender_name": "Meezan Bank", "loan_type": "business",
            "principal": 500000, "interest_rate": 12, "interest_type": "reducing",
            "tenure_months": 24, "start_date": "2026-01-01",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()

    assert Decimal(body["emi_amount"]) == Decimal("23536.74")
    assert Decimal(body["outstanding_principal"]) == Decimal("500000.00")
    assert body["status"] == "active"
    assert body["next_due_date"] == "2026-02-01"


@pytest.mark.asyncio
async def test_borrowed_money_lands_in_the_account_it_was_paid_into(shop):
    client = shop["client"]
    account = await _account(client, "Loan Account", "bank", opening=5000)

    await client.post(
        "/finance/loans",
        json={
            "lender_name": "JS Bank", "principal": 300000, "interest_rate": 15,
            "tenure_months": 12, "account_id": account["id"],
        },
    )
    assert await _balance(client, account["id"]) == Decimal("305000.00")


@pytest.mark.asyncio
async def test_an_interest_free_family_loan_is_allowed(shop):
    """Far more common in a small shop than a bank term loan."""
    client = shop["client"]
    created = await client.post(
        "/finance/loans",
        json={
            "lender_name": "Chacha Rashid", "loan_type": "personal",
            "principal": 120000, "interest_rate": 0, "tenure_months": 12,
        },
    )
    assert created.status_code == 201, created.text
    assert Decimal(created.json()["emi_amount"]) == Decimal("10000.00")
    assert created.json()["interest_type"] == "none"


@pytest.mark.asyncio
async def test_the_repayment_schedule_can_be_read_in_full(shop):
    client = shop["client"]
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Bank Alfalah", "principal": 240000, "interest_rate": 12,
                "tenure_months": 12, "start_date": "2026-01-15",
            },
        )
    ).json()

    rows = (await client.get(f"/finance/loans/{loan['id']}/schedule")).json()
    assert len(rows) == 12
    assert rows[0]["due_date"] == "2026-02-15"
    assert Decimal(rows[-1]["balance_after"]) == Decimal("0.00")
    assert sum(Decimal(r["principal"]) for r in rows) == Decimal("240000.00")


@pytest.mark.asyncio
async def test_a_repayment_is_split_into_debt_and_interest(shop):
    """Only the interest half is an expense. Booking the whole instalment as
    one understates profit by the principal every month."""
    client = shop["client"]
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Soneri Bank", "principal": 100000, "interest_rate": 12,
                "tenure_months": 12,
            },
        )
    ).json()

    paid = await client.post(
        f"/finance/loans/{loan['id']}/payments", json={"amount": 10000}
    )
    assert paid.status_code == 201, paid.text
    body = paid.json()

    assert Decimal(body["interest_component"]) == Decimal("1000.00")   # one month at 1%
    assert Decimal(body["principal_component"]) == Decimal("9000.00")
    assert Decimal(body["balance_after"]) == Decimal("91000.00")


@pytest.mark.asyncio
async def test_repaying_a_loan_in_full_closes_it(shop):
    client = shop["client"]
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Ammi", "loan_type": "personal",
                "principal": 50000, "interest_rate": 0, "tenure_months": 5,
            },
        )
    ).json()

    paid = await client.post(
        f"/finance/loans/{loan['id']}/payments", json={"amount": 50000}
    )
    assert paid.status_code == 201, paid.text

    after = (await client.get(f"/finance/loans/{loan['id']}")).json()
    assert after["status"] == "closed"
    assert Decimal(after["outstanding_principal"]) == Decimal("0.00")


@pytest.mark.asyncio
async def test_paying_more_than_is_owed_is_refused_rather_than_absorbed(shop):
    """An overpaid loan hides a keying error nobody goes looking for."""
    client = shop["client"]
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Khala Nasreen", "loan_type": "personal",
                "principal": 20000, "interest_rate": 0, "tenure_months": 4,
            },
        )
    ).json()

    too_much = await client.post(
        f"/finance/loans/{loan['id']}/payments", json={"amount": 25000}
    )
    assert too_much.status_code == 422, too_much.text
    assert "20000" in too_much.json()["error"]["message"]


@pytest.mark.asyncio
async def test_undoing_a_repayment_restores_what_is_owed(shop):
    client = shop["client"]
    account = await _account(client, "Repayment Account", "bank", opening=100000)
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Silk Bank", "principal": 80000, "interest_rate": 0,
                "tenure_months": 8,
            },
        )
    ).json()

    paid = (
        await client.post(
            f"/finance/loans/{loan['id']}/payments",
            json={"amount": 10000, "account_id": account["id"]},
        )
    ).json()
    assert await _balance(client, account["id"]) == Decimal("90000.00")

    undone = await client.delete(f"/finance/loans/{loan['id']}/payments/{paid['id']}")
    assert undone.status_code == 200, undone.text

    after = (await client.get(f"/finance/loans/{loan['id']}")).json()
    assert Decimal(after["outstanding_principal"]) == Decimal("80000.00")
    assert await _balance(client, account["id"]) == Decimal("100000.00")


@pytest.mark.asyncio
async def test_undoing_the_last_repayment_reopens_a_closed_loan(shop):
    client = shop["client"]
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Bhai Jaan", "loan_type": "personal",
                "principal": 15000, "interest_rate": 0, "tenure_months": 3,
            },
        )
    ).json()

    paid = (
        await client.post(f"/finance/loans/{loan['id']}/payments", json={"amount": 15000})
    ).json()
    assert (await client.get(f"/finance/loans/{loan['id']}")).json()["status"] == "closed"

    await client.delete(f"/finance/loans/{loan['id']}/payments/{paid['id']}")
    assert (await client.get(f"/finance/loans/{loan['id']}")).json()["status"] == "active"


@pytest.mark.asyncio
async def test_a_loan_with_repayments_against_it_cannot_be_deleted(shop):
    client = shop["client"]
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Summit Bank", "principal": 40000, "interest_rate": 0,
                "tenure_months": 4,
            },
        )
    ).json()
    await client.post(f"/finance/loans/{loan['id']}/payments", json={"amount": 5000})

    refused = await client.delete(f"/finance/loans/{loan['id']}")
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_the_loan_summary_adds_up_what_is_owed(shop):
    client = shop["client"]
    for lender, principal in (("Bank A", 100000), ("Bank B", 250000)):
        await client.post(
            "/finance/loans",
            json={
                "lender_name": lender, "principal": principal, "interest_rate": 0,
                "tenure_months": 10,
            },
        )

    summary = (await client.get("/finance/loans/summary")).json()
    assert summary["active_count"] >= 2
    assert Decimal(summary["total_outstanding"]) >= Decimal("350000")
    assert Decimal(summary["monthly_commitment"]) >= Decimal("35000")


@pytest.mark.asyncio
async def test_a_loan_settled_in_full_no_longer_counts_as_outstanding(shop):
    client = shop["client"]
    loan = (
        await client.post(
            "/finance/loans",
            json={
                "lender_name": "Closed Bank", "principal": 30000, "interest_rate": 0,
                "tenure_months": 3,
            },
        )
    ).json()
    before = Decimal((await client.get("/finance/loans/summary")).json()["total_outstanding"])

    await client.post(f"/finance/loans/{loan['id']}/payments", json={"amount": 30000})

    after = Decimal((await client.get("/finance/loans/summary")).json()["total_outstanding"])
    assert after == before - Decimal("30000")
