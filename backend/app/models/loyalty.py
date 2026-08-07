"""Loyalty points: what a customer has earned and what they have spent."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID, Money, Quantity, TZDateTime
from app.models.base import (
    Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)


class LoyaltyProgram(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """One per shop: how points are earned and what they are worth.

    Two separate rates on purpose. A shop that gives one point per hundred
    rupees and lets a point buy one rupee is running a 1% scheme, and being
    able to say that out loud is what stops a shopkeeper accidentally giving
    away a tenth of their margin.
    """

    __table_args__ = (
        UniqueConstraint("business_id", name="uq_loyalty_program_business"),
    )

    name: Mapped[str] = mapped_column(String(80), default="Loyalty points", nullable=False)

    # Points earned per unit of currency spent. 0.01 is one point per hundred.
    earn_rate: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0.01"), nullable=False)
    # What one point takes off a bill.
    point_value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("1"), nullable=False)

    min_bill_to_earn: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    min_points_to_redeem: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # A cap on how much of one bill points may pay for, as a percentage.
    max_redeem_percent: Mapped[Decimal] = mapped_column(
        Money(), default=Decimal("100"), nullable=False
    )

    # Points go stale after this many months. Null means they never do.
    expires_after_months: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def scheme_percent(self) -> Decimal:
        """What the scheme actually costs, as a percentage of turnover."""
        return self.earn_rate * self.point_value * Decimal("100")


class LoyaltyEntry(Base, UUIDMixin, TenantMixin, TimestampMixin, SyncMixin):
    """One movement of points. Append-only, like the stock ledger.

    A balance on the party row would be a number nobody could account for. A
    customer who asks where their points went is asking for this list, and a
    shop that cannot produce it will be argued with and lose.
    """

    __table_args__ = (
        Index("ix_loyalty_party_date", "business_id", "party_id", "created_at"),
        Index("ix_loyalty_expiry", "business_id", "expires_on"),
    )

    party_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("parties.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # earned | redeemed | expired | adjusted | reversed
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Signed: positive adds points, negative takes them away.
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # What the points were worth when they were spent, so a later change to
    # point_value cannot rewrite what a customer was actually given.
    value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    voucher_id: Mapped[str | None] = mapped_column(GUID(), nullable=True, index=True)
    voucher_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Only set on an earning entry: when this particular lot goes stale.
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # How many of this lot are left after redemptions and expiry took from it.
    remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expired_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    created_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    @property
    def is_earning(self) -> bool:
        return self.points > 0
