"""Price lists, discount schemes, and what a line should cost."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, status

from app.api.deps import DbSession, Tenant
from app.core.pricing import applies_on
from app.core.permissions import Perm
from app.schemas.common import Message
from app.schemas.pricing import (
    PriceEntryIn, PriceEntryOut, PriceListCreate, PriceListOut, PriceListUpdate,
    QuoteLineOut, QuoteRequest, SchemeCreate, SchemeOut, SchemeUpdate,
)
from app.services.pricing_service import (
    DiscountSchemeService, PriceListService, QuoteService,
)

router = APIRouter(prefix="/pricing", tags=["pricing"])


def _scheme(row) -> SchemeOut:
    out = SchemeOut.model_validate(row)
    out.is_running = applies_on(row.starts_on, row.ends_on, date.today(), row.is_active)
    return out


# ── price lists ────────────────────────────────────────────────────
@router.get("/lists", response_model=list[PriceListOut], summary="Price lists")
async def list_price_lists(tenant: Tenant, db: DbSession) -> list[PriceListOut]:
    tenant.require(Perm.ITEM_READ)
    out = []
    for row, count in await PriceListService(db, tenant.actor).list_all():
        entry = PriceListOut.model_validate(row)
        entry.item_count = count
        out.append(entry)
    return out


@router.post("/lists", response_model=PriceListOut, status_code=status.HTTP_201_CREATED,
             summary="Add a price list")
async def create_price_list(
    payload: PriceListCreate, tenant: Tenant, db: DbSession
) -> PriceListOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await PriceListService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return PriceListOut.model_validate(row)


@router.patch("/lists/{list_id}", response_model=PriceListOut, summary="Update a price list")
async def update_price_list(
    list_id: str, payload: PriceListUpdate, tenant: Tenant, db: DbSession
) -> PriceListOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await PriceListService(db, tenant.actor).update(
        list_id, payload.model_dump(exclude_unset=True)
    )
    return PriceListOut.model_validate(row)


@router.delete("/lists/{list_id}", response_model=Message, summary="Delete a price list")
async def delete_price_list(list_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.ITEM_DELETE)
    await PriceListService(db, tenant.actor).delete(list_id)
    return Message(message="Price list deleted.")


@router.get("/lists/{list_id}/items", response_model=list[PriceEntryOut],
            summary="Rates named on a list")
async def list_entries(list_id: str, tenant: Tenant, db: DbSession) -> list[PriceEntryOut]:
    tenant.require(Perm.ITEM_READ)
    rows = await PriceListService(db, tenant.actor).entries(list_id)
    return [
        PriceEntryOut(
            id=entry.id, item_id=item.id, item_name=item.name, sku=item.sku,
            unit_label=item.unit_label, sale_price=item.sale_price,
            price=entry.price, min_qty=entry.min_qty,
        )
        for entry, item in rows
    ]


@router.put("/lists/{list_id}/items", response_model=Message, summary="Name a rate")
async def set_entry(
    list_id: str, payload: PriceEntryIn, tenant: Tenant, db: DbSession
) -> Message:
    tenant.require(Perm.ITEM_WRITE)
    await PriceListService(db, tenant.actor).set_entry(
        list_id, payload.item_id, payload.price, payload.min_qty
    )
    return Message(message="Rate saved.")


@router.delete("/lists/{list_id}/items/{item_id}", response_model=Message,
               summary="Take an item off a list")
async def remove_entry(
    list_id: str, item_id: str, tenant: Tenant, db: DbSession
) -> Message:
    tenant.require(Perm.ITEM_WRITE)
    await PriceListService(db, tenant.actor).remove_entry(list_id, item_id)
    return Message(message="Removed. This item now follows the list's own rule.")


# ── discount schemes ───────────────────────────────────────────────
@router.get("/schemes", response_model=list[SchemeOut], summary="Discount offers")
async def list_schemes(
    tenant: Tenant, db: DbSession, only_running: bool = False
) -> list[SchemeOut]:
    tenant.require(Perm.ITEM_READ)
    rows = await DiscountSchemeService(db, tenant.actor).list_all(only_running=only_running)
    return [_scheme(row) for row in rows]


@router.post("/schemes", response_model=SchemeOut, status_code=status.HTTP_201_CREATED,
             summary="Create an offer")
async def create_scheme(payload: SchemeCreate, tenant: Tenant, db: DbSession) -> SchemeOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await DiscountSchemeService(db, tenant.actor).create(
        payload.model_dump(exclude_unset=True)
    )
    return _scheme(row)


@router.patch("/schemes/{scheme_id}", response_model=SchemeOut, summary="Update an offer")
async def update_scheme(
    scheme_id: str, payload: SchemeUpdate, tenant: Tenant, db: DbSession
) -> SchemeOut:
    tenant.require(Perm.ITEM_WRITE)
    row = await DiscountSchemeService(db, tenant.actor).update(
        scheme_id, payload.model_dump(exclude_unset=True)
    )
    return _scheme(row)


@router.delete("/schemes/{scheme_id}", response_model=Message, summary="Delete an offer")
async def delete_scheme(scheme_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.ITEM_DELETE)
    await DiscountSchemeService(db, tenant.actor).delete(scheme_id)
    return Message(message="Offer deleted.")


# ── quoting ────────────────────────────────────────────────────────
@router.post("/quote", response_model=list[QuoteLineOut], summary="What these lines cost")
async def quote(payload: QuoteRequest, tenant: Tenant, db: DbSession) -> list[QuoteLineOut]:
    """The rate to show before the shopkeeper agrees to it.

    Called as lines are added rather than on save: the bill must charge what was
    on the screen when the number was read out to the customer, so the server
    never quietly reprices a voucher it is given.
    """
    tenant.require(Perm.ITEM_READ)
    rows = await QuoteService(db, tenant.actor).quote(
        [line.item_id for line in payload.lines],
        party_id=payload.party_id,
        qty_by_item={line.item_id: line.qty for line in payload.lines},
        on_date=payload.on_date,
    )
    return [QuoteLineOut(**row) for row in rows]
