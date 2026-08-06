"""In-app notifications.

Notifications are *derived* from business state rather than fired at write time:
`refresh()` looks at what is overdue, low or expiring right now and reconciles the
list. That way a reminder disappears on its own once the invoice is paid, instead
of lingering as a stale row someone has to dismiss.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.money import money
from app.core.pagination import PageParams, paginate
from app.models.base import utcnow
from app.models.business import Business
from app.models.enums import NotificationChannel, VoucherStatus, VoucherType
from app.models.item import Item, ItemBatch
from app.models.system import Notification
from app.models.voucher import Voucher
from app.services.base import ActorContext, BaseService

# One row per (kind, entity) — re-running refresh updates rather than duplicates.
KIND_PAYMENT_DUE = "payment_due"
KIND_LOW_STOCK = "low_stock"
KIND_EXPIRING = "expiring_stock"
KIND_STALE_QUOTATION = "stale_quotation"


class NotificationService(BaseService[Notification]):
    model = Notification
    entity_name = "notification"

    # ── reading ──────────────────────────────────────────────────
    async def list(
        self, params: PageParams, *, only_unread: bool = False, kind: str | None = None
    ) -> tuple[list[Notification], int]:
        stmt = select(Notification).where(Notification.business_id == self.business_id)
        if only_unread:
            stmt = stmt.where(Notification.is_read.is_(False))
        if kind:
            stmt = stmt.where(Notification.kind == kind)
        return await paginate(self.db, stmt, params, model=Notification, default_sort="created_at")

    async def unread_count(self) -> int:
        value = (
            await self.db.execute(
                select(func.count()).select_from(Notification).where(
                    Notification.business_id == self.business_id,
                    Notification.is_read.is_(False),
                )
            )
        ).scalar_one()
        return int(value)

    async def mark_read(self, notification_id: str) -> Notification:
        row = (
            await self.db.execute(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.business_id == self.business_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Notification not found.")
        if not row.is_read:
            row.is_read = True
            row.read_at = utcnow()
        return row

    async def mark_all_read(self) -> int:
        rows = (
            await self.db.execute(
                select(Notification).where(
                    Notification.business_id == self.business_id,
                    Notification.is_read.is_(False),
                )
            )
        ).scalars().all()
        for row in rows:
            row.is_read = True
            row.read_at = utcnow()
        return len(rows)

    async def clear(self) -> int:
        rows = (
            await self.db.execute(
                select(Notification).where(Notification.business_id == self.business_id)
            )
        ).scalars().all()
        for row in rows:
            await self.db.delete(row)
        return len(rows)

    # ── generation ───────────────────────────────────────────────
    async def refresh(self) -> list[Notification]:
        """Reconcile notifications against current business state."""
        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        symbol = business.currency_symbol

        existing = {
            (row.kind, row.entity_id): row
            for row in (
                await self.db.execute(
                    select(Notification).where(Notification.business_id == self.business_id)
                )
            ).scalars().all()
        }
        seen: set[tuple[str, str | None]] = set()
        live: list[Notification] = []

        for spec in [
            *await self._overdue_specs(symbol),
            *await self._low_stock_specs(),
            *await self._expiring_specs(),
            *await self._stale_quotation_specs(symbol),
        ]:
            key = (spec["kind"], spec.get("entity_id"))
            seen.add(key)
            row = existing.get(key)
            if row is None:
                row = Notification(
                    business_id=self.business_id,
                    channel=NotificationChannel.IN_APP,
                    **spec,
                )
                self.db.add(row)
            else:
                # Keep the read flag; refresh the wording and figures.
                row.title = spec["title"]
                row.body = spec["body"]
                row.data = spec.get("data") or {}
            live.append(row)

        # Anything no longer true is dropped rather than left to rot.
        for key, row in existing.items():
            if key not in seen and row.kind in {
                KIND_PAYMENT_DUE, KIND_LOW_STOCK, KIND_EXPIRING, KIND_STALE_QUOTATION
            }:
                await self.db.delete(row)

        await self.db.flush()
        return live

    async def _overdue_specs(self, symbol: str) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.balance_amount > 0,
                    Voucher.due_date.isnot(None),
                    Voucher.due_date < date.today(),
                    Voucher.status.notin_([VoucherStatus.CANCELLED, VoucherStatus.DRAFT]),
                )
                .order_by(Voucher.due_date)
                .limit(25)
            )
        ).scalars().all()

        return [
            {
                "kind": KIND_PAYMENT_DUE,
                "title": f"{voucher.party_name or 'A customer'} is {voucher.days_overdue} days overdue",
                "body": (
                    f"{symbol} {money(voucher.balance_amount)} due on invoice "
                    f"{voucher.number}."
                ),
                "entity_type": "voucher",
                "entity_id": voucher.id,
                "data": {
                    "route": f"/invoices/{voucher.id}",
                    "party_id": voucher.party_id,
                    "amount": str(money(voucher.balance_amount)),
                    "days_overdue": voucher.days_overdue,
                },
            }
            for voucher in rows
        ]

    async def _low_stock_specs(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Item)
                .where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.is_active.is_(True),
                    Item.track_inventory.is_(True),
                    Item.low_stock_qty.isnot(None),
                    Item.stock_qty <= Item.low_stock_qty,
                )
                .order_by(Item.stock_qty)
                .limit(25)
            )
        ).scalars().all()

        specs = []
        for item in rows:
            out_of_stock = item.stock_qty <= 0
            specs.append(
                {
                    "kind": KIND_LOW_STOCK,
                    "title": f"{item.name} is {'out of stock' if out_of_stock else 'running low'}",
                    "body": (
                        "None left — reorder before the next sale."
                        if out_of_stock
                        else f"Only {item.stock_qty} {item.unit_label} left."
                    ),
                    "entity_type": "item",
                    "entity_id": item.id,
                    "data": {"route": f"/items/{item.id}", "stock": str(item.stock_qty)},
                }
            )
        return specs

    async def _expiring_specs(self) -> list[dict[str, Any]]:
        cutoff = date.today() + timedelta(days=30)
        rows = (
            await self.db.execute(
                select(ItemBatch, Item)
                .join(Item, Item.id == ItemBatch.item_id)
                .where(
                    ItemBatch.business_id == self.business_id,
                    ItemBatch.is_deleted.is_(False),
                    ItemBatch.qty > 0,
                    ItemBatch.expiry_date.isnot(None),
                    ItemBatch.expiry_date <= cutoff,
                )
                .order_by(ItemBatch.expiry_date)
                .limit(25)
            )
        ).all()

        specs = []
        for batch, item in rows:
            days = batch.days_to_expiry or 0
            specs.append(
                {
                    "kind": KIND_EXPIRING,
                    "title": (
                        f"{item.name} batch {batch.batch_number} has expired"
                        if days < 0
                        else f"{item.name} expires in {days} days"
                    ),
                    "body": f"{batch.qty} {item.unit_label} in batch {batch.batch_number}.",
                    "entity_type": "item_batch",
                    "entity_id": batch.id,
                    "data": {"route": f"/items/{item.id}", "expiry": batch.expiry_date.isoformat()},
                }
            )
        return specs

    async def _stale_quotation_specs(self, symbol: str) -> list[dict[str, Any]]:
        cutoff = date.today() - timedelta(days=7)
        rows = (
            await self.db.execute(
                select(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.voucher_type == VoucherType.QUOTATION,
                    Voucher.status == VoucherStatus.UNPAID,
                    Voucher.voucher_date <= cutoff,
                )
                .order_by(Voucher.voucher_date)
                .limit(15)
            )
        ).scalars().all()

        return [
            {
                "kind": KIND_STALE_QUOTATION,
                "title": f"Quotation {voucher.number} is waiting for a reply",
                "body": (
                    f"Sent to {voucher.party_name or 'a customer'} for "
                    f"{symbol} {money(voucher.total)}. Follow up to convert it."
                ),
                "entity_type": "voucher",
                "entity_id": voucher.id,
                "data": {"route": f"/invoices/{voucher.id}"},
            }
            for voucher in rows
        ]
