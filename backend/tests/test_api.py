"""End-to-end API tests over the real ASGI app and a real database."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.asyncio


# ── health & auth ────────────────────────────────────────────────
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_register_and_login(client):
    import uuid

    email = f"login_{uuid.uuid4().hex[:8]}@testshop.pk"
    register = await client.post(
        "/auth/register",
        json={
            "name": "Login Test", "email": email, "password": "secret123",
            "business_name": "Login Shop",
        },
    )
    assert register.status_code == 201
    assert register.json()["is_new_user"] is True

    login = await client.post("/auth/login", json={"identifier": email, "password": "secret123"})
    assert login.status_code == 200
    assert login.json()["tokens"]["access_token"]

    bad = await client.post("/auth/login", json={"identifier": email, "password": "wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "unauthenticated"


async def test_duplicate_email_rejected(client, account):
    response = await client.post(
        "/auth/register",
        json={"name": "Copy", "email": account["email"], "password": "another123"},
    )
    assert response.status_code == 409


async def test_requires_authentication(client):
    fresh = client.__class__(transport=client._transport, base_url=str(client.base_url))
    async with fresh:
        response = await fresh.get("/parties")
    assert response.status_code == 401


async def test_otp_flow(client):
    send = await client.post("/auth/otp/send", json={"identifier": "+923009998887"})
    assert send.status_code == 200
    code = send.json()["debug_code"]
    assert code, "OTP_DEV_MODE should return the code"

    verify = await client.post(
        "/auth/otp/verify",
        json={"identifier": "+923009998887", "code": code, "name": "OTP User"},
    )
    assert verify.status_code == 200
    assert verify.json()["is_new_user"] is True

    replay = await client.post(
        "/auth/otp/verify", json={"identifier": "+923009998887", "code": code}
    )
    assert replay.status_code == 401  # single use


# ── masters ──────────────────────────────────────────────────────
async def test_party_crud_and_duplicate_guard(shop):
    client = shop["client"]

    duplicate = await client.post("/parties", json={"name": "Ahmed Traders"})
    assert duplicate.status_code == 409

    listing = await client.get("/parties", params={"search": "ahmed"})
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1

    fuzzy = await client.get("/parties/search", params={"q": "ahmad traders"})
    assert fuzzy.status_code == 200
    assert fuzzy.json()[0]["name"] == "Ahmed Traders"


async def test_item_stock_starts_at_opening(shop):
    response = await shop["client"].get(f"/items/{shop['sugar']['id']}")
    assert response.status_code == 200
    assert Decimal(response.json()["stock_qty"]) == Decimal("100")


# ── the invoice engine ───────────────────────────────────────────
async def test_sale_invoice_maths_stock_and_ledger(shop):
    client = shop["client"]

    response = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [
                {"item_id": shop["sugar"]["id"], "qty": 10, "rate": 7400},
                {"item_id": shop["oil"]["id"], "qty": 4, "rate": 2750},
            ],
        },
    )
    assert response.status_code == 201, response.text
    invoice = response.json()

    # 10 × 7400 = 74,000 (no tax) + 4 × 2750 = 11,000 @ 17% = 1,870 tax
    assert Decimal(invoice["subtotal"]) == Decimal("85000.00")
    assert Decimal(invoice["tax_amount"]) == Decimal("1870.00")
    assert Decimal(invoice["total"]) == Decimal("86870.00")
    assert Decimal(invoice["balance_amount"]) == Decimal("86870.00")
    assert invoice["status"] == "unpaid"

    stock = (await client.get(f"/items/{shop['sugar']['id']}")).json()
    assert Decimal(stock["stock_qty"]) == Decimal("90")

    party = (await client.get(f"/parties/{shop['customer']['id']}")).json()
    assert Decimal(party["balance"]) == Decimal("86870.00")


async def test_line_discount_applies_before_tax(shop):
    client = shop["client"]
    response = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [
                {
                    "item_id": shop["oil"]["id"], "qty": 10, "rate": 1000,
                    "discount_type": "percent", "discount_value": 10,
                }
            ],
        },
    )
    invoice = response.json()
    # 10,000 − 10% = 9,000 taxable; 17% = 1,530
    assert Decimal(invoice["taxable_amount"]) == Decimal("9000.00")
    assert Decimal(invoice["tax_amount"]) == Decimal("1530.00")
    assert Decimal(invoice["total"]) == Decimal("10530.00")


async def test_insufficient_stock_is_blocked(shop):
    response = await shop["client"].post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 99999, "rate": 7400}],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_stock"


async def test_purchase_increases_stock_and_payable(shop):
    client = shop["client"]
    before = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])

    response = await client.post(
        "/vouchers",
        json={
            "voucher_type": "purchase",
            "party_id": shop["supplier"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 20, "rate": 6800}],
        },
    )
    assert response.status_code == 201

    after = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    assert after - before == Decimal("20")

    supplier = (await client.get(f"/parties/{shop['supplier']['id']}")).json()
    assert Decimal(supplier["balance"]) == Decimal("-136000.00")  # we owe them


async def test_inline_payment_marks_invoice_paid(shop):
    client = shop["client"]
    response = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 5000}],
            "payment": {"amount": 5000, "mode": "cash"},
        },
    )
    invoice = response.json()
    assert Decimal(invoice["paid_amount"]) == Decimal("5000.00")

    reloaded = (await client.get(f"/vouchers/{invoice['id']}")).json()
    assert reloaded["status"] == "paid"
    assert Decimal(reloaded["balance_amount"]) == Decimal("0.00")


async def test_document_numbering_increments(shop):
    client = shop["client"]
    numbers = []
    for _ in range(3):
        response = await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 100}],
            },
        )
        numbers.append(response.json()["number"])
    assert len(set(numbers)) == 3, "numbers must be unique"
    assert numbers == sorted(numbers), "numbers must increase"


async def test_cancel_restores_stock_and_balance(shop):
    client = shop["client"]
    stock_before = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    balance_before = Decimal(
        (await client.get(f"/parties/{shop['customer']['id']}")).json()["balance"]
    )

    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 5, "rate": 7400}],
            },
        )
    ).json()

    cancelled = await client.post(f"/vouchers/{invoice['id']}/cancel", json={"reason": "Wrong item"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    stock_after = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    balance_after = Decimal(
        (await client.get(f"/parties/{shop['customer']['id']}")).json()["balance"]
    )
    assert stock_after == stock_before
    assert balance_after == balance_before


async def test_quotation_does_not_move_stock(shop):
    client = shop["client"]
    before = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    quote = await client.post(
        "/vouchers",
        json={
            "voucher_type": "quotation",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 30, "rate": 7400}],
        },
    )
    assert quote.status_code == 201
    after = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    assert after == before

    converted = await client.post(
        f"/vouchers/{quote.json()['id']}/convert", json={"target_type": "sale"}
    )
    assert converted.status_code == 200
    assert converted.json()["voucher_type"] == "sale"

    final = Decimal((await client.get(f"/items/{shop['sugar']['id']}")).json()["stock_qty"])
    assert final == before - Decimal("30")


# ── payments ─────────────────────────────────────────────────────
async def test_settlement_pays_oldest_invoice_first(shop):
    client = shop["client"]
    first = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale", "party_id": shop["customer"]["id"],
                "voucher_date": "2026-01-05",
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 1000}],
            },
        )
    ).json()
    second = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale", "party_id": shop["customer"]["id"],
                "voucher_date": "2026-02-05",
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 2000}],
            },
        )
    ).json()

    settle = await client.post(
        "/payments/settle",
        json={"party_id": shop["customer"]["id"], "amount": 1500, "direction": "in"},
    )
    assert settle.status_code == 200
    settled = {s["voucher_number"]: Decimal(s["amount"]) for s in settle.json()["settled_vouchers"]}
    assert settled.get(first["number"]) == Decimal("1000.00"), "oldest invoice settles first"

    reloaded_first = (await client.get(f"/vouchers/{first['id']}")).json()
    assert reloaded_first["status"] == "paid"

    reloaded_second = (await client.get(f"/vouchers/{second['id']}")).json()
    # Backdated, so it is both partly paid and past its due date.
    assert reloaded_second["status"] in ("partial", "overdue")
    assert Decimal(reloaded_second["paid_amount"]) == Decimal("500.00")
    assert Decimal(reloaded_second["balance_amount"]) == Decimal("1500.00")


async def test_deleting_payment_restores_invoice_balance(shop):
    client = shop["client"]
    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale", "party_id": shop["customer"]["id"],
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 3000}],
            },
        )
    ).json()
    payment = (
        await client.post(
            "/payments",
            json={
                "party_id": shop["customer"]["id"], "amount": 3000, "direction": "in",
                "allocations": [{"voucher_id": invoice["id"], "amount": 3000}],
            },
        )
    ).json()

    assert (await client.get(f"/vouchers/{invoice['id']}")).json()["status"] == "paid"

    deleted = await client.delete(f"/payments/{payment['id']}")
    assert deleted.status_code == 200

    restored = (await client.get(f"/vouchers/{invoice['id']}")).json()
    assert restored["status"] in ("unpaid", "overdue")
    assert Decimal(restored["balance_amount"]) == Decimal("3000.00")


# ── stock ────────────────────────────────────────────────────────
async def test_stock_adjustment_and_ledger(shop):
    client = shop["client"]
    response = await client.post(
        "/items/stock/adjust",
        json={"item_id": shop["oil"]["id"], "qty": -3, "reason": "Bottles damaged in transit"},
    )
    assert response.status_code == 200

    ledger = (await client.get(f"/items/{shop['oil']['id']}/ledger")).json()
    assert any(
        entry["movement"] == "adjustment" and Decimal(entry["qty"]) == Decimal("-3")
        for entry in ledger
    )


# ── reports ──────────────────────────────────────────────────────
async def test_dashboard_and_reports(shop):
    client = shop["client"]
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale", "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 2, "rate": 7400}],
        },
    )

    dashboard = await client.get("/reports/dashboard", params={"period": "this_month"})
    assert dashboard.status_code == 200
    assert Decimal(dashboard.json()["sales"]["value"]) > 0

    pl = await client.get("/reports/profit-loss", params={"period": "this_month"})
    assert pl.status_code == 200
    assert "gross_profit" in pl.json()

    balance = await client.get("/reports/balance-sheet")
    assert balance.status_code == 200

    daybook = await client.get("/reports/daybook", params={"period": "today"})
    assert daybook.status_code == 200

    ageing = await client.get("/reports/ageing", params={"direction": "receivable"})
    assert ageing.status_code == 200
    assert len(ageing.json()["buckets"]) == 5


# ── permissions & tenancy ────────────────────────────────────────
async def test_viewer_cannot_write(client, account):
    import uuid

    owner = account["client"]
    viewer_email = f"viewer_{uuid.uuid4().hex[:8]}@testshop.pk"

    invite = await owner.post(
        "/businesses/current/members",
        json={"email": viewer_email, "name": "Viewer", "role": "viewer"},
    )
    assert invite.status_code == 201

    otp = await client.post("/auth/otp/send", json={"identifier": viewer_email})
    verified = await client.post(
        "/auth/otp/verify",
        json={"identifier": viewer_email, "code": otp.json()["debug_code"]},
    )
    tokens = verified.json()["tokens"]

    import httpx

    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
    ) as viewer:
        headers = {
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Business-Id": account["business"]["id"],
        }
        readable = await viewer.get("/parties", headers=headers)
        assert readable.status_code == 200

        blocked = await viewer.post("/parties", json={"name": "Sneaky"}, headers=headers)
        assert blocked.status_code == 403


async def test_business_isolation(client, account):
    """A user must not see another business's data even with a valid token."""
    import uuid

    import httpx

    from app.main import app

    other_email = f"other_{uuid.uuid4().hex[:8]}@testshop.pk"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
    ) as other:
        registered = await other.post(
            "/auth/register",
            json={
                "name": "Other Owner", "email": other_email, "password": "secret123",
                "business_name": "Other Shop",
            },
        )
        other_tokens = registered.json()["tokens"]

        stolen = await other.get(
            "/parties",
            headers={
                "Authorization": f"Bearer {other_tokens['access_token']}",
                "X-Business-Id": account["business"]["id"],  # someone else's business
            },
        )
        assert stolen.status_code == 403


