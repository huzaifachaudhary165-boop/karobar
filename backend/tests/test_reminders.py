"""Reminders — the things a shopkeeper decided to be reminded about.

Deliberately not part of the notification machinery, which is derived: those
are rebuilt from the shop's state on every refresh, so an overdue-invoice
notice appears and disappears on its own. A reminder is the opposite. Somebody
typed it, and nothing about the shop can make it untrue — least of all a
refresh running in the background.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _at(**kw) -> str:
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat()


async def _make(client, **kw) -> dict:
    body = {"title": "Call Ahmed", **kw}
    response = await client.post("/reminders", json=body)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_a_reminder_can_be_written_down(shop):
    row = await _make(
        shop["client"],
        title="Ahmed se 5000 lene hain",
        due_at=_at(days=2),
        amount=5000,
    )

    assert row["title"] == "Ahmed se 5000 lene hain"
    assert float(row["amount"]) == 5000
    assert row["is_done"] is False


@pytest.mark.asyncio
async def test_one_about_somebody_keeps_their_name(shop):
    """Copied rather than joined on read.

    A reminder has to read sensibly after the party is hidden or renamed — it
    is a note about something that was true when it was written.
    """
    row = await _make(
        shop["client"], party_id=shop["customer"]["id"], due_at=_at(days=1)
    )
    assert row["party_name"] == shop["customer"]["name"]


@pytest.mark.asyncio
async def test_a_reminder_for_somebody_who_does_not_exist_is_refused(shop):
    response = await shop["client"].post(
        "/reminders",
        json={"title": "x", "party_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_an_empty_reminder_is_refused(shop):
    response = await shop["client"].post("/reminders", json={"title": "   "})
    assert response.status_code == 422, response.text


# ── what is waiting ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_what_is_already_due_comes_first(shop):
    """Oldest due first. What should already have been done is what the
    shopkeeper needs to see, not what is furthest away."""
    client = shop["client"]
    await _make(client, title="Next week", due_at=_at(days=7))
    await _make(client, title="Yesterday", due_at=_at(days=-1))
    await _make(client, title="Tomorrow", due_at=_at(days=1))

    rows = (await client.get("/reminders")).json()
    assert [r["title"] for r in rows] == ["Yesterday", "Tomorrow", "Next week"]


@pytest.mark.asyncio
async def test_only_the_ones_whose_time_has_come_count_as_due(shop):
    client = shop["client"]
    await _make(client, title="Later", due_at=_at(days=3))
    await _make(client, title="Now", due_at=_at(days=-1))

    summary = (await client.get("/reminders/summary")).json()
    assert summary["total"] == 2
    assert summary["due_now"] == 1


@pytest.mark.asyncio
async def test_the_summary_adds_up_what_is_owed(shop):
    client = shop["client"]
    await _make(client, title="A", amount=5000, due_at=_at(days=-1))
    await _make(client, title="B", amount=2500, due_at=_at(days=1))
    await _make(client, title="No money involved", due_at=_at(days=1))

    summary = (await client.get("/reminders/summary")).json()
    assert float(summary["amount_outstanding"]) == 7500


# ── dealing with one ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ticking_one_off_takes_it_off_the_list(shop):
    client = shop["client"]
    row = await _make(client, due_at=_at(days=-1))

    done = await client.post(f"/reminders/{row['id']}/done")
    assert done.status_code == 200, done.text
    assert done.json()["is_done"] is True

    assert (await client.get("/reminders")).json() == []
    assert len((await client.get("/reminders", params={"include_done": True})).json()) == 1


@pytest.mark.asyncio
async def test_something_ticked_off_by_mistake_comes_back(shop):
    client = shop["client"]
    row = await _make(client, due_at=_at(days=-1))
    await client.post(f"/reminders/{row['id']}/done")

    back = await client.post(f"/reminders/{row['id']}/done", params={"done": False})
    assert back.json()["is_done"] is False
    assert len((await client.get("/reminders")).json()) == 1


@pytest.mark.asyncio
async def test_snoozing_pushes_it_out_without_losing_it(shop):
    """Without this the way to silence a reminder is to tick it off, which
    loses the thing it was there for."""
    client = shop["client"]
    row = await _make(client, due_at=_at(days=-1))

    snoozed = await client.post(f"/reminders/{row['id']}/snooze", params={"days": 3})
    assert snoozed.status_code == 200, snoozed.text
    assert snoozed.json()["is_done"] is False
    assert snoozed.json()["is_due"] is False

    # Still on the list, just not shouting.
    assert len((await client.get("/reminders")).json()) == 1
    assert (await client.get("/reminders/summary")).json()["due_now"] == 0


@pytest.mark.asyncio
async def test_snoozing_something_already_ticked_off_puts_it_back(shop):
    client = shop["client"]
    row = await _make(client, due_at=_at(days=-1))
    await client.post(f"/reminders/{row['id']}/done")

    snoozed = await client.post(f"/reminders/{row['id']}/snooze")
    assert snoozed.json()["is_done"] is False


@pytest.mark.asyncio
async def test_a_reminder_can_be_changed(shop):
    client = shop["client"]
    row = await _make(client, title="Call someone", amount=1000)

    fixed = await client.patch(
        f"/reminders/{row['id']}", json={"title": "Call Ahmed", "amount": 5000}
    )
    assert fixed.json()["title"] == "Call Ahmed"
    assert float(fixed.json()["amount"]) == 5000


@pytest.mark.asyncio
async def test_a_reminder_can_be_removed(shop):
    client = shop["client"]
    row = await _make(client)

    gone = await client.delete(f"/reminders/{row['id']}")
    assert gone.status_code == 200, gone.text
    assert (await client.get("/reminders")).json() == []


# ── the tap on the shoulder ────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_due_reminder_reaches_the_bell(shop):
    client = shop["client"]
    await _make(client, title="Ahmed se paise lene hain", amount=5000, due_at=_at(days=-1))

    await client.post("/notifications/refresh")
    rows = (await client.get("/notifications")).json()
    rows = rows["items"] if isinstance(rows, dict) else rows

    mine = [r for r in rows if r["kind"] == "reminder"]
    assert len(mine) == 1
    assert mine[0]["title"] == "Ahmed se paise lene hain"
    assert "5,000" in (mine[0]["body"] or "")


@pytest.mark.asyncio
async def test_one_that_is_not_due_yet_stays_quiet(shop):
    client = shop["client"]
    await _make(client, due_at=_at(days=5))

    await client.post("/notifications/refresh")
    rows = (await client.get("/notifications")).json()
    rows = rows["items"] if isinstance(rows, dict) else rows

    assert not [r for r in rows if r["kind"] == "reminder"]


@pytest.mark.asyncio
async def test_refreshing_the_bell_never_deletes_the_reminder_itself(shop):
    """The notice is derived and comes and goes. The reminder is a promise
    somebody made, and a background refresh must not be able to erase it."""
    client = shop["client"]
    row = await _make(client, due_at=_at(days=-1))

    await client.post("/notifications/refresh")
    await client.post(f"/reminders/{row['id']}/done")
    await client.post("/notifications/refresh")

    still = (await client.get("/reminders", params={"include_done": True})).json()
    assert len(still) == 1, "ticking it off must not destroy the record"

    rows = (await client.get("/notifications")).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    assert not [r for r in rows if r["kind"] == "reminder"], (
        "but the notice should go once it is dealt with"
    )
