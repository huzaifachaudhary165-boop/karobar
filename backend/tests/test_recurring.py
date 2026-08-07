"""Bills that repeat, over the API.

There is no scheduler behind any of this. The app runs on serverless functions
that only exist while a request is in flight, so nothing wakes up at midnight —
the app asks on open. That makes catching up the normal case, and most of what
follows is about getting the catch-up right.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest


async def _schedule(shop, **kw) -> dict:
    client = shop["client"]
    body = {
        "name": "Monthly rent bill",
        "party_id": shop["customer"]["id"],
        "frequency": "monthly",
        "lines": [
            {
                "item_id": shop["sugar"]["id"],
                "item_name": "Sugar 50kg",
                "qty": 2,
                "rate": 7400,
                "tax_rate": 0,
            }
        ],
        **kw,
    }
    response = await client.post("/recurring", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ── setting one up ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_schedule_starting_today_is_due_today(shop):
    """Not a month from now — a shop that sets it up today expects today's
    bill to go out."""
    row = await _schedule(shop, starts_on=date.today().isoformat())
    assert row["next_run_on"] == date.today().isoformat()
    assert row["is_due"] is True


@pytest.mark.asyncio
async def test_the_schedule_reads_the_way_a_shopkeeper_would_say_it(shop):
    monthly = await _schedule(shop)
    assert monthly["schedule_label"] == "Every month"

    fortnightly = await _schedule(shop, name="Fortnightly", frequency="weekly", interval=2)
    assert fortnightly["schedule_label"] == "Every 2 weeks"


@pytest.mark.asyncio
async def test_the_customer_name_is_kept_for_the_list_screen(shop):
    row = await _schedule(shop)
    assert row["party_name"] == shop["customer"]["name"]


@pytest.mark.asyncio
async def test_a_schedule_with_no_lines_is_refused(shop):
    refused = await shop["client"].post(
        "/recurring", json={"name": "Empty", "lines": []}
    )
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_a_schedule_ending_before_it_starts_is_refused(shop):
    refused = await shop["client"].post(
        "/recurring",
        json={
            "name": "Backwards",
            "starts_on": "2026-09-01",
            "ends_on": "2026-08-01",
            "lines": [{"item_name": "X", "qty": 1, "rate": 100}],
        },
    )
    assert refused.status_code == 422, refused.text


# ── raising the bills ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_running_raises_a_real_invoice(shop):
    client = shop["client"]
    row = await _schedule(shop, starts_on=date.today().isoformat())

    result = (await client.post("/recurring/run")).json()
    mine = [c for c in result["created"] if c["id"] == row["id"]]
    assert len(mine) == 1, result

    invoice = (await client.get(f"/vouchers/{mine[0]['voucher_id']}")).json()
    assert Decimal(invoice["total"]) == Decimal("14800.00")
    assert invoice["party_id"] == shop["customer"]["id"]


@pytest.mark.asyncio
async def test_running_moves_the_schedule_on(shop):
    client = shop["client"]
    row = await _schedule(shop, starts_on=date.today().isoformat())

    await client.post("/recurring/run")
    after = (await client.get(f"/recurring/{row['id']}")).json()

    assert after["occurrences"] == 1
    assert after["last_run_on"] == date.today().isoformat()
    assert after["next_run_on"] > date.today().isoformat()
    assert after["is_due"] is False


@pytest.mark.asyncio
async def test_running_twice_in_a_day_does_not_bill_twice(shop):
    client = shop["client"]
    row = await _schedule(shop, starts_on=date.today().isoformat())

    await client.post("/recurring/run")
    again = (await client.post("/recurring/run")).json()

    assert not [c for c in again["created"] if c["id"] == row["id"]]


@pytest.mark.asyncio
async def test_six_weeks_away_owes_six_bills_not_one(shop):
    """Raising only the most recent would silently lose five months of rent
    over a year of light use."""
    client = shop["client"]
    row = await _schedule(
        shop,
        name="Weekly delivery",
        frequency="weekly",
        starts_on=(date.today() - timedelta(days=35)).isoformat(),
    )

    result = (await client.post("/recurring/run")).json()
    mine = [c for c in result["created"] if c["id"] == row["id"]]

    assert len(mine) == 6, [c["voucher_date"] for c in mine]
    assert mine[0]["voucher_date"] < mine[-1]["voucher_date"], "oldest first"


@pytest.mark.asyncio
async def test_each_caught_up_bill_carries_its_own_date(shop):
    client = shop["client"]
    row = await _schedule(
        shop,
        name="Backdated weekly",
        frequency="weekly",
        starts_on=(date.today() - timedelta(days=14)).isoformat(),
    )

    result = (await client.post("/recurring/run")).json()
    mine = [c for c in result["created"] if c["id"] == row["id"]]

    dates = {c["voucher_date"] for c in mine}
    assert len(dates) == len(mine), "each bill is dated when it was owed"


@pytest.mark.asyncio
async def test_a_schedule_set_to_remind_does_not_raise_anything(shop):
    """A shop that wants to check a bill before it goes out gets a reminder.
    Raising one behind their back is worse than not raising it."""
    client = shop["client"]
    row = await _schedule(
        shop, name="Check first", auto_create=False,
        starts_on=date.today().isoformat(),
    )

    result = (await client.post("/recurring/run")).json()
    assert not [c for c in result["created"] if c["id"] == row["id"]]
    reminder = next(r for r in result["reminders"] if r["id"] == row["id"])
    assert reminder["due_count"] == 1


@pytest.mark.asyncio
async def test_a_dormant_schedule_is_reported_rather_than_flooding_the_books(shop):
    """Hundreds of bills at once is a mistake to be told about, not acted on."""
    client = shop["client"]
    row = await _schedule(
        shop,
        name="Forgotten daily",
        frequency="daily",
        starts_on=(date.today() - timedelta(days=400)).isoformat(),
    )

    result = (await client.post("/recurring/run")).json()
    assert not [c for c in result["created"] if c["id"] == row["id"]]
    problem = next(p for p in result["problems"] if p["id"] == row["id"])
    assert "Check the dates" in problem["reason"]


@pytest.mark.asyncio
async def test_a_schedule_stops_after_its_last_occurrence(shop):
    client = shop["client"]
    row = await _schedule(
        shop,
        name="Three only",
        frequency="weekly",
        max_occurrences=3,
        starts_on=(date.today() - timedelta(days=35)).isoformat(),
    )

    result = (await client.post("/recurring/run")).json()
    mine = [c for c in result["created"] if c["id"] == row["id"]]
    assert len(mine) == 3

    after = (await client.get(f"/recurring/{row['id']}")).json()
    assert after["is_finished"] is True
    assert after["is_active"] is False


@pytest.mark.asyncio
async def test_a_schedule_stops_at_its_end_date(shop):
    client = shop["client"]
    row = await _schedule(
        shop,
        name="Ends soon",
        frequency="weekly",
        starts_on=(date.today() - timedelta(days=35)).isoformat(),
        ends_on=(date.today() - timedelta(days=14)).isoformat(),
    )

    result = (await client.post("/recurring/run")).json()
    mine = [c for c in result["created"] if c["id"] == row["id"]]
    assert len(mine) == 4, "the four weeks up to the end date"


@pytest.mark.asyncio
async def test_a_switched_off_schedule_raises_nothing(shop):
    client = shop["client"]
    row = await _schedule(shop, starts_on=date.today().isoformat(), is_active=False)

    result = (await client.post("/recurring/run")).json()
    assert not [c for c in result["created"] if c["id"] == row["id"]]


@pytest.mark.asyncio
async def test_the_running_total_adds_up(shop):
    client = shop["client"]
    row = await _schedule(
        shop,
        name="Totals",
        frequency="weekly",
        starts_on=(date.today() - timedelta(days=14)).isoformat(),
    )

    await client.post("/recurring/run")
    after = (await client.get(f"/recurring/{row['id']}")).json()

    assert Decimal(after["total_billed"]) == Decimal("14800.00") * after["occurrences"]


# ── acting on one directly ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_bill_can_be_raised_before_it_is_due(shop):
    client = shop["client"]
    row = await _schedule(
        shop, starts_on=(date.today() + timedelta(days=30)).isoformat()
    )
    assert row["is_due"] is False

    raised = await client.post(f"/recurring/{row['id']}/run")
    assert raised.status_code == 200, raised.text
    assert (await client.get(f"/recurring/{row['id']}")).json()["occurrences"] == 1


@pytest.mark.asyncio
async def test_a_switched_off_schedule_cannot_be_forced(shop):
    client = shop["client"]
    row = await _schedule(shop, is_active=False)

    refused = await client.post(f"/recurring/{row['id']}/run")
    assert refused.status_code == 422, refused.text


@pytest.mark.asyncio
async def test_what_is_due_can_be_listed_without_raising_it(shop):
    client = shop["client"]
    row = await _schedule(shop, starts_on=date.today().isoformat())

    due = (await client.get("/recurring/due")).json()
    assert any(r["id"] == row["id"] for r in due)

    after = (await client.get(f"/recurring/{row['id']}")).json()
    assert after["occurrences"] == 0, "listing must not raise anything"


@pytest.mark.asyncio
async def test_stopping_a_schedule_leaves_its_bills_alone(shop):
    client = shop["client"]
    row = await _schedule(shop, starts_on=date.today().isoformat())
    result = (await client.post("/recurring/run")).json()
    voucher_id = next(c for c in result["created"] if c["id"] == row["id"])["voucher_id"]

    removed = await client.delete(f"/recurring/{row['id']}")
    assert removed.status_code == 200, removed.text

    invoice = await client.get(f"/vouchers/{voucher_id}")
    assert invoice.status_code == 200, "a real bill with real money against it"


@pytest.mark.asyncio
async def test_the_counters_cannot_be_edited(shop):
    """How many bills went out is a record, not a setting."""
    client = shop["client"]
    row = await _schedule(shop, starts_on=date.today().isoformat())
    await client.post("/recurring/run")

    edited = await client.patch(
        f"/recurring/{row['id']}", json={"name": "Renamed", "occurrences": 99}
    )
    assert edited.status_code in (200, 422)
    after = (await client.get(f"/recurring/{row['id']}")).json()
    assert after["occurrences"] == 1