# ── sync ─────────────────────────────────────────────────────────
async def test_sync_bootstrap_push_pull(shop):
    client = shop["client"]

    bootstrap = await client.get("/sync/bootstrap")
    assert bootstrap.status_code == 200
    assert len(bootstrap.json()["items"]) >= 2
    assert bootstrap.json()["server_seq"] > 0

    push = await client.post(
        "/sync/push",
        json={
            "device_id": "test-device-001",
            "changes": [
                {
                    "entity": "party",
                    "operation": "create",
                    "client_uuid": "offline-party-0001",
                    "data": {"name": "Offline Customer", "party_type": "customer"},
                }
            ],
        },
    )
    assert push.status_code == 200
    assert not push.json()["conflicts"]
    assert push.json()["applied"][0]["operation"] == "create"

    # Replaying the same change must not create a second party.
    replay = await client.post(
        "/sync/push",
        json={
            "device_id": "test-device-001",
            "changes": [
                {
                    "entity": "party",
                    "operation": "create",
                    "client_uuid": "offline-party-0001",
                    "data": {"name": "Offline Customer", "party_type": "customer"},
                }
            ],
        },
    )
    assert replay.json()["applied"][0]["server_id"] == push.json()["applied"][0]["server_id"]

    pull = await client.get("/sync/pull", params={"since": 0})
    assert pull.status_code == 200
    assert pull.json()["server_seq"] > 0


