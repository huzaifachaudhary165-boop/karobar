"""Recipes, and the runs that turn raw stock into finished stock."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.manufacturing import Component, Costing, cost_run, max_producible
from app.core.money import ZERO, money, qty
from app.models.enums import StockMovement
from app.models.item import Item
from app.models.manufacturing import (
    BillOfMaterials, BomComponent, ConsumedMaterial, ProductionRun,
)
from app.services.base import BaseService, stamp_sync
from app.services.item_service import StockService
from app.services.numbering_service import NumberingService

PRODUCTION_SERIES = "production"


class BomService(BaseService[BillOfMaterials]):
    """Recipes."""

    model = BillOfMaterials
    entity_name = "bill_of_materials"

    async def create(self, data: dict[str, Any]) -> BillOfMaterials:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        components = data.pop("components", []) or []

        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Give the recipe a name.")
        if await self._name_taken(name):
            raise ConflictError(f"A recipe called '{name}' already exists.")
        if not components:
            raise BusinessRuleError("A recipe needs at least one material.")

        item = await self._item(data["item_id"])
        if (output := qty(data.get("output_qty") or 1)) <= 0:
            raise BusinessRuleError("Say how many one run of this recipe produces.")

        seen: set[str] = set()
        for row in components:
            if row["item_id"] == item.id:
                raise BusinessRuleError(
                    f"'{item.name}' cannot be an ingredient in its own recipe."
                )
            if row["item_id"] in seen:
                raise BusinessRuleError("The same material is listed twice.")
            if qty(row.get("qty") or 0) <= 0:
                raise BusinessRuleError("Every material needs a quantity.")
            seen.add(row["item_id"])

        data["name"] = name
        data["output_qty"] = output
        bom = BillOfMaterials(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            **{k: v for k, v in data.items() if hasattr(BillOfMaterials, k)},
        )
        stamp_sync(bom, self.actor, client_uuid=client_uuid)
        self.db.add(bom)
        await self.db.flush()

        for row in components:
            component = BomComponent(
                business_id=self.business_id,
                bom_id=bom.id,
                item_id=row["item_id"],
                qty=qty(row["qty"]),
                note=row.get("note"),
            )
            stamp_sync(component, self.actor)
            self.db.add(component)

        await self.db.flush()
        await self.db.refresh(bom)
        await self.track("create", bom, label=bom.name)
        return bom

    async def update(self, bom_id: str, data: dict[str, Any]) -> BillOfMaterials:
        bom = await self.get_or_404(bom_id)
        components = data.pop("components", None)

        if (name := data.get("name")) and name.strip().lower() != bom.name.lower():
            if await self._name_taken(name):
                raise ConflictError(f"A recipe called '{name}' already exists.")
            data["name"] = name.strip()

        changes = self.apply_fields(bom, data)

        if components is not None:
            if not components:
                raise BusinessRuleError("A recipe needs at least one material.")
            for existing in list(bom.components):
                await self.db.delete(existing)
            await self.db.flush()

            for row in components:
                if row["item_id"] == bom.item_id:
                    raise BusinessRuleError(
                        "An item cannot be an ingredient in its own recipe."
                    )
                self.db.add(
                    BomComponent(
                        business_id=self.business_id,
                        bom_id=bom.id,
                        item_id=row["item_id"],
                        qty=qty(row["qty"]),
                        note=row.get("note"),
                    )
                )
            changes["components"] = ["…", f"{len(components)} materials"]

        if changes:
            bom.bump_revision()
            await self.track("update", bom, changes=changes, label=bom.name)
        await self.db.flush()
        await self.db.refresh(bom)
        return bom

    async def delete(self, bom_id: str) -> None:
        bom = await self.get_or_404(bom_id)
        used = (
            await self.db.execute(
                select(func.count()).select_from(ProductionRun).where(
                    ProductionRun.business_id == self.business_id,
                    ProductionRun.bom_id == bom_id,
                    ProductionRun.is_deleted.is_(False),
                )
            )
        ).scalar_one()
        if used:
            # The runs keep their own costs, so the recipe is only a label to
            # them — but losing the name would make those runs unreadable.
            raise BusinessRuleError(
                f"'{bom.name}' has been used for {used} production run(s). "
                "Switch it off instead of deleting it.",
                details={"run_count": int(used)},
            )
        await self.soft_delete(bom, label=bom.name)

    async def list_all(self, *, only_active: bool = False) -> list[BillOfMaterials]:
        stmt = self.base_query()
        if only_active:
            stmt = stmt.where(BillOfMaterials.is_active.is_(True))
        return list(
            (await self.db.execute(stmt.order_by(BillOfMaterials.name))).scalars().all()
        )

    async def costing(self, bom_id: str, making: Decimal | None = None) -> Costing:
        """What making this many would need and cost, with today's rates."""
        bom = await self.get_or_404(bom_id)
        components = await self._components_of(bom)
        return cost_run(
            components,
            output_qty=bom.output_qty,
            making=making or bom.output_qty,
            labour_cost=bom.labour_cost,
            overhead_cost=bom.overhead_cost,
            wastage_percent=bom.wastage_percent,
        )

    async def capacity(self, bom_id: str) -> Decimal:
        bom = await self.get_or_404(bom_id)
        return max_producible(await self._components_of(bom), bom.output_qty)

    async def _components_of(self, bom: BillOfMaterials) -> list[Component]:
        if not bom.components:
            return []
        items = {
            item.id: item
            for item in (
                await self.db.execute(
                    select(Item).where(
                        Item.id.in_([c.item_id for c in bom.components])
                    )
                )
            ).scalars().all()
        }
        out = []
        for component in bom.components:
            item = items.get(component.item_id)
            if item is None:
                continue
            out.append(
                Component(
                    item_id=item.id,
                    item_name=item.name,
                    qty_per_batch=component.qty,
                    # Weighted average, not the list price: what the shop
                    # actually paid is what the finished thing actually cost.
                    rate=item.avg_cost or item.purchase_price,
                    available=item.stock_qty if item.track_inventory else None,
                )
            )
        return out

    async def _item(self, item_id: str) -> Item:
        item = (
            await self.db.execute(
                select(Item).where(
                    Item.id == item_id,
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise NotFoundError("Item not found.", details={"id": item_id})
        return item

    async def _name_taken(self, name: str) -> bool:
        hit = (
            await self.db.execute(
                self.base_query()
                .where(func.lower(BillOfMaterials.name) == name.strip().lower())
                .limit(1)
            )
        ).scalar_one_or_none()
        return hit is not None


class ProductionService(BaseService[ProductionRun]):
    """Actually making the thing."""

    model = ProductionRun
    entity_name = "production_run"

    def __init__(self, db, actor) -> None:
        super().__init__(db, actor)
        self.stock = StockService(db, actor)
        self.numbering = NumberingService(db, self.business_id)
        self.boms = BomService(db, actor)

    async def run(self, data: dict[str, Any]) -> ProductionRun:
        """Consume the materials, produce the finished units, record the cost."""
        bom = await self.boms.get_or_404(data["bom_id"])
        if not bom.is_active:
            raise BusinessRuleError(f"'{bom.name}' is switched off.")

        making = qty(data.get("qty") or 0)
        if making <= 0:
            raise BusinessRuleError("Set how many to make.")

        when = data.get("run_date") or date.today()
        components = await self.boms._components_of(bom)
        costing = cost_run(
            components,
            output_qty=bom.output_qty,
            making=making,
            labour_cost=bom.labour_cost,
            overhead_cost=bom.overhead_cost,
            wastage_percent=bom.wastage_percent,
        )

        # Checked before anything moves, so a run that cannot finish does not
        # leave half the materials consumed and no finished goods to show.
        if costing.shortages:
            short = costing.shortages[0]
            raise BusinessRuleError(
                f"Not enough {short.item_name}: {short.needed} needed, "
                f"{short.available} on hand.",
                code="insufficient_materials",
                details={
                    "shortages": [
                        {
                            "item_id": row.item_id,
                            "item_name": row.item_name,
                            "needed": str(row.needed),
                            "available": str(row.available),
                            "short_by": str(row.shortfall),
                        }
                        for row in costing.shortages
                    ]
                },
            )

        finished = await self.boms._item(bom.item_id)
        number, _seq = await self.numbering.next_number(PRODUCTION_SERIES, on_date=when)

        run = ProductionRun(
            business_id=self.business_id,
            created_by=self.actor.user_id,
            number=number,
            bom_id=bom.id,
            item_id=finished.id,
            item_name=finished.name,
            run_date=when,
            qty=making,
            material_cost=costing.material_cost,
            labour_cost=costing.labour_cost,
            overhead_cost=costing.overhead_cost,
            wastage_cost=costing.wastage_cost,
            total_cost=costing.total_cost,
            unit_cost=costing.unit_cost,
            godown_id=data.get("godown_id"),
            notes=data.get("notes"),
        )
        stamp_sync(run, self.actor, client_uuid=data.get("client_uuid"))
        self.db.add(run)
        await self.db.flush()

        stamp = datetime.combine(when, datetime.min.time())

        for requirement in costing.requirements:
            material = await self.boms._item(requirement.item_id)
            await self.stock.record(
                material,
                qty_delta=-requirement.needed,
                movement=StockMovement.OUT,
                rate=requirement.rate,
                entry_date=stamp,
                reference_type="production",
                reference_id=run.id,
                reference_number=number,
                godown_id=run.godown_id,
                note=f"Used making {finished.name}",
            )
            self.db.add(
                ConsumedMaterial(
                    business_id=self.business_id,
                    run_id=run.id,
                    item_id=requirement.item_id,
                    item_name=requirement.item_name,
                    qty=requirement.needed,
                    rate=requirement.rate,
                    value=requirement.value,
                )
            )

        # The finished goods arrive at what they cost to make, which is what
        # keeps the weighted average — and therefore every margin the shop
        # reads afterwards — honest.
        await self.stock.record(
            finished,
            qty_delta=making,
            movement=StockMovement.IN,
            rate=costing.unit_cost,
            entry_date=stamp,
            reference_type="production",
            reference_id=run.id,
            reference_number=number,
            godown_id=run.godown_id,
            note=f"Made ({number})",
        )

        await self.db.flush()
        await self.db.refresh(run)
        await self.track("create", run, label=f"{number} · {finished.name}")
        return run

    async def delete(self, run_id: str) -> None:
        """Undo a run: the finished units come off, the materials go back."""
        run = await self.get_or_404(run_id)
        finished = await self.boms._item(run.item_id)

        if finished.stock_qty < run.qty:
            raise BusinessRuleError(
                f"Only {finished.stock_qty} {finished.unit_label} of "
                f"'{finished.name}' are left, and this run made {run.qty}. "
                "Some have already been sold.",
                details={"available": str(finished.stock_qty)},
            )

        # One reversal, not two half-reversals: `reverse` undoes every ledger
        # row this run wrote, in both directions, so the materials and the
        # finished goods can never end up out of step with each other.
        await self.stock.reverse("production", run.id)
        await self.soft_delete(run, label=run.number)

    async def list_all(
        self, *, start: date | None = None, end: date | None = None, limit: int = 100
    ) -> list[ProductionRun]:
        stmt = self.base_query()
        if start:
            stmt = stmt.where(ProductionRun.run_date >= start)
        if end:
            stmt = stmt.where(ProductionRun.run_date <= end)
        return list(
            (
                await self.db.execute(
                    stmt.order_by(ProductionRun.run_date.desc()).limit(limit)
                )
            ).scalars().all()
        )

    async def summary(self, start: date, end: date) -> dict[str, Any]:
        rows = await self.list_all(start=start, end=end, limit=1000)
        return {
            "runs": len(rows),
            "units_made": qty(sum((row.qty for row in rows), ZERO)),
            "material_cost": money(sum((row.material_cost for row in rows), ZERO)),
            "labour_cost": money(sum((row.labour_cost for row in rows), ZERO)),
            "wastage_cost": money(sum((row.wastage_cost for row in rows), ZERO)),
            "total_cost": money(sum((row.total_cost for row in rows), ZERO)),
        }
