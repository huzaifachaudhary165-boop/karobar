"""Things a shopkeeper asked to be reminded about.

Deliberately not part of the notification machinery, which is *derived*: those
are rebuilt from current state on every refresh, so an overdue-invoice notice
appears and disappears on its own. A reminder is the opposite — somebody typed
it, and nothing about the shop's state can make it untrue.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import BusinessRuleError
from app.core.money import money
from app.models.base import utcnow
from app.models.party import Party
from app.models.system import Reminder
from app.services.base import ActorContext, BaseService


class ReminderService(BaseService[Reminder]):
    model = Reminder
    entity_name = "reminder"

    async def create(self, data: dict[str, Any]) -> Reminder:
        title = str(data.get("title") or "").strip()
        if not title:
            raise BusinessRuleError("Say what the reminder is for.")

        due = data.get("due_at") or utcnow()

        party_name = None
        if party_id := data.get("party_id"):
            party = (
                await self.db.execute(select(Party).where(Party.id == party_id))
            ).scalar_one_or_none()
            if party is None:
                raise BusinessRuleError("That customer or supplier is not in your list.")
            # Copied rather than joined on read: a reminder still has to read
            # sensibly after the party is hidden or renamed, because it is a
            # note about something that was true when it was written.
            party_name = party.name

        row = Reminder(
            business_id=self.business_id,
            title=title,
            note=(data.get("note") or None),
            due_at=due,
            party_id=party_id or None,
            party_name=party_name,
            amount=money(data["amount"]) if data.get("amount") is not None else None,
            created_by=self.actor.user_id,
        )
        self.db.add(row)
        await self.db.flush()
        await self.track("create", row, label=row.title)
        return row

    async def update(self, reminder_id: str, data: dict[str, Any]) -> Reminder:
        row = await self.get_or_404(reminder_id)
        changes = self.apply_fields(
            row,
            {k: v for k, v in data.items() if k in {"title", "note", "due_at", "amount"}},
        )
        await self.db.flush()
        await self.track("update", row, changes=changes, label=row.title)
        return row

    async def set_done(self, reminder_id: str, done: bool) -> Reminder:
        row = await self.get_or_404(reminder_id)
        row.is_done = done
        row.done_at = utcnow() if done else None
        await self.db.flush()
        await self.track("update", row, label=row.title, changes={"is_done": done})
        return row

    async def delete(self, reminder_id: str) -> None:
        row = await self.get_or_404(reminder_id)
        await self.soft_delete(row, label=row.title)

    async def snooze(self, reminder_id: str, days: int = 1) -> Reminder:
        """Pushes it out without losing it.

        The alternative a shopkeeper actually uses is marking it done to make
        it go away, which loses the thing they were meant to do.
        """
        row = await self.get_or_404(reminder_id)
        base = max(row.due_at, utcnow()) if row.due_at else utcnow()
        row.due_at = base + timedelta(days=max(1, days))
        row.is_done = False
        row.done_at = None
        await self.db.flush()
        await self.track("update", row, label=row.title, changes={"snoozed_days": days})
        return row

    async def list_all(
        self, *, include_done: bool = False, limit: int = 200
    ) -> list[Reminder]:
        stmt = self.base_query()
        if not include_done:
            stmt = stmt.where(Reminder.is_done.is_(False))
        # Oldest due first: what should already have been done is what the
        # shopkeeper needs to see, not what is furthest away.
        return list(
            (
                await self.db.execute(stmt.order_by(Reminder.due_at).limit(limit))
            ).scalars().all()
        )

    async def due(self, *, at: datetime | None = None) -> list[Reminder]:
        """Everything whose time has come and which nobody has dealt with."""
        moment = at or utcnow()
        return list(
            (
                await self.db.execute(
                    self.base_query()
                    .where(Reminder.is_done.is_(False), Reminder.due_at <= moment)
                    .order_by(Reminder.due_at)
                )
            ).scalars().all()
        )

    async def pending_count(self) -> int:
        return (
            await self.db.execute(
                select(func.count())
                .select_from(Reminder)
                .where(
                    Reminder.business_id == self.business_id,
                    Reminder.is_deleted.is_(False),
                    Reminder.is_done.is_(False),
                    Reminder.due_at <= utcnow(),
                )
            )
        ).scalar_one()

    async def owed_total(self) -> Decimal:
        """What the outstanding reminders add up to, for the ones about money."""
        rows = await self.list_all()
        return money(sum((r.amount or 0) for r in rows))
