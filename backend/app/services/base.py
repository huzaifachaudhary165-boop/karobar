"""BaseService — tenant scoping, audit trail and change-feed in one place.

Every domain service inherits from this so no query can accidentally cross a
business boundary and no write can escape the audit log.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.logging import log
from app.models.base import utcnow
from app.models.system import AuditLog, ChangeLog

M = TypeVar("M")


class ActorContext:
    """Who is performing the operation — threaded through every service call."""

    __slots__ = ("user_id", "user_name", "business_id", "role", "device_id", "source", "ip", "user_agent")

    def __init__(
        self,
        *,
        user_id: str | None = None,
        user_name: str | None = None,
        business_id: str | None = None,
        role: str | None = None,
        device_id: str | None = None,
        source: str = "api",
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self.business_id = business_id
        self.role = role
        self.device_id = device_id
        self.source = source
        self.ip = ip
        self.user_agent = user_agent


class BaseService(Generic[M]):
    model: type[M]
    entity_name: str = "record"
    # fields never written from client input
    protected_fields: set[str] = {
        "id", "business_id", "created_at", "updated_at", "created_by",
        "is_deleted", "deleted_at", "revision",
    }

    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        if not actor.business_id:
            raise ValueError("ActorContext.business_id is required for business services.")
        self.business_id: str = actor.business_id

    # ── querying ─────────────────────────────────────────────────
    def base_query(self, *, include_deleted: bool = False) -> Select:
        stmt = select(self.model).where(self.model.business_id == self.business_id)  # type: ignore[attr-defined]
        if not include_deleted and hasattr(self.model, "is_deleted"):
            stmt = stmt.where(self.model.is_deleted.is_(False))  # type: ignore[attr-defined]
        return stmt

    async def get(self, entity_id: str, *, include_deleted: bool = False) -> M | None:
        stmt = self.base_query(include_deleted=include_deleted).where(
            self.model.id == entity_id  # type: ignore[attr-defined]
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_or_404(self, entity_id: str, *, include_deleted: bool = False) -> M:
        obj = await self.get(entity_id, include_deleted=include_deleted)
        if obj is None:
            raise NotFoundError(
                f"{self.entity_name.replace('_', ' ').title()} not found.",
                details={"id": entity_id, "entity": self.entity_name},
            )
        return obj

    async def get_by_client_uuid(self, client_uuid: str) -> M | None:
        if not client_uuid or not hasattr(self.model, "client_uuid"):
            return None
        stmt = self.base_query(include_deleted=True).where(
            self.model.client_uuid == client_uuid  # type: ignore[attr-defined]
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    # ── mutation helpers ─────────────────────────────────────────
    def apply_fields(self, obj: Any, data: dict[str, Any]) -> dict[str, Any]:
        """Assign allowed fields, returning a {field: [old, new]} diff for the audit log."""
        changes: dict[str, Any] = {}
        for key, value in data.items():
            if key in self.protected_fields or not hasattr(obj, key):
                continue
            old = getattr(obj, key)
            if old != value:
                changes[key] = [_jsonable(old), _jsonable(value)]
                setattr(obj, key, value)
        return changes

    async def record_audit(
        self,
        action: str,
        entity_id: str | None,
        *,
        label: str | None = None,
        changes: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        entity_type: str | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                business_id=self.business_id,
                user_id=self.actor.user_id,
                user_name=self.actor.user_name,
                action=action,
                entity_type=entity_type or self.entity_name,
                entity_id=entity_id,
                entity_label=label,
                changes=changes or {},
                meta=meta or {},
                ip_address=self.actor.ip,
                user_agent=(self.actor.user_agent or "")[:300] or None,
                source=self.actor.source,
            )
        )

    async def record_change(
        self,
        operation: str,
        entity_id: str,
        *,
        revision: int = 1,
        payload: dict[str, Any] | None = None,
        entity_type: str | None = None,
    ) -> None:
        """Append to the sync change-feed so other devices pull this mutation."""
        self.db.add(
            ChangeLog(
                business_id=self.business_id,
                entity_type=entity_type or self.entity_name,
                entity_id=entity_id,
                operation=operation,
                revision=revision,
                payload=payload or {},
                device_id=self.actor.device_id,
                user_id=self.actor.user_id,
            )
        )

    async def track(
        self,
        action: str,
        obj: Any,
        *,
        changes: dict[str, Any] | None = None,
        label: str | None = None,
    ) -> None:
        """Audit + change-feed in one call. Use after every create/update/delete."""
        entity_id = getattr(obj, "id", None)
        if entity_id is None:
            return
        await self.record_audit(action, entity_id, label=label, changes=changes)
        await self.record_change(action, entity_id, revision=getattr(obj, "revision", 1) or 1)

    async def soft_delete(self, obj: Any, *, label: str | None = None) -> None:
        if hasattr(obj, "soft_delete"):
            obj.soft_delete(self.actor.user_id)
        if hasattr(obj, "bump_revision"):
            obj.bump_revision()
        await self.track("delete", obj, label=label)

    async def flush(self) -> None:
        await self.db.flush()

    def log(self, event: str, **kw: Any) -> None:
        log.info(event, business_id=self.business_id, entity=self.entity_name, **kw)


def _jsonable(value: Any) -> Any:
    """Audit diffs go into a JSON column — coerce Decimal/date/enum safely."""
    from datetime import date, datetime
    from decimal import Decimal
    from enum import Enum

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def stamp_sync(obj: Any, actor: ActorContext, *, client_uuid: str | None = None) -> None:
    """Attach sync provenance to a newly created/updated row."""
    if client_uuid and hasattr(obj, "client_uuid") and not getattr(obj, "client_uuid", None):
        obj.client_uuid = client_uuid
    if hasattr(obj, "device_id") and actor.device_id:
        obj.device_id = actor.device_id
    if hasattr(obj, "synced_at"):
        obj.synced_at = utcnow()
