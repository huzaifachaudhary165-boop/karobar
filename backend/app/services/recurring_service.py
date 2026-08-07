"""Bills that repeat, and raising the ones that have come due."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from app.core.errors import BusinessRuleError
from app.core.money import ZERO, money
from app.core.schedules import FREQUENCIES, advance, catch_up, describe
from app.models.base import utcnow
from app.models.enums import VoucherType
from app.models.party import Party
from app.models.recurring import RecurringInvoice
from app.schemas.voucher import VoucherCreate, VoucherLineInput
from app.services.base import BaseService, stamp_sync
from app.services.voucher_service import VoucherService

# Beyond this many bills owed by one schedule, something is wrong with the
# schedule rather than with the shop, so it is reported and not acted on.
MAX_CATCH_UP = 24


class RecurringService(BaseService[RecurringInvoice]):
    model = RecurringInvoice
    entity_name = "recurring_invoice"

    async def create(self, data: dict[str, Any]) -> RecurringInvoice:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Give the repeating bill a name.")
        if (frequency := data.get("frequency", "monthly")) not in FREQUENCIES:
            raise BusinessRuleError(f"'{frequency}' is not a schedule this app keeps.")
        if not data.get("lines"):
            raise BusinessRuleError("A repeating bill needs at least one line.")

        starts = data.get("starts_on") or date.today()
        ends = data.get("ends_on")
        if ends and ends < starts:
            raise BusinessRuleError("The schedule would end before it starts.")

        party_name = None
        if party_id := data.get("party_id"):
            party = (
                await self.db.execute(
                    select(Party).where(
                        Party.id == party_id,
                        Party.business_id == self.business_id,
                        Party.is_deleted.is_(False),
                    )
                )
            ).scalar_one_or_none()
            if party is None:
                raise BusinessRuleError("That customer no longer exists.")
            party_name = party.name

        data["name"] = name
        data["starts_on"] = starts
        row = RecurringInvoice(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            party_name=party_name,
            # The first run is the start date itself, so a schedule set up for
            # today bills today rather than a month from now.
            next_run_on=starts,
            **{
                k: v for k, v in data.items()
                if hasattr(RecurringInvoice, k) and k not in {"next_run_on", "party_name"}
            },
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()
        await self.track("create", row, label=row.name)
        return row

    async def update(self, recurring_id: str, data: dict[str, Any]) -> RecurringInvoice:
        row = await self.get_or_404(recurring_id)
        # Owned by what has actually been raised, not by an edit.
        for owned in ("occurrences", "last_run_on", "last_voucher_id", "total_billed"):
            data.pop(owned, None)

        changes = self.apply_fields(row, data)
        if changes:
            row.bump_revision()
            await self.track("update", row, changes=changes, label=row.name)
        return row

    async def delete(self, recurring_id: str) -> None:
        row = await self.get_or_404(recurring_id)
        # Bills already raised stay: they are real invoices with real money
        # against them, and nothing here touches them.
        await self.soft_delete(row, label=row.name)

    async def list_all(self, *, only_active: bool = False) -> list[RecurringInvoice]:
        stmt = self.base_query()
        if only_active:
            stmt = stmt.where(RecurringInvoice.is_active.is_(True))
        return list(
            (await self.db.execute(stmt.order_by(RecurringInvoice.next_run_on)))
            .scalars().all()
        )

    async def due(self, on: date | None = None) -> list[RecurringInvoice]:
        when = on or date.today()
        rows = await self.list_all(only_active=True)
        return [row for row in rows if row.due_on(when)]

    async def run_due(self, on: date | None = None) -> dict[str, Any]:
        """Raise every bill that has come due since this was last looked at.

        There is no scheduler behind this. The app runs on serverless functions
        that only exist while a request is in flight, so nothing wakes up at
        midnight — the app asks on open instead. That makes catching up the
        normal case rather than the exception: a shop closed for six weeks owes
        six weekly bills, and raising only the most recent would silently lose
        five months of rent over a year of light use.
        """
        when = on or date.today()
        created: list[dict[str, Any]] = []
        reminders: list[dict[str, Any]] = []
        problems: list[dict[str, Any]] = []

        for row in await self.due(when):
            row.last_checked_at = utcnow()
            missed = catch_up(
                row.next_run_on, when, row.frequency, row.interval,
                anchor_day=row.starts_on.day, limit=MAX_CATCH_UP + 1,
            )

            if len(missed) > MAX_CATCH_UP:
                row.last_error = (
                    f"{len(missed)}+ bills are owed on this schedule. "
                    "Check the dates before raising them."
                )
                problems.append({"id": row.id, "name": row.name, "reason": row.last_error})
                continue

            if not row.auto_create:
                reminders.append(
                    {"id": row.id, "name": row.name, "due_count": len(missed),
                     "next_run_on": row.next_run_on}
                )
                continue

            for run_date in missed:
                if row.max_occurrences is not None and row.occurrences >= row.max_occurrences:
                    break
                if row.ends_on and run_date > row.ends_on:
                    break
                try:
                    voucher = await self._raise(row, run_date)
                except Exception as error:  # one bad schedule must not stop the rest
                    row.last_error = str(error)[:300]
                    problems.append(
                        {"id": row.id, "name": row.name, "reason": row.last_error}
                    )
                    break
                created.append(
                    {
                        "id": row.id,
                        "name": row.name,
                        "voucher_id": voucher.id,
                        "number": voucher.number,
                        "total": voucher.total,
                        "voucher_date": run_date,
                    }
                )

            row.bump_revision()

        return {
            "created": created,
            "reminders": reminders,
            "problems": problems,
            "checked_on": when,
        }

    async def run_one(self, recurring_id: str, on: date | None = None) -> dict[str, Any]:
        """Raise the next bill on one schedule, now — the 'do it anyway' button."""
        row = await self.get_or_404(recurring_id)
        if not row.is_active:
            raise BusinessRuleError("This repeating bill is switched off.")
        if row.is_finished:
            raise BusinessRuleError("This schedule has already finished.")

        voucher = await self._raise(row, on or row.next_run_on)
        row.bump_revision()
        return {
            "id": row.id,
            "voucher_id": voucher.id,
            "number": voucher.number,
            "total": voucher.total,
        }

    async def _raise(self, row: RecurringInvoice, on: date):
        """Turn the template into a real voucher and move the schedule on."""
        lines = [
            VoucherLineInput(
                item_id=line.get("item_id"),
                item_name=line.get("item_name") or "Item",
                qty=line.get("qty") or 1,
                rate=line.get("rate") or 0,
                tax_rate=line.get("tax_rate") or 0,
            )
            for line in (row.lines or [])
        ]
        if not lines:
            raise BusinessRuleError("This repeating bill has no lines left on it.")

        voucher = await VoucherService(self.db, self.actor).create(
            VoucherCreate(
                voucher_type=VoucherType(row.voucher_type),
                voucher_date=on,
                party_id=row.party_id,
                notes=row.notes,
                lines=lines,
                source="recurring",
            )
        )

        row.occurrences += 1
        row.last_run_on = on
        row.last_voucher_id = voucher.id
        row.last_error = None
        row.total_billed = money((row.total_billed or ZERO) + voucher.total)
        row.next_run_on = advance(
            on, row.frequency, row.interval, anchor_day=row.starts_on.day
        )
        if row.is_finished:
            row.is_active = False
        return voucher

    @staticmethod
    def describe(row: RecurringInvoice) -> str:
        return describe(row.frequency, row.interval)
