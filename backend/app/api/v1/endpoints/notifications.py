"""In-app notifications: what needs the shopkeeper's attention today."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, Tenant
from app.core.pagination import PageParams, page_params
from app.core.permissions import Perm
from app.schemas.common import Message, ORMModel, Paginated
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(ORMModel):
    id: str
    kind: str
    title: str
    body: str | None = None
    channel: str
    data: dict[str, Any] | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


@router.get("", response_model=Paginated[NotificationOut], summary="List notifications")
async def list_notifications(
    tenant: Tenant,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    only_unread: bool = False,
    kind: str | None = Query(None, max_length=32),
) -> Paginated[NotificationOut]:
    tenant.require(Perm.REPORT_READ)
    rows, total = await NotificationService(db, tenant.actor).list(
        params, only_unread=only_unread, kind=kind
    )
    return Paginated[NotificationOut](
        items=[NotificationOut.model_validate(r) for r in rows],
        total=total, page=params.page, size=params.size,
        pages=max(1, -(-total // params.size)),
        has_next=params.page * params.size < total, has_prev=params.page > 1,
    )


@router.get("/count", summary="Unread badge count")
async def unread_count(tenant: Tenant, db: DbSession) -> dict[str, int]:
    tenant.require(Perm.REPORT_READ)
    return {"unread": await NotificationService(db, tenant.actor).unread_count()}


@router.post("/refresh", response_model=list[NotificationOut],
             summary="Recompute notifications from current business state")
async def refresh(tenant: Tenant, db: DbSession) -> list[NotificationOut]:
    """Reconciles the list: anything no longer true (a paid invoice, a restocked
    item) is removed rather than left as a stale reminder."""
    tenant.require(Perm.REPORT_READ)
    rows = await NotificationService(db, tenant.actor).refresh()
    return [NotificationOut.model_validate(r) for r in rows]


@router.post("/{notification_id}/read", response_model=NotificationOut, summary="Mark one read")
async def mark_read(notification_id: str, tenant: Tenant, db: DbSession) -> NotificationOut:
    tenant.require(Perm.REPORT_READ)
    row = await NotificationService(db, tenant.actor).mark_read(notification_id)
    return NotificationOut.model_validate(row)


@router.post("/read-all", response_model=Message, summary="Mark everything read")
async def mark_all_read(tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.REPORT_READ)
    count = await NotificationService(db, tenant.actor).mark_all_read()
    return Message(message=f"{count} notification(s) marked as read.")


@router.delete("", response_model=Message, summary="Clear all notifications")
async def clear(tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.REPORT_READ)
    count = await NotificationService(db, tenant.actor).clear()
    return Message(message=f"{count} notification(s) cleared.")
