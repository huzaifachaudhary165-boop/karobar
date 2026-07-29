"""Delta sync for the offline-first client.

Contract:
  * PUSH — the device sends the mutations it made offline. Each carries a
    `client_uuid`, so a retried upload updates the same row instead of creating a
    twin, and a `base_revision` so a stale edit is reported as a conflict rather
    than silently overwriting a newer server value.
  * PULL — the device asks for everything after the monotonic sequence it last
    saw. `change_logs.id` is that sequence.

Conflict policy is last-write-wins *with detection*: the server keeps its version
and hands the client both, so the UI can ask the user instead of losing data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import log
from app.models import SYNCABLE_MODELS
from app.models.base import utcnow
from app.models.business import Business, BusinessSettings
from app.models.enums import SyncOperation
from app.models.system import ChangeLog, SyncState
from app.schemas.sync import SyncChange
from app.services.base import ActorContext

# Entity → (service class, create-schema, update-handler name)
_ENTITY_SERVICES: dict[str, tuple[str, str]] = {
    "party": ("app.services.party_service:PartyService", "app.schemas.party:PartyCreate"),
    "party_group": ("app.services.party_service:PartyGroupService", ""),
    "item": ("app.services.item_service:ItemService", "app.schemas.item:ItemCreate"),
    "item_category": ("app.services.item_service:CategoryService", ""),
    "unit": ("app.services.item_service:UnitService", ""),
    "voucher": ("app.services.voucher_service:VoucherService", "app.schemas.voucher:VoucherCreate"),
    "payment": ("app.services.payment_service:PaymentService", "app.schemas.payment:PaymentCreate"),
    "expense": ("app.services.expense_service:ExpenseService", "app.schemas.payment:ExpenseCreate"),
    "expense_category": ("app.services.expense_service:ExpenseCategoryService", ""),
    "tax_rate": ("app.services.expense_service:TaxRateService", ""),
    "account": ("app.services.payment_service:AccountService", ""),
}

MAX_PULL_BATCH = 500
FULL_SYNC_THRESHOLD = 5000  # too far behind → re-bootstrap instead of replaying


class SyncService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    # ── push ─────────────────────────────────────────────────────
    async def push(
        self, device_id: str, changes: list[SyncChange], *, platform: str | None = None,
        app_version: str | None = None,
    ) -> dict[str, Any]:
        state = await self._state(device_id, platform=platform, app_version=app_version)
        applied: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        for change in changes:
            try:
                outcome = await self._apply(change)
                applied.append(outcome)
            except _Conflict as exc:
                conflicts.append(exc.as_dict())
            except AppError as exc:
                conflicts.append(
                    {
                        "entity": change.entity,
                        "client_uuid": change.client_uuid,
                        "server_id": change.server_id,
                        "reason": "validation",
                        "message": exc.message,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — one bad row must not fail the batch
                log.exception("sync.apply_failed", entity=change.entity, error=str(exc))
                conflicts.append(
                    {
                        "entity": change.entity,
                        "client_uuid": change.client_uuid,
                        "server_id": change.server_id,
                        "reason": "validation",
                        "message": "This change could not be applied.",
                    }
                )

        state.last_pushed_at = utcnow()
        if conflicts:
            state.pending_conflicts = conflicts
        await self.db.flush()

        return {
            "applied": applied,
            "conflicts": conflicts,
            "server_seq": await self.current_seq(),
            "server_time": utcnow(),
        }

    async def _apply(self, change: SyncChange) -> dict[str, Any]:
        model = SYNCABLE_MODELS.get(change.entity)
        if model is None:
            raise AppError(f"Unknown entity '{change.entity}'.", code="unknown_entity")

        existing = await self._find(model, change)

        if change.operation == SyncOperation.DELETE:
            if existing is None:
                # Already gone — treat as success so the device stops retrying.
                return {
                    "entity": change.entity, "client_uuid": change.client_uuid,
                    "server_id": change.server_id or "", "revision": 0, "operation": "delete",
                }
            await self._delete(change.entity, existing)
            return {
                "entity": change.entity, "client_uuid": change.client_uuid,
                "server_id": existing.id, "revision": existing.revision, "operation": "delete",
            }

        if existing is None:
            created = await self._create(change)
            return {
                "entity": change.entity, "client_uuid": change.client_uuid,
                "server_id": created.id, "revision": getattr(created, "revision", 1),
                "operation": "create",
            }

        server_revision = getattr(existing, "revision", 1) or 1
        if change.base_revision and change.base_revision < server_revision:
            raise _Conflict(
                entity=change.entity,
                client_uuid=change.client_uuid,
                server_id=existing.id,
                server_revision=server_revision,
                server_data=_public(existing),
            )

        await self._update(change, existing)
        return {
            "entity": change.entity, "client_uuid": change.client_uuid,
            "server_id": existing.id, "revision": getattr(existing, "revision", 1),
            "operation": "update",
        }

    async def _find(self, model: type, change: SyncChange):
        stmt = select(model).where(model.business_id == self.business_id)
        if change.server_id:
            stmt = stmt.where(model.id == change.server_id)
        elif change.client_uuid and hasattr(model, "client_uuid"):
            stmt = stmt.where(model.client_uuid == change.client_uuid)
        else:
            return None
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _create(self, change: SyncChange):
        service = self._service(change.entity)
        payload = {**change.data, "client_uuid": change.client_uuid}
        schema = self._schema(change.entity)
        return await service.create(schema(**payload) if schema else payload)

    async def _update(self, change: SyncChange, existing):
        service = self._service(change.entity)
        if hasattr(service, "update"):
            data = {k: v for k, v in change.data.items() if k not in ("client_uuid", "device_id")}
            await service.update(existing.id, data)
        else:  # masters without a dedicated update path
            service.apply_fields(existing, change.data)
            existing.bump_revision()
        return existing

    async def _delete(self, entity: str, existing) -> None:
        service = self._service(entity)
        if hasattr(service, "delete"):
            await service.delete(existing.id)
        else:
            await service.soft_delete(existing)

    # ── pull ─────────────────────────────────────────────────────
    async def pull(
        self, device_id: str, since: int = 0, limit: int = MAX_PULL_BATCH
    ) -> dict[str, Any]:
        state = await self._state(device_id)
        server_seq = await self.current_seq()

        if since and server_seq - since > FULL_SYNC_THRESHOLD:
            return {
                "records": [], "server_seq": server_seq, "has_more": False,
                "server_time": utcnow(), "requires_full_sync": True,
            }

        rows = (
            await self.db.execute(
                select(ChangeLog)
                .where(ChangeLog.business_id == self.business_id, ChangeLog.id > since)
                .order_by(ChangeLog.id)
                .limit(min(limit, MAX_PULL_BATCH) + 1)
            )
        ).scalars().all()

        has_more = len(rows) > limit
        rows = rows[:limit]

        records: list[dict[str, Any]] = []
        for row in rows:
            # A device never needs to replay its own writes back to itself.
            if row.device_id and row.device_id == device_id:
                continue
            model = SYNCABLE_MODELS.get(row.entity_type)
            data = None
            if model is not None and row.operation != SyncOperation.DELETE:
                entity = (
                    await self.db.execute(
                        select(model).where(
                            model.id == row.entity_id, model.business_id == self.business_id
                        )
                    )
                ).scalar_one_or_none()
                data = _public(entity) if entity is not None else None
                if data is None:
                    continue
            records.append(
                {
                    "entity": row.entity_type,
                    "operation": row.operation,
                    "id": row.entity_id,
                    "revision": row.revision,
                    "seq": row.id,
                    "data": data,
                    "updated_at": row.created_at,
                }
            )

        if rows:
            state.last_pulled_seq = rows[-1].id
        state.last_pulled_at = utcnow()
        await self.db.flush()

        return {
            "records": records,
            "server_seq": server_seq,
            "has_more": has_more,
            "server_time": utcnow(),
            "requires_full_sync": False,
        }

    # ── bootstrap ────────────────────────────────────────────────
    async def bootstrap(self, device_id: str) -> dict[str, Any]:
        """Everything a fresh install needs, in one round trip."""
        from app.models.expense import ExpenseCategory, TaxRate
        from app.models.item import Item, ItemCategory, Unit
        from app.models.party import Party
        from app.models.payment import Account

        state = await self._state(device_id)
        server_seq = await self.current_seq()

        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        cfg = (
            await self.db.execute(
                select(BusinessSettings).where(BusinessSettings.business_id == self.business_id)
            )
        ).scalar_one_or_none()

        async def rows(model: type, limit: int = 5000) -> list[dict[str, Any]]:
            result = await self.db.execute(
                select(model).where(
                    model.business_id == self.business_id, model.is_deleted.is_(False)
                ).limit(limit)
            )
            return [_public(r) for r in result.scalars().all()]

        state.last_pulled_seq = server_seq
        state.last_pulled_at = utcnow()

        return {
            "business": _public(business),
            "settings": _public(cfg) if cfg else {},
            "parties": await rows(Party),
            "items": await rows(Item),
            "categories": await rows(ItemCategory),
            "units": await rows(Unit),
            "tax_rates": await rows(TaxRate),
            "accounts": await rows(Account),
            "expense_categories": await rows(ExpenseCategory),
            "server_seq": server_seq,
            "server_time": utcnow(),
        }

    async def status(self, device_id: str) -> dict[str, Any]:
        state = await self._state(device_id)
        server_seq = await self.current_seq()
        pending = (
            await self.db.execute(
                select(func.count()).select_from(ChangeLog).where(
                    ChangeLog.business_id == self.business_id,
                    ChangeLog.id > state.last_pulled_seq,
                )
            )
        ).scalar_one()
        return {
            "device_id": device_id,
            "last_pulled_seq": state.last_pulled_seq,
            "server_seq": server_seq,
            "pending_pull": int(pending),
            "last_pulled_at": state.last_pulled_at,
            "last_pushed_at": state.last_pushed_at,
            "conflicts": state.pending_conflicts or [],
        }

    async def current_seq(self) -> int:
        value = (
            await self.db.execute(
                select(func.coalesce(func.max(ChangeLog.id), 0)).where(
                    ChangeLog.business_id == self.business_id
                )
            )
        ).scalar_one()
        return int(value)

    # ── helpers ──────────────────────────────────────────────────
    async def _state(
        self, device_id: str, *, platform: str | None = None, app_version: str | None = None
    ) -> SyncState:
        row = (
            await self.db.execute(
                select(SyncState).where(
                    SyncState.business_id == self.business_id, SyncState.device_id == device_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = SyncState(
                business_id=self.business_id, device_id=device_id, user_id=self.actor.user_id
            )
            self.db.add(row)
            await self.db.flush()
        if platform:
            row.platform = platform
        if app_version:
            row.app_version = app_version
        return row

    def _service(self, entity: str):
        path = _ENTITY_SERVICES.get(entity)
        if not path:
            raise AppError(f"Entity '{entity}' cannot be synced.", code="unsupported_entity")
        module_path, class_name = path[0].split(":")
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)(self.db, self.actor)

    def _schema(self, entity: str):
        path = _ENTITY_SERVICES.get(entity)
        if not path or not path[1]:
            return None
        module_path, class_name = path[1].split(":")
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)


class _Conflict(Exception):
    def __init__(
        self,
        *,
        entity: str,
        client_uuid: str,
        server_id: str,
        server_revision: int,
        server_data: dict[str, Any],
    ) -> None:
        self.payload = {
            "entity": entity,
            "client_uuid": client_uuid,
            "server_id": server_id,
            "reason": "stale_revision",
            "message": (
                "This record was changed on another device after your edit. "
                "Review both versions before saving."
            ),
            "server_revision": server_revision,
            "server_data": server_data,
        }
        super().__init__(self.payload["message"])

    def as_dict(self) -> dict[str, Any]:
        return self.payload


def _public(entity: Any) -> dict[str, Any]:
    """Row → JSON-safe dict, minus internal columns."""
    from app.services.base import _jsonable  # noqa: PLC0415

    if entity is None:
        return {}
    hidden = {"password_hash", "access_token_enc", "refresh_token_enc", "code_hash", "salt"}
    return {
        key: _jsonable(value)
        for key, value in entity.to_dict().items()
        if key not in hidden
    }
