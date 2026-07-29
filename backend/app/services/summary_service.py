"""The end-of-day summary.

One message a shopkeeper reads while pulling the shutter down: what came in,
what is still owed, what ran out. It replaces opening the app and tapping
through four screens to answer the same four questions.

Written from real figures, not by a model — a daily number that is occasionally
hallucinated is worse than no daily number, and this has to be trustworthy
enough to act on. The assistant is for questions; this is for facts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.core.money import ZERO, format_money, money
from app.models.business import Business, BusinessSettings
from app.models.enums import PaymentDirection, VoucherStatus, VoucherType
from app.models.expense import Expense
from app.models.item import Item
from app.models.payment import Payment
from app.models.voucher import Voucher
from app.services.base import ActorContext

_POSTED = [VoucherStatus.CANCELLED, VoucherStatus.DRAFT]


def _qty(value: Any) -> str:
    """Drops meaningless decimals: 4.0000 → "4", 2.5000 → "2.5"."""
    if value is None:
        return "0"
    text = f"{value:f}".rstrip("0").rstrip(".")
    return text or "0"


class SummaryService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def for_day(self, day: date | None = None) -> dict[str, Any]:
        day = day or date.today()
        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        symbol = f"{business.currency_symbol} "

        sales, bill_count = await self._sales(day)
        collected = await self._payments(day, PaymentDirection.IN)
        paid_out = await self._payments(day, PaymentDirection.OUT)
        expenses = await self._expenses(day)
        receivable = await self._receivable()
        low_stock = await self._low_stock()

        return {
            "date": day.isoformat(),
            "business": business.name,
            "currency": business.currency_symbol,
            "sales": money(sales),
            "bill_count": bill_count,
            "collected": money(collected),
            "paid_out": money(paid_out),
            "expenses": money(expenses),
            # Cash movement, not profit: profit needs cost of goods, and a
            # number labelled "profit" that is really margin would mislead.
            "net_cash": money(collected - paid_out - expenses),
            "receivable": money(receivable),
            "low_stock": low_stock,
            "message": self._compose(
                business_name=business.name,
                day=day,
                symbol=symbol,
                sales=sales,
                bill_count=bill_count,
                collected=collected,
                expenses=expenses,
                receivable=receivable,
                low_stock=low_stock,
            ),
        }

    # ── figures ──────────────────────────────────────────────────
    async def _sales(self, day: date) -> tuple[Any, int]:
        row = (
            await self.db.execute(
                select(func.coalesce(func.sum(Voucher.total), 0), func.count()).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.voucher_date == day,
                )
            )
        ).one()
        return row[0], int(row[1])

    async def _payments(self, day: date, direction: str) -> Any:
        return (
            await self.db.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.business_id == self.business_id,
                    Payment.is_deleted.is_(False),
                    Payment.direction == direction,
                    Payment.payment_date == day,
                )
            )
        ).scalar_one()

    async def _expenses(self, day: date) -> Any:
        return (
            await self.db.execute(
                select(func.coalesce(func.sum(Expense.total), 0)).where(
                    Expense.business_id == self.business_id,
                    Expense.is_deleted.is_(False),
                    Expense.expense_date == day,
                )
            )
        ).scalar_one()

    async def _receivable(self) -> Any:
        return (
            await self.db.execute(
                select(func.coalesce(func.sum(Voucher.balance_amount), 0)).where(
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                    Voucher.status.notin_(_POSTED),
                    Voucher.voucher_type == VoucherType.SALE,
                    Voucher.balance_amount > 0,
                )
            )
        ).scalar_one()

    async def _low_stock(self, limit: int = 5) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(Item.name, Item.stock_qty, Item.unit_label)
                .where(
                    Item.business_id == self.business_id,
                    Item.is_deleted.is_(False),
                    Item.is_active.is_(True),
                    Item.track_inventory.is_(True),
                    Item.low_stock_qty.isnot(None),
                    Item.stock_qty <= Item.low_stock_qty,
                )
                .order_by(Item.stock_qty)
                .limit(limit)
            )
        ).all()
        return [
            # "4 Bag", not "4.0000 Bag" — the stored scale is for arithmetic, not
            # for a message somebody reads on their phone.
            {"name": name, "qty": _qty(qty), "unit": unit} for name, qty, unit in rows
        ]

    # ── the message ──────────────────────────────────────────────
    def _compose(
        self,
        *,
        business_name: str,
        day: date,
        symbol: str,
        sales: Any,
        bill_count: int,
        collected: Any,
        expenses: Any,
        receivable: Any,
        low_stock: list[dict[str, Any]],
    ) -> str:
        """Plain text, WhatsApp-shaped.

        Roman Urdu because that is what the recipient reads fastest, and because
        this arrives as a WhatsApp message rather than inside the app where a
        language setting would apply.
        """
        money_ = lambda v: format_money(v or ZERO, symbol=symbol)  # noqa: E731

        lines = [
            f"*{business_name}* — {day.strftime('%d %b')}",
            "",
            f"Sale: *{money_(sales)}*" + (f"  ({bill_count} bill)" if bill_count == 1
                                          else f"  ({bill_count} bills)"),
            f"Cash aayi: {money_(collected)}",
        ]
        if expenses and expenses > 0:
            lines.append(f"Kharcha: {money_(expenses)}")

        if sales and sales > 0 and collected < sales:
            udhaar = money(sales - collected)
            lines.append(f"Aaj ka udhaar: {money_(udhaar)}")

        if receivable and receivable > 0:
            lines.append("")
            lines.append(f"Kul baqaya: *{money_(receivable)}*")

        if low_stock:
            lines.append("")
            lines.append("Khatam ho raha hai:")
            for item in low_stock:
                lines.append(f"  • {item['name']} — {item['qty']} {item['unit']}")

        if not bill_count:
            lines.append("")
            lines.append("Aaj koi bill nahi bana.")

        return "\n".join(lines)

    # ── delivery ─────────────────────────────────────────────────
    async def send(self, day: date | None = None) -> dict[str, Any]:
        """Sends the summary on whichever channel is configured.

        Silently doing nothing when a shop has the daily summary switched off is
        deliberate: this is called by a scheduler across every business, and one
        shop's preference must not look like a failure.
        """
        cfg = (
            await self.db.execute(
                select(BusinessSettings).where(
                    BusinessSettings.business_id == self.business_id
                )
            )
        ).scalar_one_or_none()

        if cfg is not None and not cfg.daily_summary_enabled:
            return {"sent": False, "reason": "disabled_for_this_business"}

        summary = await self.for_day(day)
        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()

        delivered: list[str] = []

        if business.phone:
            from app.integrations.whatsapp import WhatsAppService  # noqa: PLC0415

            service = WhatsAppService(self.db, self.business_id, self.actor.user_id)
            if service.client.configured:
                try:
                    await service.send_text(business.phone, summary["message"])
                    delivered.append("whatsapp")
                except Exception as exc:  # noqa: BLE001 — one channel failing
                    log.warning("summary.whatsapp_failed", error=str(exc)[:200])

        if business.email:
            from app.integrations.email import EmailSender  # noqa: PLC0415

            sender = EmailSender()
            if sender.configured:
                try:
                    sent = await sender.send_plain(
                        business.email,
                        f"{business.name} — {summary['date']}",
                        summary["message"],
                    )
                    if sent:
                        delivered.append("email")
                except Exception as exc:  # noqa: BLE001
                    log.warning("summary.email_failed", error=str(exc)[:200])

        log.info("summary.sent", business_id=self.business_id, channels=delivered)
        return {
            "sent": bool(delivered),
            "channels": delivered,
            "date": summary["date"],
            "message": summary["message"],
        }