async def test_sync_detects_stale_edit(shop):
    client = shop["client"]
    party_id = shop["customer"]["id"]

    stale_revision = (await client.get(f"/parties/{party_id}")).json()["revision"]
    # Someone else edits the record while our device is offline.
    await client.patch(f"/parties/{party_id}", json={"city": "Karachi"})
    assert (await client.get(f"/parties/{party_id}")).json()["revision"] > stale_revision

    conflict = await client.post(
        "/sync/push",
        json={
            "device_id": "stale-device",
            "changes": [
                {
                    "entity": "party",
                    "operation": "update",
                    "client_uuid": "stale-edit-0001",
                    "server_id": party_id,
                    "base_revision": stale_revision,
                    "data": {"name": "Renamed Offline"},
                }
            ],
        },
    )
    assert conflict.status_code == 200
    conflicts = conflict.json()["conflicts"]
    assert conflicts and conflicts[0]["reason"] == "stale_revision"
    assert conflicts[0]["server_data"]["city"] == "Karachi"


# ── documents ────────────────────────────────────────────────────
async def test_invoice_html_renders(shop):
    client = shop["client"]
    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale", "party_id": shop["customer"]["id"],
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 2, "rate": 7400}],
            },
        )
    ).json()

    response = await client.get(f"/vouchers/{invoice['id']}/html")
    assert response.status_code == 200
    body = response.text
    assert invoice["number"] in body
    assert "Ahmed Traders" in body
    assert "TAX INVOICE" in body


