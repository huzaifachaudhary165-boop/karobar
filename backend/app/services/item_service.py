"""Item CRUD plus the stock engine (ledger, weighted-average cost, batches)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.barcodes import next_ean13
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.money import ZERO, D, money, qty, safe_div
from app.core.pagination import PageParams, paginate
from app.models.base import utcnow
from app.models.business import BusinessSettings
from app.models.enums import ItemType, SerialStatus, StockMovement
from app.models.item import (
    Godown, GodownStock, Item, ItemBatch, ItemCategory, ItemSerial, StockLedgerEntry, Unit,
)
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.base import ActorContext, BaseService, stamp_sync
from app.utils.strings import rank_matches

# Distinguishes "not looked up yet" from "looked up, and there are no locations".
_UNRESOLVED: Any = object()


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

    async def mint_barcode(self, item: Item, prefix: str = "200") -> str:
        """Give an item an in-store barcode and save it.

        Loose rice, home-made sweets, anything repacked: none of it arrives with
        a manufacturer's code, and a counter cannot scan what has no barcode.
        The 200–299 range exists for exactly this and can never collide with a
        real product's code.

        The next number comes from the highest already issued rather than from a
        count, so deleting an item does not hand its barcode to the next one
        created — two products sharing a code is indistinguishable at the
        counter and impossible to explain afterwards.
        """
        highest = (
            await self.db.execute(
                select(func.max(Item.barcode)).where(
                    Item.business_id == self.business_id,
                    Item.barcode.isnot(None),
                    Item.barcode.like(f"{prefix}%"),
                    func.length(Item.barcode) == 13,
                )
            )
        ).scalar_one_or_none()

        sequence = 1
        if highest and highest[len(prefix):-1].isdigit():
            sequence = int(highest[len(prefix):-1]) + 1

        # A code could still be held by an item outside this run, so walk
        # forward rather than assume the next one is free.
        for _ in range(1000):
            candidate = next_ean13(prefix, sequence)
            if not await self._barcode_taken(candidate):
                item.barcode = candidate
                item.bump_revision()
                await self.track(
                    "update", item, label=item.name, changes={"barcode": [None, candidate]}
                )
                return candidate
            sequence += 1

        raise BusinessRuleError(
            "Could not find a free barcode in the in-store range. "
            "Enter one manually instead."
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
        # Looked up once per service instance: a multi-line bill would otherwise
        # ask for the same default location once per line.
        self._default_godown_id: str | None = _UNRESOLVED
        self._godown_rows: dict[tuple[str, str], GodownStock] = {}

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

        # A transfer is the same goods in a different place. Letting it touch the
        # weighted average would let a shopkeeper change their own cost of sales
        # by moving a carton between rooms.
        if delta > 0 and movement_rate > 0 and movement != StockMovement.TRANSFER:
            old_value = item.avg_cost * item.stock_qty if item.stock_qty > 0 else ZERO
            total_qty = item.stock_qty + delta
            item.avg_cost = money(safe_div(old_value + movement_rate * delta, total_qty, movement_rate))

        item.stock_qty = new_qty
        item.bump_revision()

        if movement != StockMovement.TRANSFER:
            if delta > 0:
                item.last_purchased_at = utcnow()
            elif movement in (StockMovement.OUT,):
                item.last_sold_at = utcnow()

        if batch_id:
            await self._apply_batch(batch_id, delta)

        godown_id = await self._resolve_godown(godown_id)
        if godown_id:
            await self._apply_godown(item.id, godown_id, delta)

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
            if entry.godown_id:
                await self._apply_godown(entry.item_id, entry.godown_id, -entry.qty)
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

    async def transfer(
        self,
        item_id: str,
        *,
        from_godown_id: str,
        to_godown_id: str,
        move_qty: Decimal,
        batch_id: str | None = None,
        note: str | None = None,
        entry_date: date | None = None,
    ) -> tuple[Item, Decimal, Decimal]:
        """Move stock between locations. The business-wide total does not change.

        Posted as two opposing ledger rows rather than a silent edit, so a
        transfer shows up in the item's history like everything else and
        `recalculate` still reconstructs the same total from the ledger.
        """
        if from_godown_id == to_godown_id:
            raise BusinessRuleError("Pick two different locations to transfer between.")

        amount = qty(move_qty)
        if amount <= 0:
            raise BusinessRuleError("Transfer quantity must be more than zero.")

        item = (
            await self.db.execute(
                select(Item).where(
                    Item.id == item_id, Item.business_id == self.business_id, Item.is_deleted.is_(False)
                )
            )
        ).scalar_one_or_none()
        if not item:
            raise NotFoundError("Item not found.", details={"id": item_id})

        source, destination = await self._godown_pair(from_godown_id, to_godown_id)

        available = await self.godown_qty(item_id, from_godown_id)
        if amount > available:
            raise BusinessRuleError(
                f"'{source.name}' only has {available} {item.unit_label} of '{item.name}'.",
                code="insufficient_stock",
                details={"available": str(available), "required": str(amount)},
            )

        stamp = datetime.combine(entry_date, datetime.min.time()) if entry_date else utcnow()
        reason = note or f"Transfer {source.name} → {destination.name}"

        for godown_id, signed in ((from_godown_id, -amount), (to_godown_id, amount)):
            await self.record(
                item,
                qty_delta=signed,
                movement=StockMovement.TRANSFER,
                rate=item.avg_cost,
                entry_date=stamp,
                reference_type="transfer",
                godown_id=godown_id,
                batch_id=batch_id,
                note=reason,
                allow_negative=True,  # already checked against the source location
            )

        return (
            item,
            await self.godown_qty(item_id, from_godown_id),
            await self.godown_qty(item_id, to_godown_id),
        )

    async def godown_qty(self, item_id: str, godown_id: str) -> Decimal:
        key = (item_id, godown_id)
        if key in self._godown_rows:
            return qty(self._godown_rows[key].qty)
        row = (
            await self.db.execute(
                select(GodownStock.qty).where(
                    GodownStock.business_id == self.business_id,
                    GodownStock.item_id == item_id,
                    GodownStock.godown_id == godown_id,
                )
            )
        ).scalar_one_or_none()
        return qty(row or ZERO)

    async def by_godown(self, item_id: str) -> list[tuple[Godown, Decimal]]:
        """Where an item's stock physically sits, largest holding first."""
        rows = (
            await self.db.execute(
                select(Godown, GodownStock.qty)
                .join(GodownStock, GodownStock.godown_id == Godown.id)
                .where(
                    GodownStock.business_id == self.business_id,
                    GodownStock.item_id == item_id,
                    Godown.is_deleted.is_(False),
                )
                .order_by(GodownStock.qty.desc())
            )
        ).all()
        return [(g, qty(q)) for g, q in rows]

    async def _godown_pair(self, from_id: str, to_id: str) -> tuple[Godown, Godown]:
        rows = {
            g.id: g
            for g in (
                await self.db.execute(
                    select(Godown).where(
                        Godown.business_id == self.business_id,
                        Godown.is_deleted.is_(False),
                        Godown.id.in_([from_id, to_id]),
                    )
                )
            ).scalars().all()
        }
        missing = [i for i in (from_id, to_id) if i not in rows]
        if missing:
            raise NotFoundError("Location not found.", details={"id": missing[0]})
        return rows[from_id], rows[to_id]

    async def _apply_batch(self, batch_id: str, delta: Decimal) -> None:
        batch = (
            await self.db.execute(select(ItemBatch).where(ItemBatch.id == batch_id))
        ).scalar_one_or_none()
        if batch:
            batch.qty = qty(batch.qty + delta)

    async def _resolve_godown(self, godown_id: str | None) -> str | None:
        """Name the location a movement belongs to, when the shop keeps any.

        A shop with no locations gets None and no per-location rows at all —
        the feature costs nothing until it is turned on. Once locations exist,
        an unnamed movement lands on the default one, so the per-location
        figures always add up to the item's total instead of quietly drifting.
        """
        if godown_id:
            return godown_id
        if self._default_godown_id is _UNRESOLVED:
            self._default_godown_id = (
                await self.db.execute(
                    select(Godown.id)
                    .where(Godown.business_id == self.business_id, Godown.is_deleted.is_(False))
                    .order_by(Godown.is_default.desc(), Godown.created_at.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return self._default_godown_id

    async def _apply_godown(self, item_id: str, godown_id: str, delta: Decimal) -> None:
        """Adjust one item's holding at one location.

        Rows touched in this request are kept in hand rather than re-queried.
        The session runs with autoflush off, so a fresh SELECT would not see a
        change made moments earlier — and a bill with forty lines would
        otherwise pay for forty round trips to learn what it already knows.
        """
        key = (item_id, godown_id)
        row = self._godown_rows.get(key)

        if row is None:
            row = (
                await self.db.execute(
                    select(GodownStock).where(
                        GodownStock.business_id == self.business_id,
                        GodownStock.item_id == item_id,
                        GodownStock.godown_id == godown_id,
                    )
                )
            ).scalar_one_or_none()

        if row is None:
            row = GodownStock(
                business_id=self.business_id, item_id=item_id, godown_id=godown_id, qty=ZERO
            )
            self.db.add(row)

        row.qty = qty(row.qty + delta)
        self._godown_rows[key] = row

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


class GodownService(BaseService[Godown]):
    """Warehouses, shops and storerooms — anywhere stock physically sits."""

    model = Godown
    entity_name = "godown"

    async def create(self, data: dict[str, Any]) -> Godown:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Location name is required.")
        if await self._name_taken(name):
            raise ConflictError(f"A location named '{name}' already exists.", details={"field": "name"})

        # The first location a shop creates is its default, whatever they ticked:
        # without one, every unnamed movement would have nowhere to land.
        existing = await self.count()
        data["name"] = name
        row = Godown(
            business_id=self.business_id,
            **{k: v for k, v in data.items() if hasattr(Godown, k)},
        )
        if existing == 0:
            row.is_default = True
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()

        if row.is_default and existing:
            await self._demote_others(row.id)
        if existing == 0:
            await self._seed_existing_stock(row.id)
        await self.track("create", row, label=row.name)
        return row

    async def update(self, godown_id: str, data: dict[str, Any]) -> Godown:
        row = await self.get_or_404(godown_id)
        if (new_name := data.get("name")) and new_name.strip().lower() != row.name.lower():
            if await self._name_taken(new_name):
                raise ConflictError(f"A location named '{new_name}' already exists.")
            data["name"] = new_name.strip()

        changes = self.apply_fields(row, data)
        if row.is_default:
            await self._demote_others(row.id)
        if changes:
            row.bump_revision()
            await self.track("update", row, changes=changes, label=row.name)
        return row

    async def delete(self, godown_id: str) -> None:
        row = await self.get_or_404(godown_id)

        held = (
            await self.db.execute(
                select(func.count()).select_from(GodownStock).where(
                    GodownStock.business_id == self.business_id,
                    GodownStock.godown_id == godown_id,
                    GodownStock.qty != 0,
                )
            )
        ).scalar_one()
        if held:
            raise BusinessRuleError(
                f"'{row.name}' still holds stock of {held} item(s). "
                "Transfer it elsewhere before deleting this location.",
                details={"item_count": int(held)},
            )
        if row.is_default and await self.count() > 1:
            raise BusinessRuleError(
                "Make another location the default before deleting this one."
            )
        await self.soft_delete(row, label=row.name)

    async def list_with_stock(self) -> list[dict[str, Any]]:
        """Every location with what it currently holds, for the locations screen."""
        totals = dict(
            (
                await self.db.execute(
                    select(GodownStock.godown_id, func.count(GodownStock.item_id))
                    .where(GodownStock.business_id == self.business_id, GodownStock.qty != 0)
                    .group_by(GodownStock.godown_id)
                )
            ).all()
        )
        values = dict(
            (
                await self.db.execute(
                    select(
                        GodownStock.godown_id,
                        func.sum(GodownStock.qty * func.coalesce(Item.avg_cost, Item.purchase_price)),
                    )
                    .join(Item, Item.id == GodownStock.item_id)
                    .where(GodownStock.business_id == self.business_id, GodownStock.qty != 0)
                    .group_by(GodownStock.godown_id)
                )
            ).all()
        )
        rows = (
            await self.db.execute(
                self.base_query().order_by(Godown.is_default.desc(), Godown.name)
            )
        ).scalars().all()
        return [
            {
                "godown": g,
                "item_count": int(totals.get(g.id, 0)),
                "stock_value": money(values.get(g.id) or ZERO),
            }
            for g in rows
        ]

    async def stock_at(self, godown_id: str, *, limit: int = 200) -> list[tuple[Item, Decimal]]:
        await self.get_or_404(godown_id)
        rows = (
            await self.db.execute(
                select(Item, GodownStock.qty)
                .join(GodownStock, GodownStock.item_id == Item.id)
                .where(
                    GodownStock.business_id == self.business_id,
                    GodownStock.godown_id == godown_id,
                    GodownStock.qty != 0,
                    Item.is_deleted.is_(False),
                )
                .order_by(Item.name)
                .limit(limit)
            )
        ).all()
        return [(i, qty(q)) for i, q in rows]

    async def ensure_default(self, name: str = "Main Store") -> Godown:
        """Give a shop its first location the moment multi-location is switched on."""
        existing = (
            await self.db.execute(
                self.base_query().order_by(Godown.is_default.desc(), Godown.created_at.asc()).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        return await self.create({"name": name, "is_default": True})

    async def count(self) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count()).select_from(Godown).where(
                        Godown.business_id == self.business_id, Godown.is_deleted.is_(False)
                    )
                )
            ).scalar_one()
        )

    async def _seed_existing_stock(self, godown_id: str) -> None:
        """Put everything the shop already owns into its first location.

        Without this, a shop that has been trading for months turns on locations
        and every one of them reads zero while the stock figures say otherwise.
        The goods were always somewhere; the first location is the only honest
        answer to where.
        """
        rows = (
            await self.db.execute(
                select(Item.id, Item.stock_qty).where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.track_inventory.is_(True),
                    Item.stock_qty != 0,
                )
            )
        ).all()
        for item_id, held in rows:
            self.db.add(
                GodownStock(
                    business_id=self.business_id,
                    item_id=item_id,
                    godown_id=godown_id,
                    qty=qty(held),
                )
            )
        if rows:
            await self.db.flush()

    async def _demote_others(self, keep_id: str) -> None:
        for other in (
            await self.db.execute(
                self.base_query().where(Godown.id != keep_id, Godown.is_default.is_(True))
            )
        ).scalars().all():
            other.is_default = False
            other.bump_revision()

    async def _name_taken(self, name: str) -> bool:
        hit = (
            await self.db.execute(
                self.base_query().where(func.lower(Godown.name) == name.strip().lower()).limit(1)
            )
        ).scalar_one_or_none()
        return hit is not None


