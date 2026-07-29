"""Invoices, bills, quotations, returns — plus PDF and sharing."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Response, status

from app.api.deps import DbSession, Tenant
from app.core.pagination import PageParams, page_params
from app.core.permissions import Perm
from app.models.enums import VoucherType
from app.schemas.common import Message, Paginated
from app.schemas.voucher import (
    ConvertRequest, ShareRequest, ShareResponse, VoucherCreate, VoucherListItem, VoucherOut,
    VoucherUpdate,
)
from app.services.numbering_service import NumberingService
from app.services.pdf_service import PdfService
from app.services.voucher_service import VoucherService

router = APIRouter(prefix="/vouchers", tags=["invoices"])


def _out(voucher) -> VoucherOut:
    data = VoucherOut.model_validate(voucher)
    data.is_overdue = voucher.is_overdue
    data.days_overdue = voucher.days_overdue
    return data


def _row(voucher) -> VoucherListItem:
    item = VoucherListItem.model_validate(voucher)
    item.is_overdue = voucher.is_overdue
    item.item_count = len(voucher.lines)
    return item


def _write_permission(voucher_type: str) -> Perm:
    return (
        Perm.PURCHASE_WRITE
        if voucher_type in (VoucherType.PURCHASE, VoucherType.PURCHASE_RETURN,
                            VoucherType.PURCHASE_ORDER)
        else Perm.SALE_WRITE
    )


@router.get("", response_model=Paginated[VoucherListItem], summary="List documents")
async def list_vouchers(
    tenant: Tenant,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    voucher_type: str | None = None,
    voucher_status: str | None = Query(None, alias="status"),
    party_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = Query(None, max_length=120),
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    only_unpaid: bool = False,
    only_overdue: bool = False,
    source: str | None = None,
) -> Paginated[VoucherListItem]:
    tenant.require(Perm.SALE_READ)
    rows, total = await VoucherService(db, tenant.actor).list(
        params,
        voucher_type=voucher_type,
        status=voucher_status,
        party_id=party_id,
        start_date=start_date,
        end_date=end_date,
        search=search,
        min_amount=min_amount,
        max_amount=max_amount,
        only_unpaid=only_unpaid,
        only_overdue=only_overdue,
        source=source,
    )
    return Paginated[VoucherListItem](
        items=[_row(v) for v in rows], total=total, page=params.page, size=params.size,
        pages=max(1, -(-total // params.size)),
        has_next=params.page * params.size < total, has_prev=params.page > 1,
    )


@router.post("", response_model=VoucherOut, status_code=status.HTTP_201_CREATED,
             summary="Create an invoice / bill / quotation")
async def create_voucher(payload: VoucherCreate, tenant: Tenant, db: DbSession) -> VoucherOut:
    tenant.require(_write_permission(str(payload.voucher_type)))
    voucher = await VoucherService(db, tenant.actor).create(payload)
    await db.refresh(voucher)
    return _out(voucher)


@router.get("/next-number", summary="Preview the next document number")
async def next_number(
    tenant: Tenant,
    db: DbSession,
    voucher_type: str = Query(VoucherType.SALE),
    on_date: date | None = None,
) -> dict[str, str]:
    tenant.require(Perm.SALE_READ)
    number = await NumberingService(db, tenant.business.id).peek_number(voucher_type, on_date)
    return {"voucher_type": voucher_type, "next_number": number}


@router.get("/{voucher_id}", response_model=VoucherOut, summary="Get one document")
async def get_voucher(voucher_id: str, tenant: Tenant, db: DbSession) -> VoucherOut:
    tenant.require(Perm.SALE_READ)
    return _out(await VoucherService(db, tenant.actor).get_or_404(voucher_id))


@router.patch("/{voucher_id}", response_model=VoucherOut, summary="Edit a document")
async def update_voucher(
    voucher_id: str, payload: VoucherUpdate, tenant: Tenant, db: DbSession
) -> VoucherOut:
    service = VoucherService(db, tenant.actor)
    existing = await service.get_or_404(voucher_id)
    tenant.require(_write_permission(existing.voucher_type))
    voucher = await service.update(voucher_id, payload)
    await db.refresh(voucher)
    return _out(voucher)


@router.delete("/{voucher_id}", response_model=Message, summary="Delete a document")
async def delete_voucher(voucher_id: str, tenant: Tenant, db: DbSession) -> Message:
    service = VoucherService(db, tenant.actor)
    existing = await service.get_or_404(voucher_id)
    tenant.require(
        Perm.PURCHASE_DELETE if existing.type_enum.party_kind == "supplier" else Perm.SALE_DELETE
    )
    await service.delete(voucher_id)
    return Message(message="Document deleted.")


@router.post("/{voucher_id}/cancel", response_model=VoucherOut, summary="Cancel a document")
async def cancel_voucher(
    voucher_id: str,
    tenant: Tenant,
    db: DbSession,
    reason: Annotated[str | None, Body(embed=True)] = None,
) -> VoucherOut:
    service = VoucherService(db, tenant.actor)
    existing = await service.get_or_404(voucher_id)
    tenant.require(_write_permission(existing.voucher_type))
    return _out(await service.cancel(voucher_id, reason))


@router.post("/{voucher_id}/convert", response_model=VoucherOut,
             summary="Convert a quotation or order into an invoice")
async def convert_voucher(
    voucher_id: str, payload: ConvertRequest, tenant: Tenant, db: DbSession
) -> VoucherOut:
    tenant.require(_write_permission(str(payload.target_type)))
    voucher = await VoucherService(db, tenant.actor).convert(
        voucher_id, payload.target_type, voucher_date=payload.voucher_date
    )
    await db.refresh(voucher)
    return _out(voucher)


@router.post("/{voucher_id}/return", response_model=VoucherOut,
             summary="Create a return against this document")
async def create_return(
    voucher_id: str,
    tenant: Tenant,
    db: DbSession,
    lines: Annotated[list[dict[str, Any]] | None, Body(embed=True)] = None,
    return_date: Annotated[date | None, Body(embed=True)] = None,
    reason: Annotated[str | None, Body(embed=True)] = None,
) -> VoucherOut:
    tenant.require(Perm.SALE_WRITE)
    voucher = await VoucherService(db, tenant.actor).create_return(
        voucher_id, lines=lines, return_date=return_date, reason=reason
    )
    await db.refresh(voucher)
    return _out(voucher)


@router.get("/{voucher_id}/html", response_class=Response, summary="Print-ready HTML")
async def voucher_html(voucher_id: str, tenant: Tenant, db: DbSession) -> Response:
    tenant.require(Perm.SALE_READ)
    html = await PdfService(db, tenant.actor).render_html(voucher_id)
    return Response(content=html, media_type="text/html")


@router.get("/{voucher_id}/pdf", response_class=Response, summary="PDF (falls back to HTML)")
async def voucher_pdf(voucher_id: str, tenant: Tenant, db: DbSession) -> Response:
    tenant.require(Perm.SALE_READ)
    service = PdfService(db, tenant.actor)
    pdf = await service.render_pdf(voucher_id)
    if pdf is not None:
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{voucher_id}.pdf"'},
        )
    # No PDF engine on this host — the client renders the HTML locally.
    html = await service.render_html(voucher_id)
    return Response(content=html, media_type="text/html", headers={"X-Pdf-Fallback": "html"})


@router.post("/{voucher_id}/share", response_model=ShareResponse, summary="Share via WhatsApp/email")
async def share_voucher(
    voucher_id: str, payload: ShareRequest, tenant: Tenant, db: DbSession
) -> ShareResponse:
    tenant.require(Perm.SALE_READ)
    from app.services.share_service import ShareService  # noqa: PLC0415

    result = await ShareService(db, tenant.actor).share_voucher(voucher_id, payload)
    return ShareResponse.model_validate(result)
