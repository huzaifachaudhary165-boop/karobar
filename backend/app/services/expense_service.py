"""Expenses, expense categories and tax-rate masters."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select

from app.core.errors import BusinessRuleError
from app.core.money import ZERO, inclusive_split, money, pct
from app.core.pagination import PageParams, paginate
from app.models.expense import Expense, ExpenseCategory, TaxRate
from app.models.payment import Account
from app.schemas.payment import ExpenseCreate, ExpenseUpdate
from app.services.base import BaseService, stamp_sync
from app.services.numbering_service import NumberingService
from app.utils.dates import month_bounds


class ExpenseService(BaseService[Expense]):
    model = Expense
    entity_name = "expense"

    async def create(self, payload: ExpenseCreate) -> Expense:
        if payload.client_uuid:
            existing = await self.get_by_client_uuid(payload.client_uuid)
            if existing:
                return existing

        amount = money(payload.amount)
        if amount <= 0:
            raise BusinessRuleError("Expense amount must be greater than zero.")

        exp_date = payload.expense_date or date.today()
        numbering = NumberingService(self.db, self.business_id)
        if payload.number:
            await numbering.reserve_explicit("expense", payload.number, exp_date)
            number = payload.number
        else:
            number, _ = await numbering.next_number("expense", on_date=exp_date)

        category_name = payload.category_name
        category_id = payload.category_id
        if category_id:
            cat = (
                await self.db.execute(
                    select(ExpenseCategory).where(
                        ExpenseCategory.id == category_id,
                        ExpenseCategory.business_id == self.business_id,
                    )
                )
            ).scalar_one_or_none()
            category_name = cat.name if cat else category_name
        elif category_name:
            cat = await self._resolve_category(category_name)
            category_id, category_name = cat.id, cat.name

        if payload.is_tax_inclusive:
            net, tax = inclusive_split(amount, payload.tax_rate)
        else:
            net, tax = amount, pct(amount, payload.tax_rate)

        expense = Expense(
            business_id=self.business_id,
            number=number,
            expense_date=exp_date,
            category_id=category_id,
            category_name=category_name,
            title=payload.title,
            description=payload.description,
            amount=net,
            tax_rate=money(payload.tax_rate),
            tax_amount=tax,
            total=money(net + tax),
            is_tax_inclusive=payload.is_tax_inclusive,
            input_tax_claimable=payload.input_tax_claimable,
            party_id=payload.party_id,
            vendor_name=payload.vendor_name,
            payment_mode=str(payload.payment_mode),
            account_id=payload.account_id,
            is_paid=payload.is_paid,
            reference_number=payload.reference_number,
            is_recurring=payload.is_recurring,
            recurrence=payload.recurrence,
            next_due_date=payload.next_due_date,
            receipt_url=payload.receipt_url,
            source=payload.source,
            created_by=self.actor.user_id,
        )
        stamp_sync(expense, self.actor, client_uuid=payload.client_uuid)
        self.db.add(expense)
        await self.db.flush()

        if expense.is_paid:
            await self._move_account(expense.account_id, -expense.total)

        await self.track("create", expense, label=expense.title)
        return expense

    async def update(self, expense_id: str, payload: ExpenseUpdate) -> Expense:
        expense = await self.get_or_404(expense_id)
        data = payload.model_dump(exclude_unset=True)

        old_total, old_paid, old_account = expense.total, expense.is_paid, expense.account_id

        if "amount" in data or "tax_rate" in data or "is_tax_inclusive" in data:
            amount = money(data.get("amount", expense.amount))
            rate = money(data.get("tax_rate", expense.tax_rate))
            inclusive = data.get("is_tax_inclusive", expense.is_tax_inclusive)
            if inclusive:
                net, tax = inclusive_split(amount, rate)
            else:
                net, tax = amount, pct(amount, rate)
            expense.amount, expense.tax_amount, expense.total = net, tax, money(net + tax)
            expense.tax_rate = rate
            expense.is_tax_inclusive = inclusive
            for k in ("amount", "tax_rate", "is_tax_inclusive"):
                data.pop(k, None)

        if data.get("category_id"):
            cat = (
                await self.db.execute(
                    select(ExpenseCategory).where(ExpenseCategory.id == data["category_id"])
                )
            ).scalar_one_or_none()
            if cat:
                expense.category_name = cat.name

        changes = self.apply_fields(expense, data)

        # keep the account balance consistent with any total/paid/account change
        if old_paid:
            await self._move_account(old_account, old_total)
        if expense.is_paid:
            await self._move_account(expense.account_id, -expense.total)

        expense.updated_by = self.actor.user_id
        expense.bump_revision()
        await self.track("update", expense, changes=changes, label=expense.title)
        return expense

    async def delete(self, expense_id: str) -> None:
        expense = await self.get_or_404(expense_id)
        if expense.is_paid:
            await self._move_account(expense.account_id, expense.total)
        await self.soft_delete(expense, label=expense.title)

    async def list(
        self,
        params: PageParams,
        *,
        category_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        search: str | None = None,
        payment_mode: str | None = None,
        only_unpaid: bool = False,
    ) -> tuple[list[Expense], int]:
        stmt = self.base_query()
        if category_id:
            stmt = stmt.where(Expense.category_id == category_id)
        if start_date:
            stmt = stmt.where(Expense.expense_date >= start_date)
        if end_date:
            stmt = stmt.where(Expense.expense_date <= end_date)
        if payment_mode:
            stmt = stmt.where(Expense.payment_mode == payment_mode)
        if only_unpaid:
            stmt = stmt.where(Expense.is_paid.is_(False))
        if search:
            like = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Expense.title).like(like),
                    func.lower(func.coalesce(Expense.description, "")).like(like),
                    func.lower(func.coalesce(Expense.vendor_name, "")).like(like),
                    func.lower(Expense.number).like(like),
                )
            )
        return await paginate(self.db, stmt, params, model=Expense, default_sort="expense_date")

    async def total_between(self, start: date, end: date, *, direct_only: bool | None = None) -> Decimal:
        stmt = select(func.coalesce(func.sum(Expense.total), 0)).where(
            Expense.business_id == self.business_id,
            Expense.is_deleted.is_(False),
            Expense.expense_date >= start,
            Expense.expense_date <= end,
        )
        if direct_only is not None:
            stmt = stmt.join(ExpenseCategory, Expense.category_id == ExpenseCategory.id, isouter=True).where(
                func.coalesce(ExpenseCategory.is_direct_cost, False).is_(direct_only)
            )
        return money((await self.db.execute(stmt)).scalar_one())

    async def breakdown(self, start: date, end: date, limit: int = 12) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    Expense.category_name,
                    func.sum(Expense.total),
                    func.count(),
                )
                .where(
                    Expense.business_id == self.business_id,
                    Expense.is_deleted.is_(False),
                    Expense.expense_date >= start,
                    Expense.expense_date <= end,
                )
                # Group on the raw column, not on coalesce(...): SQLAlchemy binds
                # the fallback string as a parameter, and Postgres then sees the
                # SELECT and GROUP BY expressions as different ones and rejects
                # the query. NULL is its own group here, so the label is applied
                # in Python below instead.
                .group_by(Expense.category_name)
                .order_by(func.sum(Expense.total).desc())
                .limit(limit)
            )
        ).all()
        return [
            {"category": name or "Uncategorised", "amount": money(total), "count": int(n)}
            for name, total, n in rows
        ]

    async def _resolve_category(self, name: str) -> ExpenseCategory:
        existing = (
            await self.db.execute(
                select(ExpenseCategory).where(
                    ExpenseCategory.business_id == self.business_id,
                    ExpenseCategory.is_deleted.is_(False),
                    func.lower(ExpenseCategory.name) == name.strip().lower(),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        created = ExpenseCategory(business_id=self.business_id, name=name.strip())
        self.db.add(created)
        await self.db.flush()
        return created

    async def _move_account(self, account_id: str | None, delta: Decimal) -> None:
        if not account_id:
            return
        account = (
            await self.db.execute(
                select(Account).where(Account.id == account_id, Account.business_id == self.business_id)
            )
        ).scalar_one_or_none()
        if account:
            account.balance = money(account.balance + delta)


class ExpenseCategoryService(BaseService[ExpenseCategory]):
    model = ExpenseCategory
    entity_name = "expense_category"

    async def create(self, data: dict[str, Any]) -> ExpenseCategory:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        row = ExpenseCategory(
            business_id=self.business_id,
            **{k: v for k, v in data.items() if hasattr(ExpenseCategory, k)},
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        self.db.add(row)
        await self.db.flush()
        await self.track("create", row, label=row.name)
        return row

    async def list_with_spend(self) -> list[dict[str, Any]]:
        start, end = month_bounds(date.today())
        rows = (
            await self.db.execute(
                select(
                    ExpenseCategory,
                    func.coalesce(func.sum(Expense.total), 0),
                    func.count(Expense.id),
                )
                .outerjoin(
                    Expense,
                    (Expense.category_id == ExpenseCategory.id)
                    & (Expense.is_deleted.is_(False))
                    & (Expense.expense_date >= start)
                    & (Expense.expense_date <= end),
                )
                .where(
                    ExpenseCategory.business_id == self.business_id,
                    ExpenseCategory.is_deleted.is_(False),
                )
                .group_by(ExpenseCategory.id)
                .order_by(ExpenseCategory.sort_order, ExpenseCategory.name)
            )
        ).all()
        return [
            {"category": cat, "spent_this_month": money(spent), "expense_count": int(n)}
            for cat, spent, n in rows
        ]


class TaxRateService(BaseService[TaxRate]):
    model = TaxRate
    entity_name = "tax_rate"

    async def create(self, data: dict[str, Any]) -> TaxRate:
        client_uuid = data.pop("client_uuid", None)
        data.pop("device_id", None)
        rate = money(data.get("rate", ZERO))
        half = rate / 2
        row = TaxRate(
            business_id=self.business_id,
            cgst_rate=money(data.get("cgst_rate") or half),
            sgst_rate=money(data.get("sgst_rate") or half),
            igst_rate=money(data.get("igst_rate") or rate),
            **{
                k: v for k, v in data.items()
                if hasattr(TaxRate, k) and k not in ("cgst_rate", "sgst_rate", "igst_rate")
            },
        )
        stamp_sync(row, self.actor, client_uuid=client_uuid)
        if row.is_default:
            for other in (await self.db.execute(self.base_query().where(TaxRate.is_default.is_(True)))).scalars():
                other.is_default = False
        self.db.add(row)
        await self.db.flush()
        await self.track("create", row, label=row.name)
        return row

    async def list_all(self) -> list[TaxRate]:
        return list(
            (
                await self.db.execute(
                    self.base_query().where(TaxRate.is_active.is_(True)).order_by(TaxRate.rate)
                )
            ).scalars().all()
        )
