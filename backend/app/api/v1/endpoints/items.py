"""Items, categories, units, stock."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, Tenant
from app.core.errors import NotFoundError
from app.core.pagination import PageParams, page_params
from app.core.permissions import Perm
from app.schemas.common import Message, Paginated
from app.schemas.item import (
    CategoryCreate, CategoryOut, ItemCreate, ItemListItem, ItemOut, ItemUpdate,
    StockAdjustment, StockLedgerOut, StockSummary, UnitCreate, UnitOut,
)
from app.services.item_service import CategoryService, ItemService, StockService, UnitService

router = APIRouter(prefix="/items", tags=["items"])


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