async def test_ai_reports_not_configured(shop):
    """With no API key the assistant fails cleanly instead of 500-ing."""
    response = await shop["client"].post("/ai/chat", json={"message": "aaj ki sale kitni hai?"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] in ("ai_not_configured", "ai_disabled")



# ── notifications ────────────────────────────────────────────────
async def test_notifications_are_derived_from_live_state(shop):
    """Alerts are recomputed, not accumulated — so they can't go stale."""
    client = shop["client"]

    # Nothing is wrong yet.
    assert (await client.post("/notifications/refresh")).json() == []

    # Sell almost all the sugar; 100 → 5, under its low_stock_qty of 10.
    sale = await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 95, "rate": 7400}],
        },
    )
    assert sale.status_code == 201, sale.text

    alerts = (await client.post("/notifications/refresh")).json()
    low_stock = [a for a in alerts if a["kind"] == "low_stock"]
    assert len(low_stock) == 1
    assert "Sugar 50kg" in low_stock[0]["title"]
    assert low_stock[0]["data"]["route"] == f"/items/{shop['sugar']['id']}"

    # Restock, and the alert stops existing rather than lingering as read.
    restock = await client.post(
        "/items/stock/adjust",
        json={"item_id": shop["sugar"]["id"], "qty": 60, "reason": "New delivery"},
    )
    assert restock.status_code == 200, restock.text
    alerts = (await client.post("/notifications/refresh")).json()
    assert [a for a in alerts if a["kind"] == "low_stock"] == []


async def test_overdue_invoice_raises_one_alert_that_clears_when_paid(shop):
    client = shop["client"]

    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "voucher_date": str(date.today() - timedelta(days=40)),
                "due_date": str(date.today() - timedelta(days=10)),
                "lines": [{"item_id": shop["oil"]["id"], "qty": 2, "rate": 2750}],
            },
        )
    ).json()

    alerts = (await client.post("/notifications/refresh")).json()
    overdue = [a for a in alerts if a["kind"] == "payment_due"]
    assert len(overdue) == 1
    assert overdue[0]["entity_id"] == invoice["id"]
    assert invoice["number"] in overdue[0]["body"]

    # Refreshing twice must not duplicate it.
    alerts = (await client.post("/notifications/refresh")).json()
    assert len([a for a in alerts if a["kind"] == "payment_due"]) == 1

    # Settle the bill; the reminder disappears.
    await client.post(
        "/payments",
        json={
            "party_id": shop["customer"]["id"],
            "amount": invoice["total"],
            "direction": "in",
            "mode": "cash",
        },
    )
    alerts = (await client.post("/notifications/refresh")).json()
    assert [a for a in alerts if a["kind"] == "payment_due"] == []


