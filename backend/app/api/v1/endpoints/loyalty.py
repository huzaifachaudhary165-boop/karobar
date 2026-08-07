"""Loyalty points."""

from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, Tenant
from app.core.errors import NotFoundError
from app.core.loyalty import scheme_cost_percent, value_of
from app.core.permissions import Perm
from app.schemas.common import Message
from app.schemas.loyalty import (
    AdjustRequest, BalanceOut, EntryOut, ExpiryRun, ProgramOut, ProgramUpdate,
    QuoteOut, QuoteRequest, RedeemRequest, TopCustomer,
)
from app.services.loyalty_service import LoyaltyService

router = APIRouter(prefix="/loyalty", tags=["loyalty"])


def _program(row) -> ProgramOut:
    out = ProgramOut.model_validate(row)
    out.cost_percent = scheme_cost_percent(row.earn_rate, row.point_value)
    out.summary = f"{out.cost_percent}% of every sale"
    return out


@router.get("/program", response_model=ProgramOut | None, summary="The points scheme")
async def get_program(tenant: Tenant, db: DbSession) -> ProgramOut | None:
    """Null when the shop has never set one up — not an error, just not on."""
    tenant.require(Perm.PARTY_READ)
    row = await LoyaltyService(db, tenant.actor).program()
    return _program(row) if row else None


@router.put("/program", response_model=ProgramOut, summary="Set up or change the scheme")
async def save_program(
    payload: ProgramUpdate, tenant: Tenant, db: DbSession
) -> ProgramOut:
    tenant.require(Perm.SETTINGS_MANAGE)
    row = await LoyaltyService(db, tenant.actor).save_program(
        payload.model_dump(exclude_unset=True)
    )
    return _program(row)


@router.get("/balance/{party_id}", response_model=BalanceOut, summary="A customer's points")
async def balance(party_id: str, tenant: Tenant, db: DbSession) -> BalanceOut:
    tenant.require(Perm.PARTY_READ)
    service = LoyaltyService(db, tenant.actor)
    program = await service.program()
    points = await service.balance(party_id)

    lots = [lot for lot in await service.lots_for(party_id) if lot.expires_on]
    lots.sort(key=lambda lot: lot.expires_on)
    return BalanceOut(
        party_id=party_id,
        balance=points,
        value=value_of(points, program.point_value) if program else 0,
        next_expiry=lots[0].expires_on if lots else None,
    )


@router.get("/history/{party_id}", response_model=list[EntryOut],
            summary="Where a customer's points came from and went")
async def history(
    party_id: str, tenant: Tenant, db: DbSession, limit: int = Query(50, ge=1, le=200)
) -> list[EntryOut]:
    """The list a customer is entitled to when they ask where their points went."""
    tenant.require(Perm.PARTY_READ)
    rows = await LoyaltyService(db, tenant.actor).history(party_id, limit=limit)
    return [EntryOut.model_validate(row) for row in rows]


@router.post("/quote", response_model=QuoteOut, summary="What can be used on this bill")
async def quote(payload: QuoteRequest, tenant: Tenant, db: DbSession) -> QuoteOut:
    tenant.require(Perm.SALE_READ)
    return QuoteOut(
        **await LoyaltyService(db, tenant.actor).quote(payload.party_id, payload.bill_total)
    )


@router.post("/redeem", response_model=EntryOut, status_code=status.HTTP_201_CREATED,
             summary="Use points against a bill")
async def redeem(payload: RedeemRequest, tenant: Tenant, db: DbSession) -> EntryOut:
    tenant.require(Perm.SALE_WRITE)
    row = await LoyaltyService(db, tenant.actor).redeem(
        payload.party_id,
        payload.points,
        bill_total=payload.bill_total,
        voucher_id=payload.voucher_id,
        voucher_number=payload.voucher_number,
    )
    return EntryOut.model_validate(row)


@router.post("/adjust", response_model=EntryOut, status_code=status.HTTP_201_CREATED,
             summary="Correct a customer's points by hand")
async def adjust(payload: AdjustRequest, tenant: Tenant, db: DbSession) -> EntryOut:
    """Always requires a reason: an unexplained adjustment is what a customer
    will point at when they dispute their balance."""
    tenant.require(Perm.SETTINGS_MANAGE)
    row = await LoyaltyService(db, tenant.actor).adjust(
        payload.party_id, payload.points, payload.note
    )
    return EntryOut.model_validate(row)


@router.post("/expire", response_model=ExpiryRun, summary="Write off points past their date")
async def expire(tenant: Tenant, db: DbSession) -> ExpiryRun:
    """Asked for by the app rather than swept at midnight — there is no
    scheduler behind this API, so nothing would do it otherwise."""
    tenant.require(Perm.SETTINGS_MANAGE)
    return ExpiryRun(**await LoyaltyService(db, tenant.actor).expire_stale())


@router.get("/top", response_model=list[TopCustomer], summary="Who holds the most points")
async def top(
    tenant: Tenant, db: DbSession, limit: int = Query(20, ge=1, le=100)
) -> list[TopCustomer]:
    tenant.require(Perm.PARTY_READ)
    service = LoyaltyService(db, tenant.actor)
    program = await service.program()
    return [
        TopCustomer(
            party_id=party.id,
            party_name=party.name,
            points=points,
            value=value_of(points, program.point_value) if program else 0,
        )
        for party, points in await service.top_customers(limit=limit)
    ]


@router.delete("/program", response_model=Message, summary="Stop the scheme")
async def stop_program(tenant: Tenant, db: DbSession) -> Message:
    """Switched off rather than deleted: points already given are a promise to
    a customer, and the history stays readable."""
    tenant.require(Perm.SETTINGS_MANAGE)
    service = LoyaltyService(db, tenant.actor)
    row = await service.program()
    if row is None:
        raise NotFoundError("There is no points scheme to stop.")
    await service.save_program({"is_active": False})
    return Message(message="Scheme paused. Points already given are untouched.")
