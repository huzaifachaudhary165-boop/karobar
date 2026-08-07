"""The reports a shopkeeper asks for when the obvious ones are not enough.

Each one answers a question somebody actually asks out loud — which goods are
dead on the shelf, which customers are worth keeping, how much margin walked
out as discount. A report nobody would ask for is a screen nobody opens.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select

from app.core.money import ZERO, money, qty, safe_div
from app.models.enums import PaymentDirection, VoucherStatus, VoucherType
from app.models.expense import Expense, ExpenseCategory
from app.models.item import Item, StockLedgerEntry
from app.models.party import Party
from app.models.payment import Payment
from app.models.voucher import Voucher, VoucherLine
from app.services.base import ActorContext

_NOT_POSTED = [VoucherStatus.CANCELLED, VoucherStatus.DRAFT, VoucherStatus.CONVERTED]


class AnalyticsService:
    def __init__(self, db, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    # ── stock that is not moving ───────────────────────────────────
    async def dead_stock(self, *, days: int = 90, limit: int = 100) -> list[dict[str, Any]]:
        """Goods that have not sold in a while, and what they are tying up.

        The number that matters is the value, not the count. Forty slow items
        worth two hundred rupees between them is not a problem; one worth
        eighty thousand is the reason the shop cannot pay its supplier.
        """
        cutoff = date.today() - timedelta(days=days)
        rows = (
            await self.db.execute(
                select(Item)
                .where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.track_inventory.is_(True),
                    Item.stock_qty > 0,
                    or_(
                        Item.last_sold_at.is_(None),
                        func.date(Item.last_sold_at) < cutoff,
                    ),
                )
                .order_by((Item.stock_qty * Item.avg_cost).desc())
                .limit(limit)
            )
        ).scalars().all()

        today = date.today()
        return [
            {
                "item_id": item.id,
                "item_name": item.name,
                "unit_label": item.unit_label,
                "stock_qty": qty(item.stock_qty),
                "stock_value": money(item.stock_value),
                "last_sold_at": item.last_sold_at,
                # Never sold at all is the worst case, and saying "None" days
                # would sort it as if it were the freshest thing in the shop.
                "days_idle": (
                    (today - item.last_sold_at.date()).days
                    if item.last_sold_at
                    else None
                ),
                "never_sold": item.last_sold_at is None,
            }
            for item in rows
        ]

    async def stock_ageing(self) -> list[dict[str, Any]]:
        """How long the stock on hand has been sitting, in bands.

        Bands rather than an average: an average of sixty days hides that half
        the money is in goods nobody has touched in a year.
        """
        rows = (
            await self.db.execute(
                select(Item).where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.track_inventory.is_(True),
                    Item.stock_qty > 0,
                )
            )
        ).scalars().all()

        bands = [
            ("0-30 days", 0, 30),
            ("31-90 days", 31, 90),
            ("91-180 days", 91, 180),
            ("181-365 days", 181, 365),
            ("Over a year", 366, 99999),
        ]
        today = date.today()
        buckets = {name: {"label": name, "items": 0, "value": ZERO} for name, _, _ in bands}

        for item in rows:
            reference = item.last_purchased_at or item.created_at
            age = (today - reference.date()).days if reference else 0
            for name, low, high in bands:
                if low <= age <= high:
                    buckets[name]["items"] += 1
                    buckets[name]["value"] += item.stock_value
                    break

        return [
            {**bucket, "value": money(bucket["value"])} for bucket in buckets.values()
        ]

    # ── what actually makes money ──────────────────────────────────
    async def item_profit(
        self, start: date, end: date, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Profit per item, which is not the same list as sales per item.

        The best-selling thing in a shop is often the one it makes least on,
        and a shopkeeper looking only at turnover pushes exactly that.
        """
        rows = (
            await self.db.execute(
                select(
                    VoucherLine.item_id,
                    VoucherLine.item_name,
                    func.sum(VoucherLine.qty).label("qty"),
                    func.sum(VoucherLine.total).label("revenue"),
                    func.sum(VoucherLine.qty * VoucherLine.cost_price).label("cost"),
                )
                .join(Voucher, Voucher.id == VoucherLine.voucher_id)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .group_by(VoucherLine.item_id, VoucherLine.item_name)
                .order_by(
                    (
                        func.sum(VoucherLine.total)
                        - func.sum(VoucherLine.qty * VoucherLine.cost_price)
                    ).desc()
                )
                .limit(limit)
            )
        ).all()

        out = []
        for item_id, name, sold, revenue, cost in rows:
            revenue, cost = money(revenue or ZERO), money(cost or ZERO)
            profit = money(revenue - cost)
            out.append(
                {
                    "item_id": item_id,
                    "item_name": name,
                    "qty_sold": qty(sold or ZERO),
                    "revenue": revenue,
                    "cost": cost,
                    "profit": profit,
                    "margin_percent": money(safe_div(profit * 100, revenue)),
                }
            )
        return out

    async def party_profit(
        self, start: date, end: date, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Profit per customer. The biggest buyer is not always the best one."""
        rows = (
            await self.db.execute(
                select(
                    Voucher.party_id,
                    Voucher.party_name,
                    func.count(Voucher.id).label("bills"),
                    func.sum(Voucher.total).label("revenue"),
                    func.sum(Voucher.profit).label("profit"),
                )
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .group_by(Voucher.party_id, Voucher.party_name)
                .order_by(func.sum(Voucher.profit).desc())
                .limit(limit)
            )
        ).all()

        return [
            {
                "party_id": party_id,
                "party_name": name or "Walk-in",
                "bill_count": int(bills),
                "revenue": money(revenue or ZERO),
                "profit": money(profit or ZERO),
                "margin_percent": money(
                    safe_div(money(profit or ZERO) * 100, money(revenue or ZERO))
                ),
            }
            for party_id, name, bills, revenue, profit in rows
        ]

    # ── margin given away ──────────────────────────────────────────
    async def discounts_given(self, start: date, end: date) -> dict[str, Any]:
        """How much margin left the shop as discount.

        Shopkeepers give discounts one bill at a time and never see the total.
        Set against profit, it is usually a larger number than expected.
        """
        row = (
            await self.db.execute(
                select(
                    func.sum(Voucher.discount_amount),
                    func.sum(Voucher.subtotal),
                    func.sum(Voucher.profit),
                    func.count(Voucher.id),
                    func.sum(case((Voucher.discount_amount > 0, 1), else_=0)),
                )
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
            )
        ).one()

        discount, subtotal, profit, bills, discounted = row
        discount = money(discount or ZERO)
        profit = money(profit or ZERO)

        return {
            "total_discount": discount,
            "gross_sales": money(subtotal or ZERO),
            "profit": profit,
            "bill_count": int(bills or 0),
            "discounted_bill_count": int(discounted or 0),
            "discount_percent": money(safe_div(discount * 100, money(subtotal or ZERO))),
            # The comparison that lands: discount as a share of what was
            # actually earned, not of what was invoiced.
            "share_of_profit": money(safe_div(discount * 100, profit)),
        }

    # ── how customers pay ──────────────────────────────────────────
    async def payment_modes(self, start: date, end: date) -> list[dict[str, Any]]:
        """What money came in as. A shop taking half its takings by wallet and
        still counting a drawer at closing is reconciling the wrong thing."""
        rows = (
            await self.db.execute(
                select(
                    Payment.mode,
                    func.count(Payment.id),
                    func.sum(Payment.amount),
                )
                .where(
                    Payment.business_id == self.business_id,
                    Payment.is_deleted.is_(False),
                    Payment.direction == PaymentDirection.IN,
                    Payment.payment_date >= start,
                    Payment.payment_date <= end,
                )
                .group_by(Payment.mode)
                .order_by(func.sum(Payment.amount).desc())
            )
        ).all()

        total = money(sum((amount or ZERO for _m, _c, amount in rows), ZERO))
        return [
            {
                "mode": mode,
                "count": int(count),
                "amount": money(amount or ZERO),
                "share_percent": money(safe_div(money(amount or ZERO) * 100, total)),
            }
            for mode, count, amount in rows
        ]

    # ── registers ──────────────────────────────────────────────────
    async def purchase_register(
        self, start: date, end: date, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type == VoucherType.PURCHASE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .order_by(Voucher.voucher_date.desc())
                .limit(limit)
            )
        ).scalars().all()

        return [
            {
                "id": row.id,
                "number": row.number,
                "date": row.voucher_date,
                "party_name": row.party_name or "—",
                "taxable": money(row.taxable_amount),
                "tax": money(row.tax_amount),
                "total": money(row.total),
                "balance": money(row.balance_amount),
            }
            for row in rows
        ]

    async def returns_register(
        self, start: date, end: date, *, sales: bool = True
    ) -> list[dict[str, Any]]:
        """Returns, which a shop rarely looks at and should.

        A supplier whose goods keep coming back, or a customer who returns half
        of what they buy, is a pattern nobody notices one credit note at a time.
        """
        kind = VoucherType.SALE_RETURN if sales else VoucherType.PURCHASE_RETURN
        rows = (
            await self.db.execute(
                select(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type == kind,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .order_by(Voucher.voucher_date.desc())
            )
        ).scalars().all()

        return [
            {
                "id": row.id,
                "number": row.number,
                "date": row.voucher_date,
                "party_name": row.party_name or "—",
                "total": money(row.total),
                "reason": (row.notes or "").strip()[:120] or None,
            }
            for row in rows
        ]

    # ── expenses over time ─────────────────────────────────────────
    async def expense_trend(self, start: date, end: date) -> list[dict[str, Any]]:
        """Spending by category, with what it was in the period before.

        A category on its own is a number; the same category against last month
        is a decision.
        """
        span = (end - start).days + 1
        previous_start = start - timedelta(days=span)
        previous_end = start - timedelta(days=1)

        async def totals(from_date: date, to_date: date) -> dict[str, Decimal]:
            rows = (
                await self.db.execute(
                    select(
                        func.coalesce(ExpenseCategory.name, "Uncategorised"),
                        func.sum(Expense.total),
                    )
                    .select_from(Expense)
                    .outerjoin(ExpenseCategory, ExpenseCategory.id == Expense.category_id)
                    .where(
                        Expense.business_id == self.business_id,
                        Expense.is_deleted.is_(False),
                        Expense.expense_date >= from_date,
                        Expense.expense_date <= to_date,
                    )
                    .group_by(ExpenseCategory.name)
                )
            ).all()
            return {name: money(amount or ZERO) for name, amount in rows}

        now = await totals(start, end)
        before = await totals(previous_start, previous_end)

        out = []
        for name in sorted(set(now) | set(before), key=lambda k: -now.get(k, ZERO)):
            this_period = now.get(name, ZERO)
            last_period = before.get(name, ZERO)
            out.append(
                {
                    "category": name,
                    "amount": this_period,
                    "previous_amount": last_period,
                    "change": money(this_period - last_period),
                    "change_percent": (
                        money(safe_div((this_period - last_period) * 100, last_period))
                        if last_period
                        else None
                    ),
                }
            )
        return out

    # ── who sold what ──────────────────────────────────────────────
    async def by_user(self, start: date, end: date) -> list[dict[str, Any]]:
        """Sales by whoever raised them, for a shop with staff on the counter."""
        rows = (
            await self.db.execute(
                select(
                    Voucher.created_by,
                    func.count(Voucher.id),
                    func.sum(Voucher.total),
                    func.sum(Voucher.profit),
                )
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_NOT_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date >= start,
                    Voucher.voucher_date <= end,
                )
                .group_by(Voucher.created_by)
                .order_by(func.sum(Voucher.total).desc())
            )
        ).all()

        return [
            {
                "user_id": user_id,
                "bill_count": int(bills),
                "revenue": money(revenue or ZERO),
                "profit": money(profit or ZERO),
                "average_bill": money(safe_div(money(revenue or ZERO), Decimal(bills or 1))),
            }
            for user_id, bills, revenue, profit in rows
        ]

    # ── stock movement across everything ───────────────────────────
    async def stock_movement(
        self, start: date, end: date, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """In, out and where each item ended up over a period."""
        rows = (
            await self.db.execute(
                select(
                    StockLedgerEntry.item_id,
                    Item.name,
                    Item.unit_label,
                    Item.stock_qty,
                    func.sum(
                        case((StockLedgerEntry.qty > 0, StockLedgerEntry.qty), else_=0)
                    ).label("in_qty"),
                    func.sum(
                        case((StockLedgerEntry.qty < 0, -StockLedgerEntry.qty), else_=0)
                    ).label("out_qty"),
                )
                .join(Item, Item.id == StockLedgerEntry.item_id)
                .where(
                    StockLedgerEntry.business_id == self.business_id,
                    func.date(StockLedgerEntry.entry_date) >= start,
                    func.date(StockLedgerEntry.entry_date) <= end,
                    Item.is_deleted.is_(False),
                )
                .group_by(
                    StockLedgerEntry.item_id, Item.name, Item.unit_label, Item.stock_qty
                )
                .order_by(func.sum(
                    case((StockLedgerEntry.qty < 0, -StockLedgerEntry.qty), else_=0)
                ).desc())
                .limit(limit)
            )
        ).all()

        return [
            {
                "item_id": item_id,
                "item_name": name,
                "unit_label": unit,
                "received": qty(in_qty or ZERO),
                "issued": qty(out_qty or ZERO),
                "closing": qty(closing or ZERO),
            }
            for item_id, name, unit, closing, in_qty, out_qty in rows
        ]

    # ── who owes what, and for how long ────────────────────────────
    async def customer_balances(self, *, receivable: bool = True) -> list[dict[str, Any]]:
        """Everyone with an outstanding balance, largest first."""
        stmt = select(Party).where(
            Party.business_id == self.business_id,
            Party.is_deleted.is_(False),
        )
        stmt = stmt.where(Party.balance > 0) if receivable else stmt.where(Party.balance < 0)

        rows = (
            await self.db.execute(
                stmt.order_by(func.abs(Party.balance).desc()).limit(200)
            )
        ).scalars().all()

        return [
            {
                "party_id": party.id,
                "party_name": party.name,
                "phone": party.phone,
                "balance": money(abs(party.balance)),
                "credit_limit": money(party.credit_limit) if party.credit_limit else None,
                "over_limit": party.is_over_credit_limit,
            }
            for party in rows
        ]