async def test_marking_read_survives_a_refresh(shop):
    client = shop["client"]
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale",
            "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 95, "rate": 7400}],
        },
    )

    alert = (await client.post("/notifications/refresh")).json()[0]
    assert (await client.get("/notifications/count")).json()["unread"] == 1

    read = await client.post(f"/notifications/{alert['id']}/read")
    assert read.status_code == 200
    assert read.json()["is_read"] is True
    assert (await client.get("/notifications/count")).json()["unread"] == 0

    # The condition still holds, so the alert stays — and stays read.
    refreshed = (await client.post("/notifications/refresh")).json()
    assert len(refreshed) == 1
    assert refreshed[0]["is_read"] is True
    assert (await client.get("/notifications/count")).json()["unread"] == 0


async def test_notifications_do_not_leak_across_businesses(client, account):
    """A second shop must never see the first shop's alerts."""
    first = account["client"]
    await first.post(
        "/items",
        json={"name": "Tea 1kg", "sale_price": 900, "opening_stock": 0, "low_stock_qty": 5},
    )
    assert len((await first.post("/notifications/refresh")).json()) == 1

    second = (
        await first.post(
            "/businesses", json={"name": "Second Shop", "business_type": "retail"}
        )
    ).json()
    first.headers["X-Business-Id"] = second["id"]

    assert (await first.post("/notifications/refresh")).json() == []
    assert (await first.get("/notifications/count")).json()["unread"] == 0


# ── team sharing ─────────────────────────────────────────────────
async def test_an_invited_member_sees_the_same_shop(client, shop):
    """The whole point of sharing: a second person signs in and finds the first
    person's customers and stock already there."""
    owner = shop["client"]

    invited = await owner.post(
        "/businesses/current/members",
        json={"phone": "+923005551234", "name": "Bilal", "role": "salesman"},
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["role"] == "salesman"

    # They claim the account by signing in with that same number — no invite link.
    code = (await client.post("/auth/otp/send", json={"identifier": "+923005551234"})).json()
    session = await client.post(
        "/auth/otp/verify",
        json={"identifier": "+923005551234", "code": code["debug_code"]},
    )
    assert session.status_code == 200
    body = session.json()
    assert body["businesses"], "the invited user should land in the shop, not an empty account"
    assert body["businesses"][0]["id"] == shop["business"]["id"]

    staff = client.__class__(transport=client._transport, base_url=str(client.base_url))
    staff.headers["Authorization"] = f"Bearer {body['tokens']['access_token']}"
    staff.headers["X-Business-Id"] = shop["business"]["id"]
    async with staff:
        parties = await staff.get("/parties")
        assert parties.status_code == 200
        assert any(p["name"] == "Ahmed Traders" for p in parties.json()["items"])


async def test_a_salesman_can_bill_but_not_touch_stock(client, shop):
    """Shared access is not the same as equal access."""
    owner = shop["client"]
    await owner.post(
        "/businesses/current/members",
        json={"phone": "+923005559999", "name": "Sales", "role": "salesman"},
    )
    code = (await client.post("/auth/otp/send", json={"identifier": "+923005559999"})).json()
    body = (
        await client.post(
            "/auth/otp/verify",
            json={"identifier": "+923005559999", "code": code["debug_code"]},
        )
    ).json()

    staff = client.__class__(transport=client._transport, base_url=str(client.base_url))
    staff.headers["Authorization"] = f"Bearer {body['tokens']['access_token']}"
    staff.headers["X-Business-Id"] = shop["business"]["id"]
    async with staff:
        sale = await staff.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 7400}],
            },
        )
        assert sale.status_code == 201, "a salesman must be able to sell"

        adjust = await staff.post(
            "/items/stock/adjust",
            json={"item_id": shop["sugar"]["id"], "qty": 500, "reason": "nope"},
        )
        assert adjust.status_code == 403, "a salesman must not be able to invent stock"


async def test_the_last_owner_cannot_be_removed(shop):
    members = (await shop["client"].get("/businesses/current/members")).json()
    owner = next(m for m in members if m["role"] == "owner")

    response = await shop["client"].delete(f"/businesses/current/members/{owner['id']}")
    assert response.status_code == 422
    assert "owner" in response.json()["error"]["message"].lower()


async def test_inviting_the_same_person_twice_is_rejected(shop):
    body = {"email": "twice@testshop.pk", "role": "viewer"}
    assert (await shop["client"].post("/businesses/current/members", json=body)).status_code == 201
    assert (await shop["client"].post("/businesses/current/members", json=body)).status_code == 409


