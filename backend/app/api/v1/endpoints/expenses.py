"""Expenses, expense categories and tax rates."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, Tenant
from app.core.pagination import PageParams, page_params
from app.core.permissions import Perm
from app.schemas.common import Message, Paginated
from app.schemas.payment import (
    ExpenseCategoryCreate, ExpenseCategoryOut, ExpenseCreate, ExpenseOut, ExpenseUpdate,
    TaxRateCreate, TaxRateOut,
)
from app.services.expense_service import (
    ExpenseCategoryService, ExpenseService, TaxRateService,
)

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.get("", response_model=Paginated[ExpenseOut], summary="List expenses")
async def list_expenses(
    tenant: Tenant,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    category_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    search: str | None = Query(None, max_length=120),
    payment_mode: str | None = None,
    only_unpaid: bool = False,
) -> Paginated[ExpenseOut]:
    tenant.require(Perm.EXPENSE_READ)
    rows, total = await ExpenseService(db, tenant.actor).list(
        params,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
        search=search,
        payment_mode=payment_mode,
        only_unpaid=only_unpaid,
    )
    return Paginated[ExpenseOut](
        items=[ExpenseOut.model_validate(e) for e in rows],
        total=total, page=params.page, size=params.size,
        pages=max(1, -(-total // params.size)),
        has_next=params.page * params.size < total, has_prev=params.page > 1,
    )


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED,
             summary="Record an expense")
async def create_expense(payload: ExpenseCreate, tenant: Tenant, db: DbSession) -> ExpenseOut:
    tenant.require(Perm.EXPENSE_WRITE)
    return ExpenseOut.model_validate(await ExpenseService(db, tenant.actor).create(payload))


@router.get("/breakdown", summary="Spend by category")
async def breakdown(
    tenant: Tenant, db: DbSession, start_date: date, end_date: date
) -> list[dict]:
    tenant.require(Perm.REPORT_READ)
    return await ExpenseService(db, tenant.actor).breakdown(start_date, end_date)


@router.get("/categories", response_model=list[ExpenseCategoryOut], summary="Expense categories")
async def list_categories(tenant: Tenant, db: DbSession) -> list[ExpenseCategoryOut]:
    tenant.require(Perm.EXPENSE_READ)
    rows = await ExpenseCategoryService(db, tenant.actor).list_with_spend()
    out = []
    for row in rows:
        item = ExpenseCategoryOut.model_validate(row["category"])
        item.spent_this_month = row["spent_this_month"]
        item.expense_count = row["expense_count"]
        out.append(item)
    return out


@router.post("/categories", response_model=ExpenseCategoryOut,
             status_code=status.HTTP_201_CREATED, summary="Create an expense category")
async def create_category(
    payload: ExpenseCategoryCreate, tenant: Tenant, db: DbSession
) -> ExpenseCategoryOut:
    tenant.require(Perm.EXPENSE_WRITE)
    row = await ExpenseCategoryService(db, tenant.actor).create(
        payload.model_dump(exclude_unset=True)
    )
    return ExpenseCategoryOut.model_validate(row)


@router.get("/tax-rates", response_model=list[TaxRateOut], summary="Tax rates")
async def list_tax_rates(tenant: Tenant, db: DbSession) -> list[TaxRateOut]:
    tenant.require(Perm.ITEM_READ)
    return [TaxRateOut.model_validate(t) for t in await TaxRateService(db, tenant.actor).list_all()]


@router.post("/tax-rates", response_model=TaxRateOut, status_code=status.HTTP_201_CREATED,
             summary="Create a tax rate")
async def create_tax_rate(
    payload: TaxRateCreate, tenant: Tenant, db: DbSession
) -> TaxRateOut:
    tenant.require(Perm.SETTINGS_MANAGE)
    row = await TaxRateService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return TaxRateOut.model_validate(row)


@router.get("/{expense_id}", response_model=ExpenseOut, summary="Get one expense")
async def get_expense(expense_id: str, tenant: Tenant, db: DbSession) -> ExpenseOut:
    tenant.require(Perm.EXPENSE_READ)
    return ExpenseOut.model_validate(await ExpenseService(db, tenant.actor).get_or_404(expense_id))


@router.patch("/{expense_id}", response_model=ExpenseOut, summary="Edit an expense")
async def update_expense(
    expense_id: str, payload: ExpenseUpdate, tenant: Tenant, db: DbSession
) -> ExpenseOut:
    tenant.require(Perm.EXPENSE_WRITE)
    return ExpenseOut.model_validate(
        await ExpenseService(db, tenant.actor).update(expense_id, payload)
    )


@router.delete("/{expense_id}", response_model=Message, summary="Delete an expense")
async def delete_expense(expense_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.EXPENSE_WRITE)
    await ExpenseService(db, tenant.actor).delete(expense_id)
    return Message(message="Expense deleted.")
