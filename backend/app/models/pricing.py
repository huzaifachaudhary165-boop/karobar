"""Price lists and discount schemes — what a line on a bill actually costs."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID, Money, Quantity, TZDateTime
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)
from app.models.enums import DiscountType


class PriceList(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin,
                AuditedMixin):
    """A set of rates for a kind of customer.

    Thok and parchoon are genuinely different prices for the same sack of
    sugar, and a shop that sells both has been keying the wholesale rate by
    hand on every line. A list can name a rate per item, or move the whole
    catalogue by a percentage — most shops want the second and would never fill
    in the first.
    """

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_price_list_name"),
        UniqueConstraint("business_id", "client_uuid", name="uq_price_list_client_uuid"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # The blanket rule, applied to any item this list does not name.
    # Negative is a discount off the shop's own selling price, positive a markup.
    adjust_percent: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    # Which of the item's own prices the adjustment starts from.
    base_price: Mapped[str] = mapped_column(String(16), default="sale", nullable=False)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def has_blanket_rule(self) -> bool:
        return self.adjust_percent != 0 or self.base_price != "sale"


class PriceListEntry(Base, UUIDMixin, TenantMixin, TimestampMixin, SyncMixin):
    """One item's rate on one list. Overrides the list's blanket rule."""

    __table_args__ = (
        UniqueConstraint("business_id", "price_list_id", "item_id", name="uq_price_list_item"),
        Index("ix_price_entries_list", "business_id", "price_list_id"),
    )

    price_list_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    # Buying this many or more gets this rate. Null means it always applies.
    min_qty: Mapped[Decimal | None] = mapped_column(Quantity(), nullable=True)


class DiscountScheme(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin,
                     AuditedMixin):
    """A rule that takes something off a bill without anyone keying it.

    Deliberately narrow. Every extra condition is one more way for a shopkeeper
    to be unable to explain a total to the customer standing in front of them,
    and a discount nobody can explain is worse than no discount.
    """

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_discount_scheme_name"),
        Index("ix_schemes_active", "business_id", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # What it applies to: the whole bill, one item, or one category.
    scope: Mapped[str] = mapped_column(String(16), default="bill", nullable=False)
    item_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=True
    )
    category_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("item_categories.id", ondelete="CASCADE"), nullable=True
    )
    party_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("parties.id", ondelete="CASCADE"), nullable=True
    )
    price_list_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("price_lists.id", ondelete="CASCADE"), nullable=True
    )

    # When it fires.
    min_amount: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    min_qty: Mapped[Decimal | None] = mapped_column(Quantity(), nullable=True)

    # What it gives.
    discount_type: Mapped[str] = mapped_column(
        String(16), default=DiscountType.PERCENT, nullable=False
    )
    discount_value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    max_discount: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)

    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Highest first when two could apply, so the shop's own ordering wins
    # rather than whichever happened to be created first.
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    times_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    def runs_on(self, when: date) -> bool:
        if not self.is_active or self.is_deleted:
            return False
        if self.starts_on and when < self.starts_on:
            return False
        if self.ends_on and when > self.ends_on:
            return False
        return True
