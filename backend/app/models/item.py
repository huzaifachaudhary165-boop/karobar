"""Inventory: units, categories, items, batches, godowns and the stock ledger."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, JSONType, Money, Quantity, TZDateTime
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)
from app.models.enums import ItemType, StockMovement


class Unit(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """Measurement unit with optional conversion to a base unit (Box → 12 Pcs)."""

    __table_args__ = (UniqueConstraint("business_id", "short_name", name="uq_unit_short_name"),)

    name: Mapped[str] = mapped_column(String(60), nullable=False)
    short_name: Mapped[str] = mapped_column(String(16), nullable=False)
    base_unit_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("units.id", ondelete="SET NULL"), nullable=True
    )
    conversion_factor: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("1"), nullable=False)
    allow_decimal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ItemCategory(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    __table_args__ = (UniqueConstraint("business_id", "name", "parent_id", name="uq_category_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("item_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(48), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Godown(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """Warehouse / shop location for multi-location stock."""

    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_godown_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Item(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, AuditedMixin):
    """A product or a service. `stock_qty` is the live on-hand figure maintained by StockService."""

    __table_args__ = (
        Index("ix_items_biz_name", "business_id", "name"),
        Index("ix_items_biz_sku", "business_id", "sku"),
        Index("ix_items_biz_barcode", "business_id", "barcode"),
        Index("ix_items_biz_active", "business_id", "is_active", "is_deleted"),
        UniqueConstraint("business_id", "client_uuid", name="uq_item_client_uuid"),
    )

    name: Mapped[str] = mapped_column(String(240), nullable=False)
    item_type: Mapped[str] = mapped_column(String(16), default=ItemType.PRODUCT, nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    category_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("item_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    unit_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("units.id", ondelete="SET NULL"), nullable=True
    )
    unit_label: Mapped[str] = mapped_column(String(16), default="Pcs", nullable=False)

    # pricing (all tax-exclusive unless prices_include_tax is on)
    sale_price: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    purchase_price: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    mrp: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    wholesale_price: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    min_sale_price: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    price_includes_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # tax
    tax_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    tax_rate_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("tax_rates.id", ondelete="SET NULL"), nullable=True
    )
    is_tax_exempt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cess_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    # stock
    track_inventory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stock_qty: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"), nullable=False, index=True)
    opening_stock: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"), nullable=False)
    opening_stock_value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    opening_stock_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    low_stock_qty: Mapped[Decimal | None] = mapped_column(Quantity(), nullable=True)
    reorder_qty: Mapped[Decimal | None] = mapped_column(Quantity(), nullable=True)
    # weighted-average cost, recomputed on every purchase
    avg_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    # batching / expiry (pharmacy, FMCG)
    track_batches: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    track_expiry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    track_serial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # rollups
    total_sold_qty: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"), nullable=False)
    total_sold_value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    last_sold_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_purchased_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tags: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)

    category: Mapped["ItemCategory | None"] = relationship(lazy="joined")

    @property
    def is_low_stock(self) -> bool:
        if not self.track_inventory or self.low_stock_qty is None:
            return False
        return self.stock_qty <= self.low_stock_qty

    @property
    def stock_value(self) -> Decimal:
        return (self.avg_cost or self.purchase_price) * self.stock_qty

    @property
    def margin_percent(self) -> Decimal | None:
        cost = self.avg_cost or self.purchase_price
        if not cost:
            return None
        return (self.sale_price - cost) / cost * Decimal("100")


class ItemBatch(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    __table_args__ = (
        Index("ix_batches_item_expiry", "item_id", "expiry_date"),
        UniqueConstraint("business_id", "item_id", "batch_number", name="uq_batch_number"),
    )

    item_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_number: Mapped[str] = mapped_column(String(64), nullable=False)
    manufacture_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    qty: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"), nullable=False)
    purchase_price: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    sale_price: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    mrp: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    godown_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("godowns.id", ondelete="SET NULL"), nullable=True
    )

    @property
    def is_expired(self) -> bool:
        return bool(self.expiry_date and self.expiry_date < date.today())

    def days_to_expiry(self) -> int | None:
        return (self.expiry_date - date.today()).days if self.expiry_date else None


class StockLedgerEntry(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Append-only stock movement log. Item.stock_qty must always equal the sum here."""

    __table_args__ = (
        Index("ix_stock_ledger_item_date", "item_id", "entry_date"),
        Index("ix_stock_ledger_ref", "reference_type", "reference_id"),
    )

    item_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("item_batches.id", ondelete="SET NULL"), nullable=True
    )
    godown_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("godowns.id", ondelete="SET NULL"), nullable=True
    )

    movement: Mapped[str] = mapped_column(String(16), nullable=False)  # StockMovement
    qty: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)          # signed: +in / -out
    balance_after: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    entry_date: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False, index=True)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # voucher | adjustment
    reference_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    party_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("parties.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    @property
    def direction(self) -> str:
        return StockMovement.IN if self.qty >= 0 else StockMovement.OUT