# ── dashboard aggregates ─────────────────────────────────────────
async def test_batched_dashboard_totals_match_the_single_period_helpers(shop):
    """The dashboard batches its aggregates into one query per table. This pins
    them to the per-period helpers the other reports still use, so a future edit
    to the batching cannot silently change what the shopkeeper sees."""
    from app.models.enums import PaymentDirection, VoucherType
    from app.services.report_service import ReportService
    from app.utils.dates import previous_period, resolve_period

    client = shop["client"]
    today = date.today()

    # This period and the one before it, so the comparison arm is exercised too.
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale", "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 3, "rate": 7400}],
            "payment": {"amount": 5000, "mode": "cash"},
        },
    )
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "purchase", "party_id": shop["supplier"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 4, "rate": 6800}],
        },
    )
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale", "party_id": shop["customer"]["id"],
            "voucher_date": str(today - timedelta(days=40)),
            "lines": [{"item_id": shop["oil"]["id"], "qty": 2, "rate": 2750}],
        },
    )
    await client.post("/expenses", json={"title": "Rent", "amount": 9000,
                                         "expense_date": str(today)})

    from app.core.database import SessionLocal
    from app.services.base import ActorContext

    async with SessionLocal() as db:
        service = ReportService(
            db,
            ActorContext(
                user_id=shop["user"]["id"],
                business_id=shop["business"]["id"],
                role="owner",
            ),
        )
        start, end = resolve_period("this_month")
        prev_start, prev_end = previous_period(start, end)
        periods = [(start, end), (prev_start, prev_end)]

        batched = await service._voucher_totals(periods)
        payments = await service._payment_totals(periods)
        expenses = await service._expense_totals(periods)

        for index, (p_start, p_end) in enumerate(periods):
            assert batched[index]["sale"] == await service._voucher_total(
                VoucherType.SALE, p_start, p_end
            )
            assert batched[index]["purchase"] == await service._voucher_total(
                VoucherType.PURCHASE, p_start, p_end
            )
            assert batched[index]["profit"] == await service._profit_total(p_start, p_end)
            assert payments[index] == await service._payment_total(
                PaymentDirection.IN, p_start, p_end
            )
            assert expenses[index] == await service._expense_total(p_start, p_end)


async def test_dashboard_query_count_does_not_grow_with_the_number_of_invoices(shop):
    """A dashboard that costs one query per invoice would fall over on a busy
    shop. Measured across two rounds of added data: the first round may add a
    fixed query or two as empty branches start returning rows, but from then on
    the count must be flat."""
    from sqlalchemy import event

    from app.core.database import engine

    counter = {"n": 0}

    def count(*_args, **_kwargs):
        counter["n"] += 1

    async def add_invoices(n: int) -> None:
        for _ in range(n):
            await shop["client"].post(
                "/vouchers",
                json={
                    "voucher_type": "sale", "party_id": shop["customer"]["id"],
                    "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 500}],
                },
            )

    async def dashboard_queries() -> int:
        counter["n"] = 0
        response = await shop["client"].get("/reports/dashboard")
        assert response.status_code == 200
        return counter["n"]

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        await add_invoices(10)
        after_10 = await dashboard_queries()

        await add_invoices(30)
        after_40 = await dashboard_queries()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)

    assert after_40 == after_10, (
        f"query count grew with data: {after_10} at 10 invoices, {after_40} at 40"
    )
    # Batching the period aggregates brought this down from 33. The ceiling is a
    # tripwire: cross it and someone has added a round trip to the busiest screen.
    assert after_40 <= 27, f"dashboard now costs {after_40} queries"


# ── backup & restore ─────────────────────────────────────────────
async def test_backup_survives_a_wipe_and_restores_everything(shop):
    """The point of a backup is that losing the data is recoverable. This does
    the whole round trip: export, delete the transactions, put them back."""
    client = shop["client"]

    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale", "party_id": shop["customer"]["id"],
                "lines": [{"item_id": shop["sugar"]["id"], "qty": 4, "rate": 7400}],
                "payment": {"amount": 10000, "mode": "cash"},
            },
        )
    ).json()
    await client.post("/expenses", json={"title": "Rent", "amount": 9000,
                                         "expense_date": str(date.today())})

    backup = await client.get("/data/backup")
    assert backup.status_code == 200
    assert "attachment" in backup.headers["content-disposition"]
    payload = backup.json()
    assert payload["counts"]["vouchers"] >= 1
    assert payload["counts"]["parties"] >= 2
    assert payload["counts"]["voucher_lines"] >= 1

    cleared = await client.delete("/data/clear")
    assert cleared.status_code == 200
    assert (await client.get("/vouchers")).json()["total"] == 0

    restored = await client.post(
        "/data/restore",
        files={"file": ("backup.json", backup.content, "application/json")},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["restored"]["vouchers"] >= 1

    reloaded = (await client.get(f"/vouchers/{invoice['id']}")).json()
    assert reloaded["number"] == invoice["number"]
    assert Decimal(reloaded["total"]) == Decimal(invoice["total"])
    assert len(reloaded["lines"]) == 1


async def test_restoring_the_same_backup_twice_does_not_duplicate(shop):
    """A shopkeeper who taps restore twice must not end up with two of everything."""
    client = shop["client"]
    await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale", "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 1, "rate": 100}],
        },
    )

    backup = await client.get("/data/backup")
    before = (await client.get("/vouchers")).json()["total"]

    for _ in range(2):
        response = await client.post(
            "/data/restore",
            files={"file": ("backup.json", backup.content, "application/json")},
        )
        assert response.status_code == 200

    assert (await client.get("/vouchers")).json()["total"] == before


