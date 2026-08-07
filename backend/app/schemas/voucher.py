"""Invoice / voucher schemas — the heart of the API surface."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from app.models.enums import DiscountType, VoucherStatus, VoucherType
from app.schemas.common import InputModel, MoneyField, ORMModel, QtyField, SyncFields


class VoucherLineInput(InputModel):
    item_id: str | None = None
    item_name: str | None = Field(None, max_length=240)
    description: str | None = None
    hsn_code: str | None = Field(None, max_length=16)
    unit_label: str | None = Field(None, max_length=16)

    qty: QtyField = Field(Decimal("1"), gt=0)
    free_qty: QtyField = Decimal("0")
    rate: MoneyField = Field(Decimal("0"), ge=0)
    mrp: MoneyField | None = None
    cost_price: MoneyField | None = None

    discount_type: DiscountType = DiscountType.PERCENT
    discount_value: MoneyField = Field(Decimal("0"), ge=0)

    tax_rate: MoneyField | None = Field(None, ge=0, le=100)
    cess_rate: MoneyField = Field(Decimal("0"), ge=0, le=100)

    batch_id: str | None = None
    godown_id: str | None = None
    serial_numbers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _need_item_or_name(self):
        if not self.item_id and not self.item_name:
            raise ValueError("Each line needs an item_id or an item_name.")
        if self.discount_type == DiscountType.PERCENT and self.discount_value > 100:
            raise ValueError("Percentage discount cannot exceed 100.")
        return self


class VoucherLineOut(ORMModel):
    id: str
    position: int
    item_id: str | None = None
    item_name: str
    description: str | None = None
    hsn_code: str | None = None
    unit_label: str
    qty: Decimal
    free_qty: Decimal
    rate: Decimal
    mrp: Decimal | None = None
    cost_price: Decimal
    discount_type: str
    discount_value: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    tax_rate: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_rate: Decimal
    cess_amount: Decimal
    tax_amount: Decimal
    total: Decimal
    line_profit: Decimal
    batch_id: str | None = None
    serial_numbers: list[str] | None = None


class PaymentInline(InputModel):
    """Record a payment in the same call that creates the invoice — the common
    counter-sale flow where the customer pays immediately."""

    amount: MoneyField = Field(gt=0)
    mode: str = "cash"
    account_id: str | None = None
    reference_number: str | None = Field(None, max_length=80)
    payment_date: date | None = None
    notes: str | None = None


class VoucherCreate(InputModel, SyncFields):
    voucher_type: VoucherType = VoucherType.SALE
    number: str | None = Field(None, max_length=64, description="Auto-generated when omitted")
    voucher_date: date | None = None
    due_date: date | None = None
    reference_number: str | None = Field(None, max_length=64)

    party_id: str | None = None
    party_name: str | None = Field(None, max_length=200)
    party_phone: str | None = Field(None, max_length=20)
    billing_address: str | None = None
    shipping_address: str | None = None
    place_of_supply: str | None = Field(None, max_length=8)

    lines: list[VoucherLineInput] = Field(min_length=1)

    discount_type: DiscountType = DiscountType.AMOUNT
    discount_value: MoneyField = Field(Decimal("0"), ge=0)
    shipping_charge: MoneyField = Field(Decimal("0"), ge=0)
    packaging_charge: MoneyField = Field(Decimal("0"), ge=0)
    other_charge: MoneyField = Decimal("0")

    is_tax_inclusive: bool | None = None
    status: VoucherStatus | None = None

    notes: str | None = None
    terms: str | None = None
    transport_details: dict[str, Any] = Field(default_factory=dict)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    parent_voucher_id: str | None = None
    payment: PaymentInline | None = None
    source: str = Field("manual", pattern="^(manual|ai|ocr|import|api)$")

    @model_validator(mode="after")
    def _party_required_for_credit(self):
        vt = VoucherType(self.voucher_type)
        if vt.affects_ledger and not self.party_id and not self.party_name:
            raise ValueError("A party is required for this document type.")
        return self


class VoucherUpdate(InputModel):
    voucher_date: date | None = None
    due_date: date | None = None
    reference_number: str | None = None
    party_id: str | None = None
    party_name: str | None = None
    party_phone: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    place_of_supply: str | None = None
    lines: list[VoucherLineInput] | None = None
    discount_type: DiscountType | None = None
    discount_value: MoneyField | None = None
    shipping_charge: MoneyField | None = None
    packaging_charge: MoneyField | None = None
    other_charge: MoneyField | None = None
    is_tax_inclusive: bool | None = None
    status: VoucherStatus | None = None
    notes: str | None = None
    terms: str | None = None
    transport_details: dict[str, Any] | None = None
    custom_fields: dict[str, Any] | None = None


class VoucherOut(ORMModel):
    id: str
    business_id: str
    voucher_type: str
    number: str
    status: str
    voucher_date: date
    due_date: date | None = None
    reference_number: str | None = None

    party_id: str | None = None
    party_name: str | None = None
    party_phone: str | None = None
    party_gstin: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    place_of_supply: str | None = None

    subtotal: Decimal
    discount_type: str
    discount_value: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    cgst_amount: Decimal
    sgst_amount: Decimal
    igst_amount: Decimal
    cess_amount: Decimal
    tax_amount: Decimal
    shipping_charge: Decimal
    packaging_charge: Decimal
    other_charge: Decimal
    round_off: Decimal
    total: Decimal
    paid_amount: Decimal
    balance_amount: Decimal
    profit: Decimal

    is_tax_inclusive: bool
    is_interstate: bool
    is_overdue: bool = False
    days_overdue: int = 0
    # Document types this one may still be turned into — empty once it has been
    # converted or cancelled. The app builds its menu from exactly this list.
    convertible_to: list[str] = []

    notes: str | None = None
    terms: str | None = None
    transport_details: dict[str, Any] | None = None
    custom_fields: dict[str, Any] | None = None
    attachments: list[Any] | None = None

    parent_voucher_id: str | None = None
    source: str
    sent_at: datetime | None = None
    sent_channels: list[Any] | None = None
    pdf_url: str | None = None

    lines: list[VoucherLineOut] = []
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class VoucherListItem(ORMModel):
    id: str
    voucher_type: str
    number: str
    status: str
    voucher_date: date
    due_date: date | None = None
    party_id: str | None = None
    party_name: str | None = None
    total: Decimal
    paid_amount: Decimal
    balance_amount: Decimal
    is_overdue: bool = False
    item_count: int = 0
    source: str = "manual"


class VoucherFilters(InputModel):
    voucher_type: VoucherType | None = None
    status: VoucherStatus | None = None
    party_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    min_amount: MoneyField | None = None
    max_amount: MoneyField | None = None
    search: str | None = Field(None, max_length=120)
    only_overdue: bool = False
    only_unpaid: bool = False
    source: str | None = None


class ConvertRequest(InputModel):
    target_type: VoucherType = VoucherType.SALE
    voucher_date: date | None = None
    keep_original: bool = True


class ShareRequest(InputModel):
    channel: str = Field(pattern="^(whatsapp|email|sms|link)$")
    recipient: str | None = Field(None, max_length=255)
    message: str | None = Field(None, max_length=2000)
    attach_pdf: bool = True


class ShareResponse(ORMModel):
    success: bool
    channel: str
    recipient: str | None = None
    message_id: str | None = None
    share_url: str | None = None
    detail: str | None = None