class BatchService(BaseService[ItemBatch]):
    """Batch/lot numbers with manufacture and expiry dates."""

    model = ItemBatch
    entity_name = "item_batch"

    async def create(self, data: dict[str, Any]) -> ItemBatch:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)

        if client_uuid and (existing := await self.get_by_client_uuid(client_uuid)):
            return existing

        item = await ItemService(self.db, self.actor).get_or_404(data["item_id"])
        number = (data.get("batch_number") or "").strip()
        if not number:
            raise BusinessRuleError("Batch number is required.")
        if await self._number_taken(item.id, number):
            raise ConflictError(
                f"Batch '{number}' already exists for {item.name}.",
                details={"field": "batch_number"},
            )

        mfg, expiry = data.get("manufacture_date"), data.get("expiry_date")
        if mfg and expiry and expiry < mfg:
            raise BusinessRuleError("Expiry date cannot be before the manufacture date.")

        opening = qty(data.pop("qty", ZERO) or ZERO)
        data["batch_number"] = number
        row = ItemBatch(
            business_id=self.business_id,
            qty=ZERO,
            **{k: v for k, v in data.items() if hasattr(ItemBatch, k) and k != "qty"},
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()

        # Opening batch quantity is real stock arriving, so it goes through the
        # ledger like any other receipt rather than being written to two places.
        if opening:
            await StockService(self.db, self.actor).record(
                item,
                qty_delta=opening,
                movement=StockMovement.OPENING,
                rate=row.purchase_price or item.purchase_price,
                batch_id=row.id,
                godown_id=row.godown_id,
                reference_type="batch",
                reference_id=row.id,
                note=f"Opening stock for batch {number}",
            )
        await self.track("create", row, label=f"{item.name} · {number}")
        return row

    async def update(self, batch_id: str, data: dict[str, Any]) -> ItemBatch:
        row = await self.get_or_404(batch_id)
        # Quantity belongs to the ledger, never to a direct edit.
        data.pop("qty", None)
        data.pop("item_id", None)

        mfg = data.get("manufacture_date", row.manufacture_date)
        expiry = data.get("expiry_date", row.expiry_date)
        if mfg and expiry and expiry < mfg:
            raise BusinessRuleError("Expiry date cannot be before the manufacture date.")

        changes = self.apply_fields(row, data)
        if changes:
            row.bump_revision()
            await self.track("update", row, changes=changes, label=row.batch_number)
        return row

    async def delete(self, batch_id: str) -> None:
        row = await self.get_or_404(batch_id)
        if row.qty != 0:
            raise BusinessRuleError(
                f"Batch '{row.batch_number}' still holds {row.qty}. "
                "Adjust it to zero before deleting."
            )
        await self.soft_delete(row, label=row.batch_number)

    async def for_item(self, item_id: str, *, in_stock_only: bool = False) -> list[ItemBatch]:
        stmt = self.base_query().where(ItemBatch.item_id == item_id)
        if in_stock_only:
            stmt = stmt.where(ItemBatch.qty > 0)
        # Earliest expiry first — the order a shop should actually sell them in.
        stmt = stmt.order_by(
            ItemBatch.expiry_date.is_(None), ItemBatch.expiry_date.asc(), ItemBatch.batch_number
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def allocate(self, item_id: str, needed: Decimal) -> list[tuple[ItemBatch, Decimal]]:
        """Pick batches to sell from, first-expiry-first-out.

        FEFO rather than FIFO: for anything with a shelf life the stock that
        expires soonest is the stock that must move, regardless of when it came
        in. Expired batches are never allocated — selling them is the exact
        mistake batch tracking is bought to prevent.
        """
        want = qty(needed)
        if want <= 0:
            return []

        picked: list[tuple[ItemBatch, Decimal]] = []
        remaining = want
        for batch in await self.for_item(item_id, in_stock_only=True):
            if remaining <= 0:
                break
            if batch.is_expired:
                continue
            take = qty(min(batch.qty, remaining))
            if take <= 0:
                continue
            picked.append((batch, take))
            remaining = qty(remaining - take)

        if remaining > 0:
            raise BusinessRuleError(
                f"Only {want - remaining} available across unexpired batches, {want} needed.",
                code="insufficient_batch_stock",
                details={"available": str(want - remaining), "required": str(want)},
            )
        return picked

    async def expiring(self, *, within_days: int = 30, include_expired: bool = True) -> list[dict[str, Any]]:
        """Batches worth acting on today — already expired, or about to be."""
        cutoff = date.today() + timedelta(days=max(0, within_days))
        stmt = (
            select(ItemBatch, Item)
            .join(Item, Item.id == ItemBatch.item_id)
            .where(
                ItemBatch.business_id == self.business_id,
                ItemBatch.is_deleted.is_(False),
                ItemBatch.qty > 0,
                ItemBatch.expiry_date.isnot(None),
                ItemBatch.expiry_date <= cutoff,
                Item.is_deleted.is_(False),
            )
            .order_by(ItemBatch.expiry_date.asc())
        )
        if not include_expired:
            stmt = stmt.where(ItemBatch.expiry_date >= date.today())

        return [
            {
                "batch": b,
                "item": i,
                "value": money(b.qty * (b.purchase_price or i.avg_cost or i.purchase_price)),
            }
            for b, i in (await self.db.execute(stmt)).all()
        ]

    async def _number_taken(self, item_id: str, number: str) -> bool:
        hit = (
            await self.db.execute(
                self.base_query()
                .where(ItemBatch.item_id == item_id, func.lower(ItemBatch.batch_number) == number.lower())
                .limit(1)
            )
        ).scalar_one_or_none()
        return hit is not None


class SerialService(BaseService[ItemSerial]):
    """IMEI / chassis / warranty numbers — one row per physical unit."""

    model = ItemSerial
    entity_name = "item_serial"

    async def add_many(
        self,
        item_id: str,
        serials: list[str],
        *,
        godown_id: str | None = None,
        batch_id: str | None = None,
        purchase_price: Decimal | None = None,
        warranty_months: int | None = None,
        purchase_voucher_id: str | None = None,
        received_on: date | None = None,
    ) -> tuple[list[ItemSerial], list[str]]:
        """Register received units. Returns (added, rejected-as-duplicate).

        Duplicates are reported rather than raised: a shopkeeper scanning
        thirty handsets should not lose the other twenty-nine because one was
        already on the books.
        """
        item = await ItemService(self.db, self.actor).get_or_404(item_id)

        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in serials:
            value = (raw or "").strip()
            if not value or value.lower() in seen:
                continue
            seen.add(value.lower())
            cleaned.append(value)
        if not cleaned:
            raise BusinessRuleError("No serial numbers were given.")

        taken = {
            s.lower()
            for s in (
                await self.db.execute(
                    select(ItemSerial.serial_number).where(
                        ItemSerial.business_id == self.business_id,
                        ItemSerial.is_deleted.is_(False),
                        func.lower(ItemSerial.serial_number).in_([c.lower() for c in cleaned]),
                    )
                )
            ).scalars().all()
        }

        base_date = received_on or date.today()
        added: list[ItemSerial] = []
        rejected: list[str] = []
        for value in cleaned:
            if value.lower() in taken:
                rejected.append(value)
                continue
            row = ItemSerial(
                business_id=self.business_id,
                item_id=item_id,
                serial_number=value,
                status=SerialStatus.IN_STOCK,
                godown_id=godown_id,
                batch_id=batch_id,
                purchase_price=money(purchase_price) if purchase_price is not None else None,
                purchase_voucher_id=purchase_voucher_id,
                warranty_months=warranty_months,
                warranty_until=(
                    base_date + timedelta(days=30 * warranty_months) if warranty_months else None
                ),
            )
            stamp_sync(row, self.actor)
            self.db.add(row)
            added.append(row)

        await self.db.flush()
        if added:
            await self.record_audit(
                "create", added[0].id, label=f"{item.name} × {len(added)}",
                meta={"count": len(added), "rejected": len(rejected)},
            )
        return added, rejected

    async def reserve_for_sale(
        self, item_id: str, serials: list[str], *, voucher_id: str | None = None,
        sale_price: Decimal | None = None,
    ) -> list[ItemSerial]:
        """Mark specific units sold, refusing any that are not actually here."""
        wanted = [s.strip() for s in serials if s and s.strip()]
        if not wanted:
            return []

        rows = list(
            (
                await self.db.execute(
                    self.base_query().where(
                        ItemSerial.item_id == item_id,
                        func.lower(ItemSerial.serial_number).in_([w.lower() for w in wanted]),
                    )
                )
            ).scalars().all()
        )
        found = {r.serial_number.lower(): r for r in rows}

        missing = [w for w in wanted if w.lower() not in found]
        if missing:
            raise BusinessRuleError(
                f"Not in stock: {', '.join(missing[:5])}"
                + (f" and {len(missing) - 5} more" if len(missing) > 5 else ""),
                code="serial_not_found",
                details={"serials": missing},
            )

        already = [r.serial_number for r in rows if not r.is_available]
        if already:
            raise BusinessRuleError(
                f"Already sold: {', '.join(already[:5])}"
                + (f" and {len(already) - 5} more" if len(already) > 5 else ""),
                code="serial_already_sold",
                details={"serials": already},
            )

        for row in rows:
            row.status = SerialStatus.SOLD
            row.sale_voucher_id = voucher_id
            row.sold_at = utcnow()
            if sale_price is not None:
                row.sale_price = money(sale_price)
            if row.warranty_months and not row.warranty_until:
                row.warranty_until = date.today() + timedelta(days=30 * row.warranty_months)
            row.bump_revision()
        return rows

    async def release(self, voucher_id: str) -> int:
        """Put units back in stock when the bill they left on is cancelled."""
        rows = (
            await self.db.execute(
                self.base_query().where(ItemSerial.sale_voucher_id == voucher_id)
            )
        ).scalars().all()
        for row in rows:
            row.status = SerialStatus.IN_STOCK
            row.sale_voucher_id = None
            row.sold_at = None
            row.bump_revision()
        return len(rows)

    async def for_item(
        self, item_id: str, *, status: str | None = None, limit: int = 500
    ) -> list[ItemSerial]:
        stmt = self.base_query().where(ItemSerial.item_id == item_id)
        if status:
            stmt = stmt.where(ItemSerial.status == status)
        return list(
            (await self.db.execute(stmt.order_by(ItemSerial.serial_number).limit(limit)))
            .scalars().all()
        )

    async def available_count(self, item_id: str) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count()).select_from(ItemSerial).where(
                        ItemSerial.business_id == self.business_id,
                        ItemSerial.is_deleted.is_(False),
                        ItemSerial.item_id == item_id,
                        ItemSerial.status.in_([SerialStatus.IN_STOCK, SerialStatus.RETURNED]),
                    )
                )
            ).scalar_one()
        )

    async def lookup(self, serial_number: str) -> tuple[ItemSerial, Item] | None:
        """Scan a serial at the counter and see the unit's whole history."""
        row = (
            await self.db.execute(
                select(ItemSerial, Item)
                .join(Item, Item.id == ItemSerial.item_id)
                .where(
                    ItemSerial.business_id == self.business_id,
                    ItemSerial.is_deleted.is_(False),
                    func.lower(ItemSerial.serial_number) == serial_number.strip().lower(),
                )
                .limit(1)
            )
        ).first()
        return (row[0], row[1]) if row else None