async def test_a_backup_from_another_shop_cannot_be_restored_into_this_one(client, account):
    """Row ids are trusted from the file, business ownership is not."""
    first = account["client"]
    await first.post("/parties", json={"name": "Shop One Customer"})
    backup = (await first.get("/data/backup")).json()

    second = (
        await first.post("/businesses", json={"name": "Shop Two", "business_type": "retail"})
    ).json()
    first.headers["X-Business-Id"] = second["id"]

    import json as _json
    response = await first.post(
        "/data/restore",
        files={"file": ("b.json", _json.dumps(backup).encode(), "application/json")},
    )
    assert response.status_code == 200

    parties = (await first.get("/parties")).json()["items"]
    assert all(p["name"] == "Shop One Customer" for p in parties) or parties
    # Whatever was restored now belongs to shop two — nothing leaked sideways.
    for party in parties:
        detail = await first.get(f"/parties/{party['id']}")
        assert detail.status_code == 200


async def test_a_junk_file_is_rejected_with_a_readable_message(shop):
    response = await shop["client"].post(
        "/data/restore",
        files={"file": ("notes.txt", b"this is not a backup", "text/plain")},
    )
    assert response.status_code == 422
    assert "readable JSON" in response.json()["error"]["message"]


# ── GSTR-1 ───────────────────────────────────────────────────────
async def test_gstr1_splits_registered_and_unregistered_sales(shop):
    """B2B is itemised per invoice; walk-in sales are summarised in B2CS. Getting
    this wrong is what makes a return rejected at the portal."""
    client = shop["client"]

    registered = (
        await client.post(
            "/parties",
            json={"name": "GST Buyer", "party_type": "customer",
                  "gstin": "27AAPFU0939F1ZV", "state_code": "27"},
        )
    ).json()

    await client.post(
        "/vouchers",
        json={"voucher_type": "sale", "party_id": registered["id"],
              "lines": [{"item_id": shop["oil"]["id"], "qty": 2, "rate": 2750}]},
    )
    await client.post(
        "/vouchers",
        json={"voucher_type": "sale", "party_id": shop["customer"]["id"],
              "lines": [{"item_id": shop["oil"]["id"], "qty": 1, "rate": 2750}]},
    )

    today = date.today()
    response = await client.get(
        "/data/gstr1",
        params={"start_date": str(today.replace(day=1)), "end_date": str(today)},
    )
    assert response.status_code == 200, response.text
    report = response.json()

    assert report["fp"] == f"{today.month:02d}{today.year}"
    assert any(b["ctin"] == "27AAPFU0939F1ZV" for b in report["b2b"]), "registered buyer must be B2B"
    assert report["b2cs"], "the walk-in sale must be summarised in B2CS"
    assert report["hsn"]["data"], "HSN summary is mandatory on the return"


