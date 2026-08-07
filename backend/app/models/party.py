"""Customers and suppliers ("parties") plus their grouping."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, JSONType, LowerString, Money, TZDateTime
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)
from app.models.enums import PartyType


class PartyGroup(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_party_group_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    default_credit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_discount_percent: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)


class Party(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, AuditedMixin):
    """A customer, a supplier, or both. `balance` is the running ledger figure:
    positive → they owe us (receivable); negative → we owe them (payable)."""

    __table_args__ = (
        Index("ix_parties_biz_name", "business_id", "name"),
        Index("ix_parties_biz_phone", "business_id", "phone"),
        Index("ix_parties_biz_type", "business_id", "party_type", "is_deleted"),
        UniqueConstraint("business_id", "client_uuid", name="uq_party_client_uuid"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    party_type: Mapped[str] = mapped_column(String(16), default=PartyType.CUSTOMER, nullable=False)
    group_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("party_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # contact
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    alternate_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(LowerString(255), nullable=True)
    contact_person: Mapped[str | None] = mapped_column(String(160), nullable=True)

    # address
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # tax
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ntn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Sales tax registration. Distinct from the NTN on purpose: an NTN is
    # income tax registration and does not exempt a buyer from further tax, so
    # a shop that treats the two as the same under-charges every such customer.
    strn: Mapped[str | None] = mapped_column(String(24), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # money
    opening_balance: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    opening_balance_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    balance: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False, index=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    credit_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_discount_percent: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    price_list: Mapped[str | None] = mapped_column(String(32), nullable=True)  # retail | wholesale | ...

    # rollups (denormalised for a fast list screen; recomputed by PartyService)
    total_sales: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    total_purchases: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    transaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_transaction_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    group: Mapped["PartyGroup | None"] = relationship(lazy="joined")

    @property
    def receivable(self) -> Decimal:
        return self.balance if self.balance > 0 else Decimal("0")

    @property
    def payable(self) -> Decimal:
        return -self.balance if self.balance < 0 else Decimal("0")

    @property
    def is_over_credit_limit(self) -> bool:
        return bool(self.credit_limit is not None and self.receivable > self.credit_limit)

    @property
    def contact_number(self) -> str | None:
        return self.whatsapp or self.phone
