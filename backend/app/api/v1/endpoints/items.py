"""Items, categories, units, stock."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, Tenant
from app.core.errors import NotFoundError
from app.core.pagination import PageParams, page_params
from app.core.permissions import Perm
from app.schemas.common import Message, Paginated
from app.schemas.item import (
    BatchAllocation, BatchCreate, BatchOut, BatchUpdate, CategoryCreate, CategoryOut, ExpiringBatch,
    GodownCreate, GodownOut, GodownStockRow, GodownUpdate, ItemCreate, ItemGodownRow,
    ItemListItem, ItemOut, ItemUpdate, SerialAdd, SerialAddResult, SerialLookupOut, SerialOut,
    StockAdjustment, StockLedgerOut, StockSummary, StockTransfer, TransferResult,
    UnitCreate, UnitOut,
)
from app.services.item_service import (
    BatchService, CategoryService, GodownService, ItemService, SerialService, StockService,
    UnitService,
)

router = APIRouter(prefix="/items", tags=["items"])


def _batch(batch) -> BatchOut:
    row = BatchOut.model_validate(batch)
    row.is_expired = batch.is_expired
    row.days_to_expiry = batch.days_to_expiry
    return row


def _serial(serial) -> SerialOut:
    row = SerialOut.model_validate(serial)
    row.in_warranty = serial.in_warranty
    return row


def _out(item) -> ItemOut:
    data = ItemOut.model_validate(item)
    data.is_low_stock = item.is_low_stock
    data.stock_value = item.stock_value
    data.margin_percent = item.margin_percent
    data.category_name = item.category.name if item.category else None
    return data


def _list_item(item) -> ItemListItem:
    row = ItemListItem.model_validate(item)
    row.is_low_stock = item.is_low_stock
    return row


@router.get("", response_model=Paginated[ItemListItem], summary="List items")
async def list_items(
    tenant: Tenant,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    search: str | None = Query(None, max_length=120),
    category_id: str | None = None,
    item_type: str | None = Query(None, pattern="^(product|service)$"),
    only_low_stock: bool = False,
    only_out_of_stock: bool = False,
    is_active: bool | None = None,
) -> Paginated[ItemListItem]:
    tenant.require(Perm.ITEM_READ)
    rows, total = await ItemService(db, tenant.actor).list(
        params,
        search=search,
        category_id=category_id,
        item_type=item_type,
        only_low_stock=only_low_stock,
        only_out_of_stock=only_out_of_stock,
        is_active=is_active,
    )
    return Paginated[ItemListItem](
        items=[_list_item(i) for i in rows], total=total, page=params.page, size=params.size,
        pages=max(1, -(-total // params.size)),
        has_next=params.page * params.size < total, has_prev=params.page > 1,
    )


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED, summary="Add an item")
async def create_item(payload: ItemCreate, tenant: Tenant, db: DbSession) -> ItemOut:
    tenant.require(Perm.ITEM_WRITE)
    return _out(await ItemService(db, tenant.actor).create(payload))


@router.get("/search", response_model=list[ItemListItem], summary="Fuzzy item search")
async def search_items(
    tenant: Tenant, db: DbSession, q: str = Query(min_length=1, max_length=120), limit: int = 10
) -> list[ItemListItem]:
    tenant.require(Perm.ITEM_READ)
    matches = await ItemService(db, tenant.actor).search_by_name(q, limit=limit)
    return [_list_item(i) for i, _score in matches]


@router.get("/barcode/{barcode}", response_model=ItemOut, summary="Look up by barcode")
async def by_barcode(barcode: str, tenant: Tenant, db: DbSession) -> ItemOut:
    tenant.require(Perm.ITEM_READ)
    item = await ItemService(db, tenant.actor).find_by_barcode(barcode)
    if item is None:
        raise NotFoundError("No item with that barcode.", details={"barcode": barcode})
    return _out(item)


@router.get("/stock/summary", response_model=StockSummary, summary="Stock position")
async def stock_summary(tenant: Tenant, db: DbSession) -> StockSummary:
    tenant.require(Perm.ITEM_READ)
    data = await ItemService(db, tenant.actor).stock_summary()
    return StockSummary(
        total_items=data["total_items"],
        total_stock_value=data["total_stock_value"],
        low_stock_count=data["low_stock_count"],
        out_of_stock_count=data["out_of_stock_count"],
        expiring_soon_count=data["expiring_soon_count"],
        top_value_items=[_list_item(i) for i in data["top_value_items"]],
    )


@router.post("/stock/adjust", response_model=ItemOut, summary="Adjust stock manually")
async def adjust_stock(payload: StockAdjustment, tenant: Tenant, db: DbSession) -> ItemOut:
    tenant.require(Perm.STOCK_ADJUST)
    item = await StockService(db, tenant.actor).adjust(
        payload.item_id,
        qty_delta=payload.qty,
        movement=payload.movement,
        rate=payload.rate,
        reason=payload.reason,
        batch_id=payload.batch_id,
        godown_id=payload.godown_id,
        entry_date=payload.entry_date,
    )
    return _out(item)


@router.get("/categories", response_model=list[CategoryOut], summary="Item categories")
async def list_categories(tenant: Tenant, db: DbSession) -> list[CategoryOut]:
    tenant.require(Perm.ITEM_READ)
    rows = await CategoryService(db, tenant.actor).list_with_counts()
    out = []
    for row in rows:
        item = CategoryOut.model_validate(row["category"])
        item.item_count = row["item_count"]
        out.append(item)
    return out


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED,
             summary="Create a category")
async def create_category(payload: CategoryCreate, tenant: Tenant, db: DbSession) -> CategoryOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await CategoryService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return CategoryOut.model_validate(row)


@router.get("/units", response_model=list[UnitOut], summary="Measurement units")
async def list_units(tenant: Tenant, db: DbSession) -> list[UnitOut]:
    tenant.require(Perm.ITEM_READ)
    return [UnitOut.model_validate(u) for u in await UnitService(db, tenant.actor).list_all()]


@router.post("/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED,
             summary="Create a unit")
async def create_unit(payload: UnitCreate, tenant: Tenant, db: DbSession) -> UnitOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await UnitService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return UnitOut.model_validate(row)


# ── locations ──────────────────────────────────────────────────────
@router.get("/godowns", response_model=list[GodownOut], summary="Stock locations")
async def list_godowns(tenant: Tenant, db: DbSession) -> list[GodownOut]:
    tenant.require(Perm.ITEM_READ)
    out = []
    for row in await GodownService(db, tenant.actor).list_with_stock():
        entry = GodownOut.model_validate(row["godown"])
        entry.item_count = row["item_count"]
        entry.stock_value = row["stock_value"]
        out.append(entry)
    return out


@router.post("/godowns", response_model=GodownOut, status_code=status.HTTP_201_CREATED,
             summary="Add a stock location")
async def create_godown(payload: GodownCreate, tenant: Tenant, db: DbSession) -> GodownOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await GodownService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return GodownOut.model_validate(row)


@router.patch("/godowns/{godown_id}", response_model=GodownOut, summary="Update a location")
async def update_godown(
    godown_id: str, payload: GodownUpdate, tenant: Tenant, db: DbSession
) -> GodownOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await GodownService(db, tenant.actor).update(
        godown_id, payload.model_dump(exclude_unset=True)
    )
    return GodownOut.model_validate(row)


@router.delete("/godowns/{godown_id}", response_model=Message, summary="Delete a location")
async def delete_godown(godown_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.ITEM_DELETE)
    await GodownService(db, tenant.actor).delete(godown_id)
    return Message(message="Location deleted.")


@router.get("/godowns/{godown_id}/stock", response_model=list[GodownStockRow],
            summary="What one location holds")
async def godown_stock(
    godown_id: str, tenant: Tenant, db: DbSession, limit: int = Query(200, ge=1, le=1000)
) -> list[GodownStockRow]:
    tenant.require(Perm.ITEM_READ)
    rows = await GodownService(db, tenant.actor).stock_at(godown_id, limit=limit)
    return [
        GodownStockRow(
            item_id=item.id, item_name=item.name, sku=item.sku, unit_label=item.unit_label,
            qty=held, value=(item.avg_cost or item.purchase_price) * held,
        )
        for item, held in rows
    ]


@router.post("/stock/transfer", response_model=TransferResult, summary="Move stock between locations")
async def transfer_stock(payload: StockTransfer, tenant: Tenant, db: DbSession) -> TransferResult:
    tenant.require(Perm.STOCK_ADJUST)
    item, from_after, to_after = await StockService(db, tenant.actor).transfer(
        payload.item_id,
        from_godown_id=payload.from_godown_id,
        to_godown_id=payload.to_godown_id,
        move_qty=payload.qty,
        batch_id=payload.batch_id,
        note=payload.note,
        entry_date=payload.entry_date,
    )
    return TransferResult(
        item_id=item.id, item_name=item.name, qty=payload.qty,
        from_godown_id=payload.from_godown_id, from_qty_after=from_after,
        to_godown_id=payload.to_godown_id, to_qty_after=to_after,
    )


# ── batches ────────────────────────────────────────────────────────
@router.post("/batches", response_model=BatchOut, status_code=status.HTTP_201_CREATED,
             summary="Add a batch")
async def create_batch(payload: BatchCreate, tenant: Tenant, db: DbSession) -> BatchOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await BatchService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return _batch(row)


@router.get("/batches/expiring", response_model=list[ExpiringBatch], summary="Expiring or expired stock")
async def expiring_batches(
    tenant: Tenant,
    db: DbSession,
    within_days: int = Query(30, ge=0, le=730),
    include_expired: bool = True,
) -> list[ExpiringBatch]:
    tenant.require(Perm.ITEM_READ)
    rows = await BatchService(db, tenant.actor).expiring(
        within_days=within_days, include_expired=include_expired
    )
    return [
        ExpiringBatch(
            batch=_batch(row["batch"]),
            item_id=row["item"].id,
            item_name=row["item"].name,
            unit_label=row["item"].unit_label,
            value=row["value"],
            days_to_expiry=row["batch"].days_to_expiry,
        )
        for row in rows
    ]


@router.patch("/batches/{batch_id}", response_model=BatchOut, summary="Update a batch")
async def update_batch(
    batch_id: str, payload: BatchUpdate, tenant: Tenant, db: DbSession
) -> BatchOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await BatchService(db, tenant.actor).update(
        batch_id, payload.model_dump(exclude_unset=True)
    )
    return _batch(row)


@router.delete("/batches/{batch_id}", response_model=Message, summary="Delete a batch")
async def delete_batch(batch_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.ITEM_DELETE)
    await BatchService(db, tenant.actor).delete(batch_id)
    return Message(message="Batch deleted.")


# ── serial numbers ─────────────────────────────────────────────────
@router.post("/serials", response_model=SerialAddResult, status_code=status.HTTP_201_CREATED,
             summary="Register serial numbers")
async def add_serials(payload: SerialAdd, tenant: Tenant, db: DbSession) -> SerialAddResult:
    tenant.require(Perm.ITEM_WRITE)
    service = SerialService(db, tenant.actor)
    added, duplicates = await service.add_many(
        payload.item_id,
        payload.serials,
        godown_id=payload.godown_id,
        batch_id=payload.batch_id,
        purchase_price=payload.purchase_price,
        warranty_months=payload.warranty_months,
        purchase_voucher_id=payload.purchase_voucher_id,
        received_on=payload.received_on,
    )
    return SerialAddResult(
        added=[_serial(s) for s in added],
        duplicates=duplicates,
        added_count=len(added),
        available_count=await service.available_count(payload.item_id),
    )


@router.get("/serials/lookup/{serial_number}", response_model=SerialLookupOut,
            summary="Find one unit by its serial")
async def lookup_serial(serial_number: str, tenant: Tenant, db: DbSession) -> SerialLookupOut:
    tenant.require(Perm.ITEM_READ)
    found = await SerialService(db, tenant.actor).lookup(serial_number)
    if found is None:
        raise NotFoundError("No unit with that serial number.", details={"serial": serial_number})
    serial, item = found
    return SerialLookupOut(
        serial=_serial(serial), item_id=item.id, item_name=item.name, sku=item.sku
    )


@router.get("/{item_id}/serials", response_model=list[SerialOut], summary="Units of one item")
async def item_serials(
    item_id: str,
    tenant: Tenant,
    db: DbSession,
    serial_status: str | None = Query(None, pattern="^(in_stock|sold|returned|damaged)$"),
    limit: int = Query(200, ge=1, le=500),
) -> list[SerialOut]:
    tenant.require(Perm.ITEM_READ)
    rows = await SerialService(db, tenant.actor).for_item(item_id, status=serial_status, limit=limit)
    return [_serial(s) for s in rows]


@router.get("/{item_id}/batches", response_model=list[BatchOut], summary="Batches of one item")
async def item_batches(
    item_id: str, tenant: Tenant, db: DbSession, in_stock_only: bool = False
) -> list[BatchOut]:
    tenant.require(Perm.ITEM_READ)
    rows = await BatchService(db, tenant.actor).for_item(item_id, in_stock_only=in_stock_only)
    return [_batch(b) for b in rows]


@router.get("/{item_id}/batches/allocate", response_model=list[BatchAllocation],
            summary="Which batches to sell from")
async def allocate_batches(
    item_id: str,
    tenant: Tenant,
    db: DbSession,
    qty: Decimal = Query(gt=0, description="How much is being sold"),
) -> list[BatchAllocation]:
    """First-expiry-first-out. Expired batches are never offered."""
    tenant.require(Perm.ITEM_READ)
    picked = await BatchService(db, tenant.actor).allocate(item_id, qty)
    return [
        BatchAllocation(
            batch_id=batch.id,
            batch_number=batch.batch_number,
            expiry_date=batch.expiry_date,
            qty=take,
            available=batch.qty,
        )
        for batch, take in picked
    ]


@router.get("/{item_id}/godowns", response_model=list[ItemGodownRow],
            summary="Where one item's stock sits")
async def item_by_godown(item_id: str, tenant: Tenant, db: DbSession) -> list[ItemGodownRow]:
    tenant.require(Perm.ITEM_READ)
    rows = await StockService(db, tenant.actor).by_godown(item_id)
    return [
        ItemGodownRow(
            godown_id=g.id, godown_name=g.name, is_default=g.is_default, qty=held
        )
        for g, held in rows
    ]


@router.get("/{item_id}", response_model=ItemOut, summary="Get one item")
async def get_item(item_id: str, tenant: Tenant, db: DbSession) -> ItemOut:
    tenant.require(Perm.ITEM_READ)
    return _out(await ItemService(db, tenant.actor).get_or_404(item_id))


@router.patch("/{item_id}", response_model=ItemOut, summary="Update an item")
async def update_item(
    item_id: str, payload: ItemUpdate, tenant: Tenant, db: DbSession
) -> ItemOut:
    tenant.require(Perm.ITEM_WRITE)
    return _out(await ItemService(db, tenant.actor).update(item_id, payload))


@router.delete("/{item_id}", response_model=Message, summary="Delete an item")
async def delete_item(item_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.ITEM_DELETE)
    await ItemService(db, tenant.actor).delete(item_id)
    return Message(message="Item deleted.")


@router.get("/{item_id}/ledger", response_model=list[StockLedgerOut], summary="Stock movements")
async def stock_ledger(
    item_id: str,
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[StockLedgerOut]:
    tenant.require(Perm.ITEM_READ)
    rows = await StockService(db, tenant.actor).ledger(
        item_id, start=start_date, end=end_date, limit=limit
    )
    return [StockLedgerOut.model_validate(r) for r in rows]
