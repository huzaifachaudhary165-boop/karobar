"""Bills that repeat."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, status

from app.api.deps import DbSession, Tenant
from app.core.permissions import Perm
from app.core.schedules import describe
from app.schemas.common import Message
from app.schemas.recurring import (
    RecurringCreate, RecurringOut, RecurringUpdate, RunResult,
)
from app.services.recurring_service import RecurringService

router = APIRouter(prefix="/recurring", tags=["recurring"])


def _out(row) -> RecurringOut:
    data = RecurringOut.model_validate(row)
    data.schedule_label = describe(row.frequency, row.interval)
    data.is_due = row.due_on(date.today())
    data.is_finished = row.is_finished
    return data


@router.get("", response_model=list[RecurringOut], summary="Repeating bills")
async def list_recurring(
    tenant: Tenant, db: DbSession, only_active: bool = False
) -> list[RecurringOut]:
    tenant.require(Perm.SALE_READ)
    rows = await RecurringService(db, tenant.actor).list_all(only_active=only_active)
    return [_out(row) for row in rows]


@router.post("", response_model=RecurringOut, status_code=status.HTTP_201_CREATED,
             summary="Set up a repeating bill")
async def create_recurring(
    payload: RecurringCreate, tenant: Tenant, db: DbSession
) -> RecurringOut:
    tenant.require(Perm.SALE_WRITE)
    data = payload.model_dump(exclude_unset=True)
    data["lines"] = [line.model_dump(mode="json") for line in payload.lines]
    return _out(await RecurringService(db, tenant.actor).create(data))


@router.post("/run", response_model=RunResult, summary="Raise everything that is due")
async def run_due(tenant: Tenant, db: DbSession) -> RunResult:
    """Called by the app when it opens.

    There is no scheduler behind this: the app runs on serverless functions
    that only exist while a request is in flight, so nothing wakes up at
    midnight to raise a bill. Asking on open makes catching up the normal case
    rather than the exception, which is why a shop closed for six weeks gets
    six weekly bills and not one.
    """
    tenant.require(Perm.SALE_WRITE)
    return RunResult(**await RecurringService(db, tenant.actor).run_due())


@router.get("/due", response_model=list[RecurringOut], summary="What is due right now")
async def list_due(tenant: Tenant, db: DbSession) -> list[RecurringOut]:
    tenant.require(Perm.SALE_READ)
    return [_out(row) for row in await RecurringService(db, tenant.actor).due()]


@router.get("/{recurring_id}", response_model=RecurringOut, summary="Get one")
async def get_recurring(recurring_id: str, tenant: Tenant, db: DbSession) -> RecurringOut:
    tenant.require(Perm.SALE_READ)
    return _out(await RecurringService(db, tenant.actor).get_or_404(recurring_id))


@router.patch("/{recurring_id}", response_model=RecurringOut, summary="Update one")
async def update_recurring(
    recurring_id: str, payload: RecurringUpdate, tenant: Tenant, db: DbSession
) -> RecurringOut:
    tenant.require(Perm.SALE_WRITE)
    data = payload.model_dump(exclude_unset=True)
    if payload.lines is not None:
        data["lines"] = [line.model_dump(mode="json") for line in payload.lines]
    row = await RecurringService(db, tenant.actor).update(recurring_id, data)
    return _out(row)


@router.delete("/{recurring_id}", response_model=Message, summary="Stop a repeating bill")
async def delete_recurring(recurring_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.SALE_DELETE)
    await RecurringService(db, tenant.actor).delete(recurring_id)
    return Message(message="Stopped. Bills already raised are untouched.")


@router.post("/{recurring_id}/run", response_model=Message, summary="Raise this one now")
async def run_one(recurring_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.SALE_WRITE)
    result = await RecurringService(db, tenant.actor).run_one(recurring_id)
    return Message(message=f"{result['number']} raised.")
