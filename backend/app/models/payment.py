"""Payments in/out, their allocation across invoices, and cash/bank accounts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, JSONType, Money, TZDateTime
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)
from app.models.enums import PaymentDirection, PaymentMode


class Account(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """Cash drawer / bank account / wallet. Balances move with every payment."""

    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_account_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(16), default="cash", nullable=False)  # cash|bank|wallet
    bank_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ifsc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(160), nullable=True)
    upi_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    opening_balance: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_on_invoice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Payment(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, AuditedMixin):
    """A receipt (direction=in) or a disbursement (direction=out).

    `unallocated_amount` is the on-account balance — money received that isn't
    tied to any invoice yet (advance payments).
    """

    __table_args__ = (
        UniqueConstraint("business_id", "number", name="uq_payment_number"),
        UniqueConstraint("business_id", "client_uuid", name="uq_payment_client_uuid"),
        Index("ix_payments_biz_date", "business_id", "payment_date"),
        Index("ix_payments_biz_party", "business_id", "party_id"),
    )

    number: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), default=PaymentDirection.IN, nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    party_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("parties.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    allocated_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    unallocated_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    discount_given: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    mode: Mapped[str] = mapped_column(String(16), default=PaymentMode.CASH, nullable=False)
    account_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reference_number: Mapped[str | None] = mapped_column(String(80), nullable=True)  # cheque/UTR/txn id
    cheque_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cheque_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # pending|cleared|bounced

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)

    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def signed_amount(self) -> Decimal:
        return self.amount if self.direction == PaymentDirection.IN else -self.amount


class PaymentAllocation(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Links a payment to a specific invoice for a specific amount."""

    __table_args__ = (
        UniqueConstraint("payment_id", "voucher_id", name="uq_allocation_payment_voucher"),
        Index("ix_allocations_voucher", "voucher_id"),
    )

    payment_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    voucher_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("vouchers.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    voucher_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    payment: Mapped["Payment"] = relationship(back_populates="allocations")
