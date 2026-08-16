"""Reminders: things the shopkeeper decided to be reminded about.

Separate from notifications, which are derived from the shop's state and come
and go on their own. A reminder was typed by somebody, so nothing about the
shop can make it untrue and nothing may quietly delete it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Query, status
from pydantic import Field

from app.api.deps import DbSession, Tenant
from app.core.permissions import Perm
from app.schemas.common import InputModel, Message, MoneyField, ORMModel
from app.services.reminder_service import ReminderService

router = APIRouter(prefix="/reminders", tags=["reminders"])


class ReminderOut(ORMModel):
    id: str
    title: str
    note: str | None = None
    due_at: datetime
    party_id: str | None = None
    party_name: str | None = None
    amount: Decimal | None = None
    is_done: bool
    done_at: datetime | None = None
    created_at: datetime

    #: True once its time has passed and nobody has dealt with it. Computed on
    #: the way out rather than stored, because it changes with the clock and a
    #: stored copy would be wrong within the hour.
    is_due: bool = False


class ReminderCreate(InputModel):
    title: str = Field(min_length=1, max_length=200)
    note: str | None = None
    due_at: datetime | None = None
    party_id: str | None = None
    amount: MoneyField | None = None


class ReminderUpdate(InputModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = None
    due_at: datetime | None = None
    amount: MoneyField | None = None


class ReminderSummary(ORMModel):
    total: int
    due_now: int
    amount_outstanding: Decimal


def _out(row) -> ReminderOut:
    from app.models.base import utcnow

    data = ReminderOut.model_validate(row)
    data.is_due = not row.is_done and row.due_at <= utcnow()
    return data


@router.get("", response_model=list[ReminderOut], summary="Everything still to do")
async def list_reminders(
    tenant: Tenant,
    db: DbSession,
    include_done: bool = Query(False, description="Include what has been ticked off."),
) -> list[ReminderOut]:
    tenant.require(Perm.PARTY_READ)
    rows = await ReminderService(db, tenant.actor).list_all(include_done=include_done)
    return [_out(r) for r in rows]


@router.get("/summary", response_model=ReminderSummary, summary="How much is waiting")
async def reminder_summary(tenant: Tenant, db: DbSession) -> ReminderSummary:
    tenant.require(Perm.PARTY_READ)
    service = ReminderService(db, tenant.actor)
    rows = await service.list_all()
    return ReminderSummary(
        total=len(rows),
        due_now=await service.pending_count(),
        amount_outstanding=await service.owed_total(),
    )


@router.post("", response_model=ReminderOut, status_code=status.HTTP_201_CREATED,
             summary="Remind me about this")
async def create_reminder(
    payload: ReminderCreate, tenant: Tenant, db: DbSession
) -> ReminderOut:
    tenant.require(Perm.PARTY_WRITE)
    row = await ReminderService(db, tenant.actor).create(
        payload.model_dump(exclude_unset=True)
    )
    return _out(row)


@router.patch("/{reminder_id}", response_model=ReminderOut, summary="Change one")
async def update_reminder(
    reminder_id: str, payload: ReminderUpdate, tenant: Tenant, db: DbSession
) -> ReminderOut:
    tenant.require(Perm.PARTY_WRITE)
    row = await ReminderService(db, tenant.actor).update(
        reminder_id, payload.model_dump(exclude_unset=True)
    )
    return _out(row)


@router.post("/{reminder_id}/done", response_model=ReminderOut, summary="Tick it off")
async def complete_reminder(
    reminder_id: str,
    tenant: Tenant,
    db: DbSession,
    done: bool = Query(True, description="False puts it back on the list."),
) -> ReminderOut:
    tenant.require(Perm.PARTY_WRITE)
    return _out(await ReminderService(db, tenant.actor).set_done(reminder_id, done))


@router.post("/{reminder_id}/snooze", response_model=ReminderOut,
             summary="Not now — remind me again later")
async def snooze_reminder(
    reminder_id: str,
    tenant: Tenant,
    db: DbSession,
    days: int = Query(1, ge=1, le=365),
) -> ReminderOut:
    """Without this the way to silence a reminder is to tick it off, which
    loses the thing it was there for."""
    tenant.require(Perm.PARTY_WRITE)
    return _out(await ReminderService(db, tenant.actor).snooze(reminder_id, days))


@router.delete("/{reminder_id}", response_model=Message, summary="Remove one")
async def delete_reminder(reminder_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.PARTY_WRITE)
    await ReminderService(db, tenant.actor).delete(reminder_id)
    return Message(message="Reminder removed.")