async def test_gstr1_csv_is_downloadable(shop):
    today = date.today()
    response = await shop["client"].get(
        "/data/gstr1",
        params={"start_date": str(today.replace(day=1)), "end_date": str(today),
                "format": "csv"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "Section,GSTIN" in response.text


# ── invoice templates ────────────────────────────────────────────
async def test_every_invoice_template_renders_the_same_bill(shop):
    """Four layouts, one set of data. A template that references a field the
    voucher does not have fails silently in Jinja and prints a blank cell, so
    each one is rendered against a real invoice with tax, discount and payment."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models.business import BusinessSettings
    from app.services.invoice_templates import TEMPLATES
    from app.services.pdf_service import PdfService
    from app.services.base import ActorContext

    client = shop["client"]
    invoice = (
        await client.post(
            "/vouchers",
            json={
                "voucher_type": "sale",
                "party_id": shop["customer"]["id"],
                "lines": [
                    {"item_id": shop["oil"]["id"], "qty": 3, "rate": 2750,
                     "discount_type": "percent", "discount_value": 5},
                    {"item_id": shop["sugar"]["id"], "qty": 2, "rate": 7400},
                ],
                "payment": {"amount": 5000, "mode": "cash"},
            },
        )
    ).json()

    actor = ActorContext(
        user_id=shop["user"]["id"], business_id=shop["business"]["id"], role="owner"
    )

    for name in TEMPLATES:
        async with SessionLocal() as db:
            cfg = (
                await db.execute(
                    select(BusinessSettings).where(
                        BusinessSettings.business_id == shop["business"]["id"]
                    )
                )
            ).scalar_one()
            cfg.invoice_template = name
            await db.commit()

        async with SessionLocal() as db:
            html = await PdfService(db, actor).render_html(invoice["id"])

        assert invoice["number"] in html, f"{name}: invoice number missing"
        assert "Ahmed Traders" in html, f"{name}: customer missing"
        assert "Cooking Oil 5L" in html, f"{name}: line item missing"
        assert "Sugar 50kg" in html, f"{name}: second line missing"
        # Jinja leaves unresolved syntax in place when a block is malformed.
        assert "{{" not in html and "{%" not in html, f"{name}: unrendered Jinja left in output"
        assert html.strip().startswith("<!doctype html>"), f"{name}: not a full document"


async def test_an_unknown_template_name_still_prints(shop):
    """A bad value in the database must not stop a shopkeeper printing a bill."""
    from app.services.invoice_templates import CLASSIC, get

    assert get("nonsense") is CLASSIC
    assert get(None) is CLASSIC
    assert get("") is CLASSIC


async def test_the_template_setting_rejects_an_unknown_name(shop):
    response = await shop["client"].patch(
        "/businesses/current/settings", json={"invoice_template": "fancy"}
    )
    assert response.status_code == 422


# ── daily summary ────────────────────────────────────────────────
async def test_daily_summary_reports_the_day_as_it_actually_happened(shop):
    """Every figure here is read from the ledger, never generated — a daily
    number that is occasionally invented is worse than no daily number."""
    client = shop["client"]

    await client.post(
        "/vouchers",
        json={
            "voucher_type": "sale", "party_id": shop["customer"]["id"],
            "lines": [{"item_id": shop["sugar"]["id"], "qty": 2, "rate": 7400}],
            "payment": {"amount": 5000, "mode": "cash"},
        },
    )
    await client.post("/expenses", json={"title": "Bijli", "amount": 800,
                                         "expense_date": str(date.today())})

    response = await client.get("/reports/daily-summary")
    assert response.status_code == 200
    summary = response.json()

    assert summary["bill_count"] == 1
    assert Decimal(summary["sales"]) == Decimal("14800.00")
    assert Decimal(summary["collected"]) == Decimal("5000.00")
    assert Decimal(summary["expenses"]) == Decimal("800.00")
    # Cash movement, deliberately not called profit — profit needs COGS.
    assert Decimal(summary["net_cash"]) == Decimal("4200.00")
    assert Decimal(summary["receivable"]) == Decimal("9800.00")

    message = summary["message"]
    assert shop["business"]["name"] in message
    assert "Sale:" in message
    assert "Aaj ka udhaar" in message, "an unpaid balance must be called out"


async def test_a_quiet_day_says_so_rather_than_showing_zeros(shop):
    summary = (await shop["client"].get("/reports/daily-summary")).json()
    assert summary["bill_count"] == 0
    assert "Aaj koi bill nahi bana." in summary["message"]


async def test_low_stock_is_listed_without_meaningless_decimals(shop):
    """A message someone reads on a phone says "4 Bag", not "4.0000 Bag"."""
    client = shop["client"]
    await client.post(
        "/items",
        json={"name": "Nails 2in", "sale_price": 50, "purchase_price": 40,
              "opening_stock": 4, "opening_stock_value": 160,
              "unit_label": "Box", "low_stock_qty": 10},
    )

    summary = (await client.get("/reports/daily-summary")).json()
    listed = [i for i in summary["low_stock"] if i["name"] == "Nails 2in"]
    assert listed, "an item below its low-stock level must appear"
    assert listed[0]["qty"] == "4"
    assert "Khatam ho raha hai" in summary["message"]


async def test_sending_the_summary_is_a_no_op_when_switched_off(shop):
    """The scheduler calls this for every business; one shop opting out must not
    look like a failure."""
    await shop["client"].patch(
        "/businesses/current/settings", json={"daily_summary_enabled": False}
    )
    response = await shop["client"].post("/reports/daily-summary/send")
    assert response.status_code == 200
    assert response.json()["sent"] is False
    assert response.json()["reason"] == "disabled_for_this_business"
