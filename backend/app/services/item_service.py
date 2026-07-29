"""Item CRUD plus the stock engine (ledger, weighted-average cost, batches)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.money import ZERO, D, money, qty, safe_div
from app.core.pagination import PageParams, paginate
from app.models.base import utcnow
from app.models.business import BusinessSettings
from app.models.enums import ItemType, StockMovement
from app.models.item import Item, ItemBatch, ItemCategory, StockLedgerEntry, Unit
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.base import ActorContext, BaseService, stamp_sync
from app.utils.strings import rank_matches


class ItemService(BaseService[Item]):
    model = Item
    entity_name = "item"

    async def create(self, payload: ItemCreate | dict[str, Any]) -> Item:
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        if client_uuid:
            existing = await self.get_by_client_uuid(client_uuid)
            if existing:
                return existing

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Item name is required.")
        if await self._name_taken(name):
            raise ConflictError(f"An item named '{name}' already exists.", details={"field": "name"})
        if data.get("barcode") and await self._barcode_taken(data["barcode"]):
            raise ConflictError("This barcode is already used by another item.", details={"field": "barcode"})

        opening = qty(data.pop("opening_stock", ZERO) or ZERO)
        opening_value = money(data.pop("opening_stock_value", ZERO) or ZERO)
        opening_date = data.pop("opening_stock_date", None)

        item = Item(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            opening_stock=opening,
            opening_stock_value=opening_value,
            opening_stock_date=opening_date,
            # stock_qty stays at zero here: the opening balance is posted through
            # StockService below so the ledger and the live figure can never disagree.
            stock_qty=ZERO,
            avg_cost=(
                money(safe_div(opening_value, opening))
                if opening
                else money(data.get("purchase_price", ZERO))
            ),
            **{k: v for k, v in data.items() if hasattr(Item, k)},
        )
        stamp_sync(item, self.actor, client_uuid=client_uuid)
        self.db.add(item)
        await self.db.flush()

        if opening and item.track_inventory:
            await StockService(self.db, self.actor).record(
                item,
                qty_delta=opening,
                movement=StockMovement.OPENING,
                rate=item.avg_cost,
                entry_date=datetime.combine(opening_date or date.today(), datetime.min.time()),
                note="Opening stock",
            )
        await self.track("create", item, label=item.name)
        return item

    async def update(self, item_id: str, payload: ItemUpdate | dict[str, Any]) -> Item:
        item = await self.get_or_404(item_id)
        data = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else dict(payload)

        if (new_name := data.get("name")) and new_name.strip().lower() != item.name.lower():
            if await self._name_taken(new_name):
                raise ConflictError(f"An item named '{new_name}' already exists.")
        if (bc := data.get("barcode")) and bc != item.barcode and await self._barcode_taken(bc):
            raise ConflictError("This barcode is already used by another item.")

        # stock_qty is owned by StockService — never settable directly
        data.pop("stock_qty", None)

        changes = self.apply_fields(item, data)
        if changes:
            item.updated_by = self.actor.user_id
            item.bump_revision()
            await self.track("update", item, changes=changes, label=item.name)
        return item

    async def delete(self, item_id: str) -> None:
        from app.models.voucher import VoucherLine  # local import avoids a cycle

        item = await self.get_or_404(item_id)
        used = (
            await self.db.execute(
                select(func.count()).select_from(VoucherLine).where(
                    VoucherLine.business_id == self.business_id, VoucherLine.item_id == item_id
                )
            )
        ).scalar_one()
        if used:
            raise BusinessRuleError(
                f"'{item.name}' appears on {used} transaction(s) and cannot be deleted. "
                "Mark it inactive instead.",
                details={"usage_count": int(used)},
            )
        await self.soft_delete(item, label=item.name)

    async def list(
        self,
        params: PageParams,
        *,
        search: str | None = None,
        category_id: str | None = None,
        item_type: str | None = None,
        only_low_stock: bool = False,
        only_out_of_stock: bool = False,
        is_active: bool | None = None,
    ) -> tuple[list[Item], int]:
        stmt = self.base_query()
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Item.name).like(like),
                    func.lower(func.coalesce(Item.sku, "")).like(like),
                    func.lower(func.coalesce(Item.barcode, "")).like(like),
                    func.lower(func.coalesce(Item.hsn_code, "")).like(like),
                    func.lower(func.coalesce(Item.description, "")).like(like),
                )
            )
        if category_id:
            stmt = stmt.where(Item.category_id == category_id)
        if item_type:
            stmt = stmt.where(Item.item_type == item_type)
        if is_active is not None:
            stmt = stmt.where(Item.is_active.is_(is_active))
        if only_out_of_stock:
            stmt = stmt.where(Item.track_inventory.is_(True), Item.stock_qty <= 0)
        elif only_low_stock:
            stmt = stmt.where(
                Item.track_inventory.is_(True),
                Item.low_stock_qty.isnot(None),
                Item.stock_qty <= Item.low_stock_qty,
            )
        return await paginate(self.db, stmt, params, model=Item, default_sort="name")

    async def find_by_barcode(self, barcode: str) -> Item | None:
        return (
            await self.db.execute(self.base_query().where(Item.barcode == barcode.strip()).limit(1))
        ).scalar_one_or_none()

    async def search_by_name(self, query: str, limit: int = 5) -> list[tuple[Item, float]]:
        """Fuzzy item lookup for AI/OCR: 'sugar 1kg' → 'Sugar (1 KG Pack)'."""
        if not query or not query.strip():
            return []
        like = f"%{query.strip().lower()[:40]}%"
        pool = list(
            (
                await self.db.execute(
                    self.base_query().where(
                        or_(
                            func.lower(Item.name).like(like),
                            func.lower(func.coalesce(Item.sku, "")).like(like),
                            func.lower(func.coalesce(Item.barcode, "")).like(like),
                        )
                    ).limit(25)
                )
            ).scalars().all()
        )
        if len(pool) < 3:
            pool += list((await self.db.execute(self.base_query().limit(500))).scalars().all())
        by_id = {i.id: i for i in pool}
        ranked = rank_matches(query, [(i.id, i.name) for i in by_id.values()], limit=limit)
        return [(by_id[iid], score) for iid, _n, score in ranked]

    async def resolve_or_create(
        self, name: str, *, sale_price: Decimal | None = None, purchase_price: Decimal | None = None
    ) -> tuple[Item, bool]:
        matches = await self.search_by_name(name, limit=1)
        if matches and matches[0][1] >= 0.85:
            return matches[0][0], False
        item = await self.create(
            ItemCreate(  # type: ignore[arg-type]
                name=name.strip(),
                sale_price=money(sale_price or ZERO),
                purchase_price=money(purchase_price or ZERO),
            )
        )
        return item, True

    async def stock_summary(self) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                self.base_query().where(Item.track_inventory.is_(True), Item.is_active.is_(True))
            )
        ).scalars().all()

        total_value = money(sum((i.stock_value for i in rows), ZERO))
        low = [i for i in rows if i.is_low_stock and i.stock_qty > 0]
        out = [i for i in rows if i.stock_qty <= 0]

        expiring = (
            await self.db.execute(
                select(func.count()).select_from(ItemBatch).where(
                    ItemBatch.business_id == self.business_id,
                    ItemBatch.is_deleted.is_(False),
                    ItemBatch.qty > 0,
                    ItemBatch.expiry_date.isnot(None),
                    ItemBatch.expiry_date <= date.today() + timedelta(days=30),
                )
            )
        ).scalar_one()

        top = sorted(rows, key=lambda i: i.stock_value, reverse=True)[:10]
        return {
            "total_items": len(rows),
            "total_stock_value": total_value,
            "low_stock_count": len(low),
            "out_of_stock_count": len(out),
            "expiring_soon_count": int(expiring),
            "top_value_items": top,
        }

    async def low_stock_items(self, limit: int = 20) -> list[Item]:
        return list(
            (
                await self.db.execute(
                    self.base_query()
                    .where(
                        Item.track_inventory.is_(True),
                        Item.is_active.is_(True),
                        Item.low_stock_qty.isnot(None),
                        Item.stock_qty <= Item.low_stock_qty,
                    )
                    .order_by(Item.stock_qty.asc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    async def _name_taken(self, name: str) -> bool:
        hit = (
            await self.db.execute(
                self.base_query().where(func.lower(Item.name) == name.strip().lower()).limit(1)
            )
        ).scalar_one_or_none()
        return hit is not None

    async def _barcode_taken(self, barcode: str) -> bool:
        hit = (
            await self.db.execute(self.base_query().where(Item.barcode == barcode.strip()).limit(1))
        ).scalar_one_or_none()
        return hit is not None


class StockService:
    """Owns every mutation of Item.stock_qty. Nothing else may write that field."""

    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def record(
        self,
        item: Item,
        *,
        qty_delta: Decimal,
        movement: str,
        rate: Decimal | None = None,
        entry_date: datetime | None = None,
        reference_type: str | None = None,
        reference_id: str | None = None,
        reference_number: str | None = None,
        party_id: str | None = None,
        batch_id: str | None = None,
        godown_id: str | None = None,
        note: str | None = None,
        allow_negative: bool | None = None,
    ) -> StockLedgerEntry | None:
        """Apply a signed stock movement and append a ledger row.

        Positive qty_delta = stock in. Weighted-average cost only moves on inward
        movements, which is what makes COGS stable across price changes.
        """
        if not item.track_inventory or item.item_type == ItemType.SERVICE:
            return None

        delta = qty(qty_delta)
        if delta == 0:
            return None

        new_qty = qty(item.stock_qty + delta)
        if new_qty < 0:
            permitted = allow_negative if allow_negative is not None else await self._negative_allowed()
            if not permitted:
                raise BusinessRuleError(
                    f"Not enough stock for '{item.name}'. Available {item.stock_qty} "
                    f"{item.unit_label}, needed {abs(delta)}.",
                    code="insufficient_stock",
                    details={
                        "item_id": item.id, "item_name": item.name,
                        "available": str(item.stock_qty), "required": str(abs(delta)),
                    },
                )

        movement_rate = money(rate if rate is not None else (item.avg_cost or item.purchase_price))

        if delta > 0 and movement_rate > 0:
            old_value = item.avg_cost * item.stock_qty if item.stock_qty > 0 else ZERO
            total_qty = item.stock_qty + delta
            item.avg_cost = money(safe_div(old_value + movement_rate * delta, total_qty, movement_rate))

        item.stock_qty = new_qty
        item.bump_revision()

        if delta > 0:
            item.last_purchased_at = utcnow()
        elif movement in (StockMovement.OUT,):
            item.last_sold_at = utcnow()

        if batch_id:
            await self._apply_batch(batch_id, delta)

        entry = StockLedgerEntry(
            business_id=self.business_id,
            item_id=item.id,
            batch_id=batch_id,
            godown_id=godown_id,
            movement=movement,
            qty=delta,
            balance_after=new_qty,
            rate=movement_rate,
            value=money(movement_rate * abs(delta)),
            entry_date=entry_date or utcnow(),
            reference_type=reference_type,
            reference_id=reference_id,
            reference_number=reference_number,
            party_id=party_id,
            note=note,
            created_by=self.actor.user_id,
        )
        self.db.add(entry)
        return entry

    async def reverse(self, reference_type: str, reference_id: str) -> int:
        """Undo every movement made by a document (used when editing/cancelling)."""
        entries = (
            await self.db.execute(
                select(StockLedgerEntry).where(
                    StockLedgerEntry.business_id == self.business_id,
                    StockLedgerEntry.reference_type == reference_type,
                    StockLedgerEntry.reference_id == reference_id,
                )
            )
        ).scalars().all()

        reversed_count = 0
        for entry in entries:
            item = (
                await self.db.execute(select(Item).where(Item.id == entry.item_id))
            ).scalar_one_or_none()
            if not item:
                continue
            item.stock_qty = qty(item.stock_qty - entry.qty)
            item.bump_revision()
            if entry.batch_id:
                await self._apply_batch(entry.batch_id, -entry.qty)
            await self.db.delete(entry)
            reversed_count += 1
        return reversed_count

    async def adjust(
        self,
        item_id: str,
        *,
        qty_delta: Decimal,
        movement: str = StockMovement.ADJUSTMENT,
        rate: Decimal | None = None,
        reason: str | None = None,
        batch_id: str | None = None,
        godown_id: str | None = None,
        entry_date: date | None = None,
    ) -> Item:
        item = (
            await self.db.execute(
                select(Item).where(
                    Item.id == item_id, Item.business_id == self.business_id, Item.is_deleted.is_(False)
                )
            )
        ).scalar_one_or_none()
        if not item:
            raise NotFoundError("Item not found.", details={"id": item_id})

        await self.record(
            item,
            qty_delta=qty_delta,
            movement=movement,
            rate=rate,
            entry_date=datetime.combine(entry_date, datetime.min.time()) if entry_date else None,
            reference_type="adjustment",
            note=reason or "Manual stock adjustment",
            allow_negative=True,   # an explicit adjustment is the user's decision
        )
        return item

    async def ledger(
        self,
        item_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int = 200,
    ) -> list[StockLedgerEntry]:
        stmt = select(StockLedgerEntry).where(
            StockLedgerEntry.business_id == self.business_id,
            StockLedgerEntry.item_id == item_id,
        )
        if start:
            stmt = stmt.where(StockLedgerEntry.entry_date >= datetime.combine(start, datetime.min.time()))
        if end:
            stmt = stmt.where(StockLedgerEntry.entry_date <= datetime.combine(end, datetime.max.time()))
        stmt = stmt.order_by(StockLedgerEntry.entry_date.desc()).limit(limit)
        return list((await self.db.execute(stmt)).scalars().all())

    async def recalculate(self, item_id: str) -> Decimal:
        """Rebuild stock_qty from the ledger — the repair path."""
        item = (
            await self.db.execute(select(Item).where(Item.id == item_id, Item.business_id == self.business_id))
        ).scalar_one_or_none()
        if not item:
            raise NotFoundError("Item not found.")
        total = (
            await self.db.execute(
                select(func.coalesce(func.sum(StockLedgerEntry.qty), 0)).where(
                    StockLedgerEntry.business_id == self.business_id,
                    StockLedgerEntry.item_id == item_id,
                )
            )
        ).scalar_one()
        item.stock_qty = qty(D(total))
        item.bump_revision()
        return item.stock_qty

    async def _apply_batch(self, batch_id: str, delta: Decimal) -> None:
        batch = (
            await self.db.execute(select(ItemBatch).where(ItemBatch.id == batch_id))
        ).scalar_one_or_none()
        if batch:
            batch.qty = qty(batch.qty + delta)

    async def _negative_allowed(self) -> bool:
        cfg = (
            await self.db.execute(
                select(BusinessSettings.allow_negative_stock).where(
                    BusinessSettings.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()
        return bool(cfg)


class CategoryService(BaseService[ItemCategory]):
    model = ItemCategory
    entity_name = "item_category"

    async def create(self, data: dict[str, Any]) -> ItemCategory:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        row = ItemCategory(
            business_id=self.business_id,
            **{k: v for k, v in data.items() if hasattr(ItemCategory, k)},
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()
        await self.track("create", row, label=row.name)
        return row

    async def list_with_counts(self) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(ItemCategory, func.count(Item.id))
                .outerjoin(Item, (Item.category_id == ItemCategory.id) & (Item.is_deleted.is_(False)))
                .where(ItemCategory.business_id == self.business_id, ItemCategory.is_deleted.is_(False))
                .group_by(ItemCategory.id)
                .order_by(ItemCategory.sort_order, ItemCategory.name)
            )
        ).all()
        return [{"category": c, "item_count": int(n)} for c, n in rows]


class UnitService(BaseService[Unit]):
    model = Unit
    entity_name = "unit"

    async def create(self, data: dict[str, Any]) -> Unit:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        row = Unit(business_id=self.business_id, **{k: v for k, v in data.items() if hasattr(Unit, k)})
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()
        await self.track("create", row, label=row.name)
        return row

    async def list_all(self) -> list[Unit]:
        return list((await self.db.execute(self.base_query().order_by(Unit.name))).scalars().all())
