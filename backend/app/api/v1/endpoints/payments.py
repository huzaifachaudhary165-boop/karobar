"""Payments, settlements, cash/bank accounts."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, Tenant
from app.core.pagination import PageParams, page_params
from app.core.permissions import Perm
from app.schemas.common import Message, Paginated
from app.schemas.payment import (
    AccountCreate, AccountOut, PaymentCreate, PaymentListItem, PaymentOut, PaymentUpdate,
    SettleRequest, SettleResult,
)
from app.services.payment_service import AccountService, PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("", response_model=Paginated[PaymentListItem], summary="List payments")
async def list_payments(
    tenant: Tenant,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    direction: str | None = Query(None, pattern="^(in|out)$"),
    party_id: str | None = None,
    mode: str | None = None,
    account_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = Query(None, max_length=120),
) -> Paginated[PaymentListItem]:
    tenant.require(Perm.PAYMENT_READ)
    rows, total = await PaymentService(db, tenant.actor).list(
        params,
        direction=direction,
        party_id=party_id,
        mode=mode,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        search=search,
    )
    return Paginated[PaymentListItem](
        items=[PaymentListItem.model_validate(p) for p in rows],
        total=total, page=params.page, size=params.size,
        pages=max(1, -(-total // params.size)),
        has_next=params.page * params.size < total, has_prev=params.page > 1,
    )


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED,
             summary="Record a payment")
async def create_payment(payload: PaymentCreate, tenant: Tenant, db: DbSession) -> PaymentOut:
    tenant.require(Perm.PAYMENT_WRITE)
    payment = await PaymentService(db, tenant.actor).create(payload)
    await db.refresh(payment)
    return PaymentOut.model_validate(payment)


@router.post("/settle", response_model=SettleResult,
             summary="Settle a party's dues, oldest invoice first")
async def settle(payload: SettleRequest, tenant: Tenant, db: DbSession) -> SettleResult:
    tenant.require(Perm.PAYMENT_WRITE)
    result = await PaymentService(db, tenant.actor).settle_party(
        payload.party_id,
        payload.amount,
        direction=str(payload.direction),
        mode=str(payload.mode),
        account_id=payload.account_id,
        payment_date=payload.payment_date,
        notes=payload.notes,
        discount_given=payload.discount_given,
    )
    return SettleResult(
        payment=PaymentOut.model_validate(result["payment"]),
        settled_vouchers=result["settled_vouchers"],
        remaining_credit=result["remaining_credit"],
        party_balance_after=result["party_balance_after"],
    )


@router.get("/accounts", response_model=list[AccountOut], summary="Cash and bank accounts")
async def list_accounts(tenant: Tenant, db: DbSession) -> list[AccountOut]:
    tenant.require(Perm.PAYMENT_READ)
    rows = await AccountService(db, tenant.actor).list_all()
    return [AccountOut.model_validate(a) for a in rows]


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED,
             summary="Add a cash or bank account")
async def create_account(payload: AccountCreate, tenant: Tenant, db: DbSession) -> AccountOut:
    tenant.require(Perm.SETTINGS_MANAGE)
    row = await AccountService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return AccountOut.model_validate(row)


@router.get("/{payment_id}", response_model=PaymentOut, summary="Get one payment")
async def get_payment(payment_id: str, tenant: Tenant, db: DbSession) -> PaymentOut:
    tenant.require(Perm.PAYMENT_READ)
    return PaymentOut.model_validate(await PaymentService(db, tenant.actor).get_or_404(payment_id))


@router.patch("/{payment_id}", response_model=PaymentOut, summary="Edit a payment")
async def update_payment(
    payment_id: str, payload: PaymentUpdate, tenant: Tenant, db: DbSession
) -> PaymentOut:
    tenant.require(Perm.PAYMENT_WRITE)
    payment = await PaymentService(db, tenant.actor).update(payment_id, payload)
    await db.refresh(payment)
    return PaymentOut.model_validate(payment)


@router.delete("/{payment_id}", response_model=Message, summary="Delete a payment")
async def delete_payment(payment_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.PAYMENT_WRITE)
    await PaymentService(db, tenant.actor).delete(payment_id)
    return Message(message="Payment deleted and invoice balances restored.")
