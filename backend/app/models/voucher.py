"""Trade documents — sale, purchase, returns, quotations, challans, orders.

All of them share one table discriminated by `voucher_type`; the behavioural
differences (stock direction, ledger sign, numbering series) live on the enum
and in VoucherService, not in separate tables.
"""

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
from app.models.enums import DiscountType, VoucherStatus, VoucherType


class Voucher(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, SyncMixin, AuditedMixin):
    __table_args__ = (
        UniqueConstraint("business_id", "voucher_type", "number", name="uq_voucher_number"),
        UniqueConstraint("business_id", "client_uuid", name="uq_voucher_client_uuid"),
        Index("ix_vouchers_biz_type_date", "business_id", "voucher_type", "voucher_date"),
        Index("ix_vouchers_biz_party", "business_id", "party_id"),
        Index("ix_vouchers_biz_status", "business_id", "status", "is_deleted"),
        Index("ix_vouchers_due", "business_id", "due_date", "status"),
    )

    voucher_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=VoucherStatus.UNPAID, nullable=False)

    voucher_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(64), nullable=True)  # supplier's bill no.

    # party
    party_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("parties.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    party_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # snapshot for walk-ins
    party_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    party_gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_of_supply: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # ── money (every figure is stored, never recomputed on read) ──
    subtotal: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    discount_type: Mapped[str] = mapped_column(String(12), default=DiscountType.AMOUNT, nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    taxable_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    cgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    cess_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    shipping_charge: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    packaging_charge: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    other_charge: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    round_off: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    total: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False, index=True)
    paid_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    balance_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False, index=True)
    profit: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    is_tax_inclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_interstate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # extras
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)
    transport_details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)

    # linkage
    parent_voucher_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("vouchers.id", ondelete="SET NULL"), nullable=True, index=True
    )  # return → original invoice, invoice → quotation
    converted_to_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    # provenance — tells the UI this came from the assistant or a scanned bill
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)  # manual|ai|ocr|import|api
    ocr_job_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    # delivery state
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    sent_channels: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)
    viewed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    lines: Mapped[list["VoucherLine"]] = relationship(
        back_populates="voucher",
        cascade="all, delete-orphan",
        order_by="VoucherLine.position",
        lazy="selectin",
    )

    # ── derived ──────────────────────────────────────────────────
    @property
    def type_enum(self) -> VoucherType:
        return VoucherType(self.voucher_type)

    @property
    def is_paid(self) -> bool:
        return self.balance_amount <= Decimal("0.005")

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.due_date
            and not self.is_paid
            and self.status not in (VoucherStatus.CANCELLED, VoucherStatus.DRAFT)
            and self.due_date < date.today()
        )

    @property
    def days_overdue(self) -> int:
        return (date.today() - self.due_date).days if self.is_overdue and self.due_date else 0

    def compute_status(self) -> str:
        if self.status in (VoucherStatus.CANCELLED, VoucherStatus.DRAFT, VoucherStatus.CONVERTED):
            return self.status
        if not self.type_enum.affects_ledger:
            return VoucherStatus.PAID
        if self.is_paid:
            return VoucherStatus.PAID
        if self.paid_amount > 0:
            return VoucherStatus.OVERDUE if self.is_overdue else VoucherStatus.PARTIAL
        return VoucherStatus.OVERDUE if self.is_overdue else VoucherStatus.UNPAID


class VoucherLine(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """One row of an invoice. Item details are snapshotted so history never mutates."""

    __table_args__ = (Index("ix_voucher_lines_item", "item_id", "created_at"),)

    voucher_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("vouchers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    item_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("item_batches.id", ondelete="SET NULL"), nullable=True
    )
    godown_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    # snapshot
    item_name: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    hsn_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unit_label: Mapped[str] = mapped_column(String(16), default="Pcs", nullable=False)

    qty: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("1"), nullable=False)
    free_qty: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    mrp: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    cost_price: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    discount_type: Mapped[str] = mapped_column(String(12), default=DiscountType.PERCENT, nullable=False)
    discount_value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    taxable_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    cgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    sgst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    igst_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    cess_rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    cess_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    total: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    line_profit: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    serial_numbers: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)

    voucher: Mapped["Voucher"] = relationship(back_populates="lines")

    @property
    def gross(self) -> Decimal:
        return self.qty * self.rate
