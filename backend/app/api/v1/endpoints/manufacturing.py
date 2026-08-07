"""Recipes and production runs."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import DbSession, Tenant
from app.core.permissions import Perm
from app.models.item import Item
from app.schemas.common import Message
from app.schemas.manufacturing import (
    BomCreate, BomOut, BomUpdate, ComponentOut, ConsumedOut, CostingOut,
    ProductionSummary, RunCreate, RunOut, ShortageOut,
)
from app.services.manufacturing_service import BomService, ProductionService

router = APIRouter(prefix="/manufacturing", tags=["manufacturing"])


def _shortage(row) -> ShortageOut:
    return ShortageOut(
        item_id=row.item_id,
        item_name=row.item_name,
        needed=row.needed,
        available=row.available,
        short_by=row.shortfall,
    )


async def _bom_out(bom, service: BomService, db) -> BomOut:
    out = BomOut.model_validate(bom)

    items = {
        item.id: item
        for item in (
            await db.execute(
                select(Item).where(
                    Item.id.in_([bom.item_id, *[c.item_id for c in bom.components]])
                )
            )
        ).scalars().all()
    }
    finished = items.get(bom.item_id)
    out.item_name = finished.name if finished else ""

    out.components = [
        ComponentOut(
            id=component.id,
            item_id=component.item_id,
            item_name=items[component.item_id].name if component.item_id in items else "",
            unit_label=(
                items[component.item_id].unit_label if component.item_id in items else "Pcs"
            ),
            qty=component.qty,
            rate=(
                items[component.item_id].avg_cost or items[component.item_id].purchase_price
                if component.item_id in items
                else Decimal("0")
            ),
            available=(
                items[component.item_id].stock_qty if component.item_id in items else None
            ),
            note=component.note,
        )
        for component in bom.components
    ]

    costing = await service.costing(bom.id)
    out.batch_cost = costing.total_cost
    out.unit_cost = costing.unit_cost
    out.can_make = await service.capacity(bom.id)
    return out


# ── recipes ────────────────────────────────────────────────────────
@router.get("/recipes", response_model=list[BomOut], summary="Recipes")
async def list_recipes(
    tenant: Tenant, db: DbSession, only_active: bool = False
) -> list[BomOut]:
    tenant.require(Perm.ITEM_READ)
    service = BomService(db, tenant.actor)
    rows = await service.list_all(only_active=only_active)
    return [await _bom_out(row, service, db) for row in rows]


@router.post("/recipes", response_model=BomOut, status_code=status.HTTP_201_CREATED,
             summary="Add a recipe")
async def create_recipe(payload: BomCreate, tenant: Tenant, db: DbSession) -> BomOut:
    tenant.require(Perm.ITEM_WRITE)
    service = BomService(db, tenant.actor)
    data = payload.model_dump(exclude_unset=True)
    data["components"] = [c.model_dump() for c in payload.components]
    bom = await service.create(data)
    return await _bom_out(bom, service, db)


@router.get("/recipes/{bom_id}", response_model=BomOut, summary="Get one recipe")
async def get_recipe(bom_id: str, tenant: Tenant, db: DbSession) -> BomOut:
    tenant.require(Perm.ITEM_READ)
    service = BomService(db, tenant.actor)
    return await _bom_out(await service.get_or_404(bom_id), service, db)


@router.patch("/recipes/{bom_id}", response_model=BomOut, summary="Update a recipe")
async def update_recipe(
    bom_id: str, payload: BomUpdate, tenant: Tenant, db: DbSession
) -> BomOut:
    tenant.require(Perm.ITEM_WRITE)
    service = BomService(db, tenant.actor)
    data = payload.model_dump(exclude_unset=True)
    if payload.components is not None:
        data["components"] = [c.model_dump() for c in payload.components]
    bom = await service.update(bom_id, data)
    return await _bom_out(bom, service, db)


@router.delete("/recipes/{bom_id}", response_model=Message, summary="Delete a recipe")
async def delete_recipe(bom_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.ITEM_DELETE)
    await BomService(db, tenant.actor).delete(bom_id)
    return Message(message="Recipe deleted.")


@router.get("/recipes/{bom_id}/costing", response_model=CostingOut,
            summary="What making this many would need and cost")
async def costing(
    bom_id: str,
    tenant: Tenant,
    db: DbSession,
    qty: Decimal = Query(gt=0, description="How many to make"),
) -> CostingOut:
    """Asked before committing, so a run that cannot finish is never started."""
    tenant.require(Perm.ITEM_READ)
    result = await BomService(db, tenant.actor).costing(bom_id, qty)
    return CostingOut(
        making=qty,
        material_cost=result.material_cost,
        labour_cost=result.labour_cost,
        overhead_cost=result.overhead_cost,
        wastage_cost=result.wastage_cost,
        total_cost=result.total_cost,
        unit_cost=result.unit_cost,
        requirements=[_shortage(row) for row in result.requirements],
        shortages=[_shortage(row) for row in result.shortages],
        can_make_now=not result.shortages,
    )


# ── runs ───────────────────────────────────────────────────────────
@router.get("/runs", response_model=list[RunOut], summary="What has been made")
async def list_runs(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> list[RunOut]:
    tenant.require(Perm.ITEM_READ)
    rows = await ProductionService(db, tenant.actor).list_all(
        start=start_date, end=end_date, limit=limit
    )
    return [RunOut.model_validate(row) for row in rows]


@router.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED,
             summary="Make it")
async def create_run(payload: RunCreate, tenant: Tenant, db: DbSession) -> RunOut:
    """Consumes the materials and produces the finished units in one go.

    The materials are checked before anything moves, so a run that cannot
    finish never leaves half the flour consumed and no biscuits to show.
    """
    tenant.require(Perm.STOCK_ADJUST)
    run = await ProductionService(db, tenant.actor).run(
        payload.model_dump(exclude_unset=True)
    )
    out = RunOut.model_validate(run)
    out.consumed = [ConsumedOut.model_validate(row) for row in run.consumed]
    return out


@router.delete("/runs/{run_id}", response_model=Message, summary="Undo a run")
async def delete_run(run_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.STOCK_ADJUST)
    await ProductionService(db, tenant.actor).delete(run_id)
    return Message(message="Run undone. The materials are back and the finished units gone.")


@router.get("/summary", response_model=ProductionSummary, summary="What was made and what it cost")
async def summary(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> ProductionSummary:
    tenant.require(Perm.REPORT_READ)
    end = end_date or date.today()
    start = start_date or (end - timedelta(days=30))
    return ProductionSummary(
        **await ProductionService(db, tenant.actor).summary(start, end)
    )
