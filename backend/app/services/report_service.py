"""Dashboard, P&L, balance sheet, sales/tax/daybook and cash-flow reports."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import ZERO, D, growth_pct, money, safe_div
from app.models.business import Business
from app.models.enums import PaymentDirection, VoucherStatus, VoucherType
from app.models.expense import Expense, ExpenseCategory
from app.models.item import Item
from app.models.party import Party
from app.models.payment import Account, Payment
from app.models.voucher import Voucher, VoucherLine
from app.services.base import ActorContext
from app.utils.dates import (
    auto_granularity, iter_buckets, month_bounds, previous_period, resolve_period,
)

_POSTED = [VoucherStatus.CANCELLED, VoucherStatus.DRAFT]


class ReportService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    # ── dashboard ────────────────────────────────────────────────
    async def dashboard(self, period: str = "this_month", *, compare: bool = True) -> dict[str, Any]:
        biz = await self._business()
        start, end = resolve_period(period, fy_start_month=biz.financial_year_start_month)
        prev_start, prev_end = previous_period(start, end)

        # This screen is opened more than any other, so its aggregates are
        # batched: one query per table covering both this period and the one
        # before it, instead of ten separate round trips. Over a link to a
        # database in another country, round trips are the entire cost.
        periods = [(start, end)] + ([(prev_start, prev_end)] if compare else [])
        voucher_totals = await self._voucher_totals(periods)
        payment_totals = await self._payment_totals(periods)
        expense_totals = await self._expense_totals(periods)

        sales = voucher_totals[0]["sale"]
        purchases = voucher_totals[0]["purchase"]
        gross_profit = voucher_totals[0]["profit"]
        expenses = expense_totals[0]
        collections = payment_totals[0]
        net_profit = money(gross_profit - expenses)

        if compare:
            prev_sales = voucher_totals[1]["sale"]
            prev_purchases = voucher_totals[1]["purchase"]
            prev_expenses = expense_totals[1]
            prev_profit = money(voucher_totals[1]["profit"] - prev_expenses)
            prev_collections = payment_totals[1]
        else:
            prev_sales = prev_purchases = prev_expenses = prev_profit = prev_collections = None

        receivable, payable = await self.receivable_payable()
        cash, bank = await self._account_balances()
        stock_value = await self._stock_value()
        counts = await self._invoice_counts(start, end)

        granularity = auto_granularity(start, end)
        series = await self.sales_series(start, end, granularity)

        return {
            "period_label": period,
            "start_date": start,
            "end_date": end,
            "currency_symbol": biz.currency_symbol,
            "sales": _trend(sales, prev_sales),
            "purchases": _trend(purchases, prev_purchases),
            "expenses": _trend(expenses, prev_expenses),
            "profit": _trend(net_profit, prev_profit),
            "collections": _trend(collections, prev_collections),
            "receivable": receivable,
            "payable": payable,
            "cash_in_hand": cash,
            "bank_balance": bank,
            "stock_value": stock_value,
            **counts,
            "new_party_count": await self._new_parties(start, end),
            "low_stock_count": await self._low_stock_count(),
            "sales_series": series,
            "top_items": await self.top_items(start, end, limit=5),
            "top_parties": await self.top_parties(start, end, limit=5),
            "recent_activity": await self.recent_activity(limit=10),
            "alerts": await self.alerts(),
        }

    async def sales_series(self, start: date, end: date, granularity: str) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Voucher.voucher_date, Voucher.voucher_type, Voucher.total, Voucher.profit).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type.in_([VoucherType.SALE, VoucherType.PURCHASE]),
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).all()

        sales: dict[str, Decimal] = {}
        purchases: dict[str, Decimal] = {}
        for vdate, vtype, total, _profit in rows:
            from app.utils.dates import bucket_label

            key = bucket_label(vdate, granularity)
            target = sales if vtype == VoucherType.SALE else purchases
            target[key] = money(target.get(key, ZERO) + D(total))

        return [
            {"label": label, "value": sales.get(label, ZERO), "secondary": purchases.get(label, ZERO)}
            for label, _s, _e in iter_buckets(start, end, granularity)
        ]

    async def top_items(self, start: date, end: date, limit: int = 10) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    VoucherLine.item_id,
                    VoucherLine.item_name,
                    func.sum(VoucherLine.qty),
                    func.sum(VoucherLine.total),
                    func.sum(VoucherLine.line_profit),
                    func.count(),
                )
                .join(Voucher, VoucherLine.voucher_id == Voucher.id)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .group_by(VoucherLine.item_id, VoucherLine.item_name)
                .order_by(func.sum(VoucherLine.total).desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "item_id": iid, "name": name, "quantity": D(q),
                "revenue": money(rev), "profit": money(profit), "sale_count": int(n),
            }
            for iid, name, q, rev, profit, n in rows
        ]

    async def top_parties(self, start: date, end: date, limit: int = 10) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    Voucher.party_id, Voucher.party_name,
                    func.sum(Voucher.total), func.count(), func.sum(Voucher.balance_amount),
                )
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .group_by(Voucher.party_id, Voucher.party_name)
                .order_by(func.sum(Voucher.total).desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "party_id": pid, "name": name or "Walk-in", "total": money(total),
                "invoice_count": int(n), "outstanding": money(due),
            }
            for pid, name, total, n, due in rows
        ]

    async def recent_activity(self, limit: int = 10) -> list[dict[str, Any]]:
        vouchers = (
            await self.db.execute(
                select(Voucher)
                .where(Voucher.business_id == self.business_id, Voucher.is_deleted.is_(False))
                .order_by(Voucher.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        payments = (
            await self.db.execute(
                select(Payment)
                .where(Payment.business_id == self.business_id, Payment.is_deleted.is_(False))
                .order_by(Payment.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()

        items = [
            {
                "type": v.voucher_type, "id": v.id, "number": v.number,
                "party": v.party_name, "amount": money(v.total),
                "date": v.voucher_date, "at": v.created_at, "status": v.status, "source": v.source,
            }
            for v in vouchers
        ] + [
            {
                "type": f"payment_{p.direction}", "id": p.id, "number": p.number,
                "party": p.party_name, "amount": money(p.amount),
                "date": p.payment_date, "at": p.created_at, "status": "done", "source": p.source,
            }
            for p in payments
        ]
        items.sort(key=lambda x: x["at"], reverse=True)
        return items[:limit]

    async def alerts(self) -> list[dict[str, Any]]:
        """Things the shopkeeper should act on today."""
        out: list[dict[str, Any]] = []

        overdue = (
            await self.db.execute(
                select(func.count(), func.coalesce(func.sum(Voucher.balance_amount), 0)).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.balance_amount > 0,
                    Voucher.due_date < date.today(),
                    Voucher.status.notin_(_POSTED),
                )
            )
        ).one()
        if overdue[0]:
            out.append({
                "kind": "overdue_payments", "severity": "warning",
                "title": f"{int(overdue[0])} overdue invoice(s)",
                "body": f"{money(overdue[1])} is past its due date.",
                "action": {"route": "/invoices", "filter": "overdue"},
            })

        low = await self._low_stock_count()
        if low:
            out.append({
                "kind": "low_stock", "severity": "info",
                "title": f"{low} item(s) running low",
                "body": "Reorder before you run out.",
                "action": {"route": "/items", "filter": "low_stock"},
            })

        expiring = (
            await self.db.execute(
                select(func.count()).select_from(Voucher).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.voucher_type == VoucherType.QUOTATION,
                    Voucher.status == VoucherStatus.UNPAID,
                    Voucher.voucher_date <= date.today() - timedelta(days=7),
                )
            )
        ).scalar_one()
        if expiring:
            out.append({
                "kind": "stale_quotations", "severity": "info",
                "title": f"{int(expiring)} quotation(s) awaiting a reply",
                "body": "Follow up to convert them into sales.",
                "action": {"route": "/quotations"},
            })
        return out

    # ── P&L ──────────────────────────────────────────────────────
    async def profit_and_loss(self, start: date, end: date) -> dict[str, Any]:
        sales = await self._voucher_total(VoucherType.SALE, start, end)
        sales_returns = await self._voucher_total(VoucherType.SALE_RETURN, start, end)
        purchases = await self._voucher_total(VoucherType.PURCHASE, start, end)
        purchase_returns = await self._voucher_total(VoucherType.PURCHASE_RETURN, start, end)

        net_sales = money(sales - sales_returns)
        # COGS from the recorded cost on each sold line — accurate even when prices move.
        cogs = money(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(VoucherLine.cost_price * VoucherLine.qty), 0))
                    .join(Voucher, VoucherLine.voucher_id == Voucher.id)
                    .where(
                        Voucher.business_id == self.business_id,
                        Voucher.is_deleted.is_(False),
                        Voucher.status.notin_(_POSTED),
                        Voucher.voucher_type == VoucherType.SALE,
                        Voucher.voucher_date >= start,
                        Voucher.voucher_date <= end,
                    )
                )
            ).scalar_one()
        )

        gross_profit = money(net_sales - cogs)
        direct = await self._expense_total(start, end, direct_only=True)
        indirect = await self._expense_total(start, end, direct_only=False)
        total_expenses = money(direct + indirect)
        net_profit = money(gross_profit - total_expenses)

        return {
            "start_date": start,
            "end_date": end,
            "sales": sales,
            "sales_returns": sales_returns,
            "net_sales": net_sales,
            "opening_stock": ZERO,
            "purchases": purchases,
            "purchase_returns": purchase_returns,
            "closing_stock": await self._stock_value(),
            "cost_of_goods_sold": cogs,
            "gross_profit": gross_profit,
            "gross_margin_percent": money(safe_div(gross_profit * 100, net_sales)),
            "direct_expenses": direct,
            "indirect_expenses": indirect,
            "total_expenses": total_expenses,
            "expense_breakdown": await self._expense_breakdown(start, end),
            "other_income": ZERO,
            "net_profit": net_profit,
            "net_margin_percent": money(safe_div(net_profit * 100, net_sales)),
        }

    async def balance_sheet(self, as_of: date | None = None) -> dict[str, Any]:
        ref = as_of or date.today()
        cash, bank = await self._account_balances()
        receivable, payable = await self.receivable_payable()
        inventory = await self._stock_value()

        tax_payable = money(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(Voucher.tax_amount), 0)).where(
                        Voucher.business_id == self.business_id,
                        Voucher.is_deleted.is_(False),
                        Voucher.status.notin_(_POSTED),
                        Voucher.voucher_type == VoucherType.SALE,
                        Voucher.voucher_date <= ref,
                    )
                )
            ).scalar_one()
        ) - money(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(Voucher.tax_amount), 0)).where(
                        Voucher.business_id == self.business_id,
                        Voucher.is_deleted.is_(False),
                        Voucher.status.notin_(_POSTED),
                        Voucher.voucher_type == VoucherType.PURCHASE,
                        Voucher.voucher_date <= ref,
                    )
                )
            ).scalar_one()
        )

        total_assets = money(cash + bank + receivable + inventory)
        total_liabilities = money(payable + max(ZERO, tax_payable))
        equity = money(total_assets - total_liabilities)

        return {
            "as_of": ref,
            "cash_and_bank": money(cash + bank),
            "accounts_receivable": receivable,
            "inventory": inventory,
            "other_assets": ZERO,
            "total_assets": total_assets,
            "accounts_payable": payable,
            "tax_payable": money(max(ZERO, tax_payable)),
            "other_liabilities": ZERO,
            "total_liabilities": total_liabilities,
            "capital": ZERO,
            "retained_earnings": equity,
            "total_equity": equity,
            "is_balanced": True,
            "difference": ZERO,
        }

    # ── sales report ─────────────────────────────────────────────
    async def sales_report(
        self, start: date, end: date, *, group_by: str = "day", voucher_type: str = VoucherType.SALE
    ) -> dict[str, Any]:
        base = (
            select(Voucher)
            .where(
                Voucher.business_id == self.business_id,
                Voucher.is_deleted.is_(False),
                Voucher.status.notin_(_POSTED),
                Voucher.voucher_type == voucher_type,
                Voucher.voucher_date >= start,
                Voucher.voucher_date <= end,
            )
        )
        vouchers = (await self.db.execute(base)).scalars().all()

        groups: dict[str, dict[str, Any]] = {}
        for v in vouchers:
            if group_by == "party":
                key = v.party_name or "Walk-in"
            elif group_by == "status":
                key = v.status
            elif group_by in ("day", "week", "month", "quarter", "year"):
                from app.utils.dates import bucket_label

                key = bucket_label(v.voucher_date, group_by)
            else:
                key = "All"
            row = groups.setdefault(
                key,
                {"label": key, "invoice_count": 0, "quantity": ZERO, "taxable": ZERO,
                 "tax": ZERO, "total": ZERO, "profit": ZERO},
            )
            row["invoice_count"] += 1
            row["taxable"] = money(row["taxable"] + v.taxable_amount)
            row["tax"] = money(row["tax"] + v.tax_amount)
            row["total"] = money(row["total"] + v.total)
            row["profit"] = money(row["profit"] + v.profit)
            row["quantity"] = D(row["quantity"]) + sum((line.qty for line in v.lines), ZERO)

        rows = sorted(groups.values(), key=lambda r: r["label"])
        for row in rows:
            row["margin_percent"] = money(safe_div(row["profit"] * 100, row["total"]))

        totals = {
            "label": "Total",
            "invoice_count": sum(r["invoice_count"] for r in rows),
            "quantity": sum((D(r["quantity"]) for r in rows), ZERO),
            "taxable": money(sum((r["taxable"] for r in rows), ZERO)),
            "tax": money(sum((r["tax"] for r in rows), ZERO)),
            "total": money(sum((r["total"] for r in rows), ZERO)),
            "profit": money(sum((r["profit"] for r in rows), ZERO)),
        }
        totals["margin_percent"] = money(safe_div(totals["profit"] * 100, totals["total"]))

        return {
            "start_date": start, "end_date": end, "group_by": group_by,
            "rows": rows, "totals": totals,
            "series": [{"label": r["label"], "value": r["total"], "secondary": r["profit"]} for r in rows],
        }

    # ── tax ──────────────────────────────────────────────────────
    async def tax_report(self, start: date, end: date) -> dict[str, Any]:
        output = await self._tax_rows(VoucherType.SALE, start, end)
        inputs = await self._tax_rows(VoucherType.PURCHASE, start, end)
        total_out = money(sum((r["total_tax"] for r in output), ZERO))
        total_in = money(sum((r["total_tax"] for r in inputs), ZERO))
        return {
            "start_date": start,
            "end_date": end,
            "output_tax": output,
            "input_tax": inputs,
            "total_output_tax": total_out,
            "total_input_tax": total_in,
            "net_payable": money(total_out - total_in),
            "hsn_summary": await self._hsn_summary(start, end),
        }

    async def _tax_rows(self, voucher_type: str, start: date, end: date) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    VoucherLine.tax_rate,
                    func.sum(VoucherLine.taxable_amount),
                    func.sum(VoucherLine.cgst_amount),
                    func.sum(VoucherLine.sgst_amount),
                    func.sum(VoucherLine.igst_amount),
                    func.sum(VoucherLine.cess_amount),
                    func.count(func.distinct(VoucherLine.voucher_id)),
                )
                .join(Voucher, VoucherLine.voucher_id == Voucher.id)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == voucher_type,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .group_by(VoucherLine.tax_rate)
                .order_by(VoucherLine.tax_rate)
            )
        ).all()
        return [
            {
                "rate": D(rate), "taxable": money(taxable), "cgst": money(cgst),
                "sgst": money(sgst), "igst": money(igst), "cess": money(cess),
                "total_tax": money(D(cgst) + D(sgst) + D(igst) + D(cess)),
                "invoice_count": int(n),
            }
            for rate, taxable, cgst, sgst, igst, cess, n in rows
        ]

    async def _hsn_summary(self, start: date, end: date) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(
                    func.coalesce(VoucherLine.hsn_code, "-"),
                    func.sum(VoucherLine.qty),
                    func.sum(VoucherLine.taxable_amount),
                    func.sum(VoucherLine.tax_amount),
                )
                .join(Voucher, VoucherLine.voucher_id == Voucher.id)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .group_by(func.coalesce(VoucherLine.hsn_code, "-"))
                .order_by(func.sum(VoucherLine.taxable_amount).desc())
                .limit(50)
            )
        ).all()
        return [
            {"hsn": hsn, "quantity": D(q), "taxable": money(taxable), "tax": money(tax)}
            for hsn, q, taxable, tax in rows
        ]

    # ── daybook & cash flow ──────────────────────────────────────
    async def daybook(self, start: date, end: date) -> dict[str, Any]:
        vouchers = (
            await self.db.execute(
                select(Voucher).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).scalars().all()
        payments = (
            await self.db.execute(
                select(Payment).where(
                    Payment.business_id == self.business_id,
                    Payment.is_deleted.is_(False),
                    Payment.payment_date >= start,
                    Payment.payment_date <= end,
                )
            )
        ).scalars().all()
        expenses = (
            await self.db.execute(
                select(Expense).where(
                    Expense.business_id == self.business_id,
                    Expense.is_deleted.is_(False),
                    Expense.expense_date >= start,
                    Expense.expense_date <= end,
                )
            )
        ).scalars().all()

        entries: list[dict[str, Any]] = []
        for v in vouchers:
            inflow = v.voucher_type in (VoucherType.SALE, VoucherType.PURCHASE_RETURN)
            entries.append({
                "date": v.voucher_date, "entry_type": v.voucher_type,
                "reference_number": v.number, "party_name": v.party_name,
                "description": f"{v.voucher_type.replace('_', ' ').title()} — {len(v.lines)} item(s)",
                "debit": money(v.total) if inflow else ZERO,
                "credit": ZERO if inflow else money(v.total),
                "entity_id": v.id,
            })
        for p in payments:
            received = p.direction == PaymentDirection.IN
            entries.append({
                "date": p.payment_date, "entry_type": f"payment_{p.direction}",
                "reference_number": p.number, "party_name": p.party_name,
                "description": f"Payment {'received' if received else 'made'}",
                "debit": money(p.amount) if received else ZERO,
                "credit": ZERO if received else money(p.amount),
                "mode": p.mode, "entity_id": p.id,
            })
        for e in expenses:
            entries.append({
                "date": e.expense_date, "entry_type": "expense",
                "reference_number": e.number, "party_name": e.vendor_name,
                "description": e.title, "debit": ZERO, "credit": money(e.total),
                "mode": e.payment_mode, "entity_id": e.id,
            })

        entries.sort(key=lambda x: x["date"])
        total_in = money(sum((e["debit"] for e in entries), ZERO))
        total_out = money(sum((e["credit"] for e in entries), ZERO))
        cash, bank = await self._account_balances()

        return {
            "start_date": start, "end_date": end,
            "opening_cash": ZERO, "closing_cash": money(cash + bank),
            "total_in": total_in, "total_out": total_out, "entries": entries,
        }

    async def cash_flow(self, start: date, end: date) -> dict[str, Any]:
        received = await self._payment_total(PaymentDirection.IN, start, end)
        paid = await self._payment_total(PaymentDirection.OUT, start, end)
        expenses = await self._expense_total(start, end)
        cash, bank = await self._account_balances()

        granularity = auto_granularity(start, end)
        series: list[dict[str, Any]] = []
        for label, b_start, b_end in iter_buckets(start, end, granularity):
            inflow = await self._payment_total(PaymentDirection.IN, b_start, b_end)
            outflow = money(
                await self._payment_total(PaymentDirection.OUT, b_start, b_end)
                + await self._expense_total(b_start, b_end)
            )
            series.append({"label": label, "value": inflow, "secondary": outflow})

        total_out = money(paid + expenses)
        return {
            "start_date": start, "end_date": end,
            "opening_balance": ZERO,
            "inflows": [{"label": "Customer receipts", "amount": received}],
            "outflows": [
                {"label": "Supplier payments", "amount": paid},
                {"label": "Expenses", "amount": expenses},
            ],
            "total_inflow": received,
            "total_outflow": total_out,
            "net_flow": money(received - total_out),
            "closing_balance": money(cash + bank),
            "series": series,
        }

    # ── shared aggregates ────────────────────────────────────────
    async def receivable_payable(self) -> tuple[Decimal, Decimal]:
        row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(case((Party.balance > 0, Party.balance), else_=0)), 0),
                    func.coalesce(func.sum(case((Party.balance < 0, -Party.balance), else_=0)), 0),
                ).where(Party.business_id == self.business_id, Party.is_deleted.is_(False))
            )
        ).one()
        return money(row[0]), money(row[1])

    # ── batched period aggregates ────────────────────────────────
    # Each of these answers "how much, per period" in a single statement, using
    # SUM(CASE ...) rather than Postgres' FILTER so the same code runs on SQLite.
    # The filters are copied exactly from the single-period helpers below, which
    # remain the reference implementation for every other report.

    async def _voucher_totals(
        self, periods: list[tuple[date, date]]
    ) -> list[dict[str, Decimal]]:
        columns = []
        for index, (start, end) in enumerate(periods):
            in_period = and_(Voucher.voucher_date >= start, Voucher.voucher_date <= end)
            columns += [
                func.coalesce(
                    func.sum(
                        case(
                            (and_(in_period, Voucher.voucher_type == VoucherType.SALE), Voucher.total),
                            else_=0,
                        )
                    ),
                    0,
                ).label(f"sale_{index}"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(in_period, Voucher.voucher_type == VoucherType.PURCHASE),
                                Voucher.total,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label(f"purchase_{index}"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(in_period, Voucher.voucher_type == VoucherType.SALE),
                                Voucher.profit,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label(f"profit_{index}"),
            ]

        # Narrow the scan to the union of the periods; everything outside it
        # contributes zero to every CASE anyway.
        earliest = min(p[0] for p in periods)
        latest = max(p[1] for p in periods)

        row = (
            await self.db.execute(
                select(*columns).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_date >= earliest,
                    Voucher.voucher_date <= latest,
                )
            )
        ).one()

        return [
            {
                "sale": money(row[index * 3]),
                "purchase": money(row[index * 3 + 1]),
                "profit": money(row[index * 3 + 2]),
            }
            for index in range(len(periods))
        ]

    async def _payment_totals(self, periods: list[tuple[date, date]]) -> list[Decimal]:
        columns = [
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(Payment.payment_date >= start, Payment.payment_date <= end),
                            Payment.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
            for start, end in periods
        ]
        row = (
            await self.db.execute(
                select(*columns).where(
                    Payment.business_id == self.business_id,
                    Payment.is_deleted.is_(False),
                    Payment.direction == PaymentDirection.IN,
                    Payment.payment_date >= min(p[0] for p in periods),
                    Payment.payment_date <= max(p[1] for p in periods),
                )
            )
        ).one()
        return [money(value) for value in row]

    async def _expense_totals(self, periods: list[tuple[date, date]]) -> list[Decimal]:
        columns = [
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(Expense.expense_date >= start, Expense.expense_date <= end),
                            Expense.total,
                        ),
                        else_=0,
                    )
                ),
                0,
            )
            for start, end in periods
        ]
        row = (
            await self.db.execute(
                select(*columns).where(
                    Expense.business_id == self.business_id,
                    Expense.is_deleted.is_(False),
                    Expense.expense_date >= min(p[0] for p in periods),
                    Expense.expense_date <= max(p[1] for p in periods),
                )
            )
        ).one()
        return [money(value) for value in row]

    async def _voucher_total(self, voucher_type: str, start: date, end: date) -> Decimal:
        value = (
            await self.db.execute(
                select(func.coalesce(func.sum(Voucher.total), 0)).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == voucher_type,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).scalar_one()
        return money(value)

    async def _profit_total(self, start: date, end: date) -> Decimal:
        value = (
            await self.db.execute(
                select(func.coalesce(func.sum(Voucher.profit), 0)).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).scalar_one()
        return money(value)

    async def _payment_total(self, direction: str, start: date, end: date) -> Decimal:
        value = (
            await self.db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.business_id == self.business_id,
                    Payment.is_deleted.is_(False),
                    Payment.direction == direction,
                    Payment.payment_date >= start,
                    Payment.payment_date <= end,
                )
            )
        ).scalar_one()
        return money(value)

    async def _expense_total(self, start: date, end: date, *, direct_only: bool | None = None) -> Decimal:
        stmt = select(func.coalesce(func.sum(Expense.total), 0)).where(
            Expense.business_id == self.business_id,
            Expense.is_deleted.is_(False),
            Expense.expense_date >= start,
            Expense.expense_date <= end,
        )
        if direct_only is not None:
            stmt = stmt.outerjoin(ExpenseCategory, Expense.category_id == ExpenseCategory.id).where(
                func.coalesce(ExpenseCategory.is_direct_cost, False).is_(direct_only)
            )
        return money((await self.db.execute(stmt)).scalar_one())

    async def _expense_breakdown(self, start: date, end: date) -> list[dict[str, Any]]:
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
            )
        ).all()
        return [
            {"category": c or "Uncategorised", "amount": money(t), "count": int(n)}
            for c, t, n in rows
        ]

    async def _account_balances(self) -> tuple[Decimal, Decimal]:
        rows = (
            await self.db.execute(
                select(Account.account_type, func.coalesce(func.sum(Account.balance), 0))
                .where(
                    Account.business_id == self.business_id,
                    Account.is_deleted.is_(False),
                    Account.is_active.is_(True),
                )
                .group_by(Account.account_type)
            )
        ).all()
        cash = money(sum((D(b) for t, b in rows if t == "cash"), ZERO))
        bank = money(sum((D(b) for t, b in rows if t != "cash"), ZERO))
        return cash, bank

    async def _stock_value(self) -> Decimal:
        value = (
            await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            Item.stock_qty
                            * case((Item.avg_cost > 0, Item.avg_cost), else_=Item.purchase_price)
                        ),
                        0,
                    )
                ).where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.track_inventory.is_(True),
                    Item.stock_qty > 0,
                )
            )
        ).scalar_one()
        return money(value)

    async def _invoice_counts(self, start: date, end: date) -> dict[str, Any]:
        row = (
            await self.db.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(case((Voucher.balance_amount > 0, 1), else_=0)), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                ((Voucher.balance_amount > 0) & (Voucher.due_date < date.today()), 1),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            case(
                                ((Voucher.balance_amount > 0) & (Voucher.due_date < date.today()),
                                 Voucher.balance_amount),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                ).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).one()
        return {
            "invoice_count": int(row[0]),
            "unpaid_invoice_count": int(row[1]),
            "overdue_invoice_count": int(row[2]),
            "overdue_amount": money(row[3]),
        }

    async def _new_parties(self, start: date, end: date) -> int:
        from datetime import datetime, time

        value = (
            await self.db.execute(
                select(func.count()).select_from(Party).where(
                    Party.business_id == self.business_id,
                    Party.is_deleted.is_(False),
                    Party.created_at >= datetime.combine(start, time.min),
                    Party.created_at <= datetime.combine(end, time.max),
                )
            )
        ).scalar_one()
        return int(value)

    async def _low_stock_count(self) -> int:
        value = (
            await self.db.execute(
                select(func.count()).select_from(Item).where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.is_active.is_(True),
                    Item.track_inventory.is_(True),
                    Item.low_stock_qty.isnot(None),
                    Item.stock_qty <= Item.low_stock_qty,
                )
            )
        ).scalar_one()
        return int(value)

    async def _business(self) -> Business:
        return (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()


def _trend(current: Decimal, previous: Decimal | None) -> dict[str, Any]:
    change = growth_pct(current, previous) if previous is not None else None
    direction = "flat"
    if change is not None:
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
    return {
        "value": money(current),
        "previous": money(previous) if previous is not None else None,
        "change_percent": change,
        "direction": direction,
    }
