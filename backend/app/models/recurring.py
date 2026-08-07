"""Bills that repeat: rent, subscriptions, a standing monthly order."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID, JSONType, Money, TZDateTime
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)


class RecurringInvoice(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin,
                       SyncMixin, AuditedMixin):
    """A bill the shop raises on a schedule, and where that schedule has got to.

    The lines are held as JSON rather than as rows of their own. A recurring
    bill is a *template* — what to raise next time — and the moment it becomes
    a real voucher it gets real lines. Keeping a second set of line rows that
    are not on any ledger would mean every stock and tax query had to learn to
    ignore them.
    """

    __table_args__ = (
        Index("ix_recurring_due", "business_id", "is_active", "next_run_on"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    voucher_type: Mapped[str] = mapped_column(String(24), default="sale", nullable=False)

    party_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("parties.id", ondelete="CASCADE"), nullable=True, index=True
    )
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # [{item_id, item_name, qty, rate, tax_rate, discount_value}, ...]
    lines: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    frequency: Mapped[str] = mapped_column(String(16), default="monthly", nullable=False)
    # Every N of that frequency: 2 weekly is a fortnight, 3 monthly a quarter.
    interval: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Stops after this many bills, whatever the end date says.
    max_occurrences: Mapped[int | None] = mapped_column(Integer, nullable=True)

    next_run_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    last_run_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # A shop that wants to check a bill before it goes out gets a reminder
    # instead. Raising one behind their back is worse than not raising it.
    auto_create: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    last_voucher_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    total_billed: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    @property
    def is_finished(self) -> bool:
        if self.max_occurrences is not None and self.occurrences >= self.max_occurrences:
            return True
        return bool(self.ends_on and self.next_run_on > self.ends_on)

    # Named `due_on` rather than `is_due` on purpose: the schema carries an
    # `is_due` field, and a same-named method on the model validates into the
    # response as a bound method instead of a boolean.
    def due_on(self, on: date) -> bool:
        return self.is_active and not self.is_finished and self.next_run_on <= on
