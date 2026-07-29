"""Expenses, expense categories and tax-rate masters."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, JSONType, Money
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)
from app.models.enums import PaymentMode, TaxType


class ExpenseCategory(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_expense_category_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(48), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_direct_cost: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    monthly_budget: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Expense(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, AuditedMixin):
    __table_args__ = (
        UniqueConstraint("business_id", "number", name="uq_expense_number"),
        UniqueConstraint("business_id", "client_uuid", name="uq_expense_client_uuid"),
        Index("ix_expenses_biz_date", "business_id", "expense_date"),
        Index("ix_expenses_biz_category", "business_id", "category_id"),
    )

    number: Mapped[str] = mapped_column(String(64), nullable=False)
    expense_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("expense_categories.id", ondelete="SET NULL"), nullable=True
    )
    category_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    total: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    is_tax_inclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    input_tax_claimable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    party_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True
    )
    vendor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    payment_mode: Mapped[str] = mapped_column(String(16), default=PaymentMode.CASH, nullable=False)
    account_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    is_paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(80), nullable=True)

    is_recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recurrence: Mapped[str | None] = mapped_column(String(16), nullable=True)  # monthly|weekly|yearly
    next_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    receipt_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    ocr_job_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    category: Mapped["ExpenseCategory | None"] = relationship(lazy="joined")


class TaxRate(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """Named tax rate, optionally a group (e.g. GST 18% = CGST 9 + SGST 9)."""

    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_tax_rate_name"),)

    name: Mapped[str] = mapped_column(String(60), nullable=False)          # "GST 18%"
    tax_type: Mapped[str] = mapped_column(String(16), default=TaxType.GST, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    cgst_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    cess_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def split(self, interstate: bool) -> tuple[Decimal, Decimal, Decimal]:
        """Returns (cgst, sgst, igst) rates for the supply type."""
        if interstate:
            return Decimal("0"), Decimal("0"), self.igst_rate or self.rate
        half = (self.rate or Decimal("0")) / 2
        return self.cgst_rate or half, self.sgst_rate or half, Decimal("0")
