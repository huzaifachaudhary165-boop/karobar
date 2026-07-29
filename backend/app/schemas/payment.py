"""Payment, allocation, account and expense schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from app.models.enums import PaymentDirection, PaymentMode
from app.schemas.common import InputModel, MoneyField, ORMModel, SyncFields


class AllocationInput(InputModel):
    voucher_id: str
    amount: MoneyField = Field(gt=0)


class PaymentCreate(InputModel, SyncFields):
    direction: PaymentDirection = PaymentDirection.IN
    number: str | None = Field(None, max_length=64)
    payment_date: date | None = None

    party_id: str | None = None
    party_name: str | None = Field(None, max_length=200)

    amount: MoneyField = Field(gt=0)
    discount_given: MoneyField = Field(Decimal("0"), ge=0)

    mode: PaymentMode = PaymentMode.CASH
    account_id: str | None = None
    reference_number: str | None = Field(None, max_length=80)
    cheque_date: date | None = None

    # Leave empty to auto-allocate oldest-invoice-first (FIFO), the behaviour
    # shopkeepers expect when they just say "received 5000 from Ahmed".
    allocations: list[AllocationInput] = Field(default_factory=list)
    auto_allocate: bool = True

    notes: str | None = None
    source: str = Field("manual", pattern="^(manual|ai|ocr|import|api)$")

    @model_validator(mode="after")
    def _allocations_within_amount(self):
        allocated = sum((a.amount for a in self.allocations), Decimal("0"))
        if allocated > self.amount + self.discount_given:
            raise ValueError("Allocated amount exceeds the payment amount.")
        return self


class PaymentUpdate(InputModel):
    payment_date: date | None = None
    amount: MoneyField | None = Field(None, gt=0)
    mode: PaymentMode | None = None
    account_id: str | None = None
    reference_number: str | None = None
    cheque_date: date | None = None
    cheque_status: str | None = Field(None, pattern="^(pending|cleared|bounced)$")
    notes: str | None = None
    allocations: list[AllocationInput] | None = None


class AllocationOut(ORMModel):
    id: str
    voucher_id: str
    voucher_number: str | None = None
    amount: Decimal


class PaymentOut(ORMModel):
    id: str
    business_id: str
    number: str
    direction: str
    payment_date: date
    party_id: str | None = None
    party_name: str | None = None
    amount: Decimal
    allocated_amount: Decimal
    unallocated_amount: Decimal
    discount_given: Decimal
    mode: str
    account_id: str | None = None
    account_name: str | None = None
    reference_number: str | None = None
    cheque_date: date | None = None
    cheque_status: str | None = None
    notes: str | None = None
    source: str
    allocations: list[AllocationOut] = []
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class PaymentListItem(ORMModel):
    id: str
    number: str
    direction: str
    payment_date: date
    party_id: str | None = None
    party_name: str | None = None
    amount: Decimal
    unallocated_amount: Decimal
    mode: str


class AccountCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=120)
    account_type: str = Field("cash", pattern="^(cash|bank|wallet)$")
    bank_name: str | None = Field(None, max_length=160)
    account_number: str | None = Field(None, max_length=64)
    iban: str | None = Field(None, max_length=40)
    ifsc: str | None = Field(None, max_length=20)
    branch: str | None = Field(None, max_length=160)
    upi_id: str | None = Field(None, max_length=80)
    opening_balance: MoneyField = Decimal("0")
    is_default: bool = False
    show_on_invoice: bool = False


class AccountOut(ORMModel):
    id: str
    name: str
    account_type: str
    bank_name: str | None = None
    account_number: str | None = None
    iban: str | None = None
    ifsc: str | None = None
    branch: str | None = None
    upi_id: str | None = None
    opening_balance: Decimal
    balance: Decimal
    is_default: bool
    is_active: bool
    show_on_invoice: bool


class ExpenseCreate(InputModel, SyncFields):
    number: str | None = Field(None, max_length=64)
    expense_date: date | None = None
    category_id: str | None = None
    category_name: str | None = Field(None, max_length=120)

    title: str = Field(min_length=1, max_length=240)
    description: str | None = None

    amount: MoneyField = Field(gt=0)
    tax_rate: MoneyField = Field(Decimal("0"), ge=0, le=100)
    is_tax_inclusive: bool = False
    input_tax_claimable: bool = False

    party_id: str | None = None
    vendor_name: str | None = Field(None, max_length=200)

    payment_mode: PaymentMode = PaymentMode.CASH
    account_id: str | None = None
    is_paid: bool = True
    reference_number: str | None = Field(None, max_length=80)

    is_recurring: bool = False
    recurrence: str | None = Field(None, pattern="^(weekly|monthly|quarterly|yearly)$")
    next_due_date: date | None = None

    receipt_url: str | None = None
    source: str = Field("manual", pattern="^(manual|ai|ocr|import|api)$")


class ExpenseUpdate(InputModel):
    expense_date: date | None = None
    category_id: str | None = None
    title: str | None = None
    description: str | None = None
    amount: MoneyField | None = Field(None, gt=0)
    tax_rate: MoneyField | None = None
    is_tax_inclusive: bool | None = None
    input_tax_claimable: bool | None = None
    party_id: str | None = None
    vendor_name: str | None = None
    payment_mode: PaymentMode | None = None
    account_id: str | None = None
    is_paid: bool | None = None
    reference_number: str | None = None
    receipt_url: str | None = None


class ExpenseOut(ORMModel):
    id: str
    business_id: str
    number: str
    expense_date: date
    category_id: str | None = None
    category_name: str | None = None
    title: str
    description: str | None = None
    amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    total: Decimal
    is_tax_inclusive: bool
    input_tax_claimable: bool
    party_id: str | None = None
    vendor_name: str | None = None
    payment_mode: str
    account_id: str | None = None
    is_paid: bool
    reference_number: str | None = None
    is_recurring: bool
    recurrence: str | None = None
    next_due_date: date | None = None
    receipt_url: str | None = None
    source: str
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class ExpenseCategoryCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    icon: str | None = Field(None, max_length=48)
    color: str | None = Field(None, max_length=16)
    is_direct_cost: bool = False
    monthly_budget: MoneyField | None = None
    sort_order: int = 0


class ExpenseCategoryOut(ORMModel):
    id: str
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    is_direct_cost: bool
    monthly_budget: Decimal | None = None
    spent_this_month: Decimal = Decimal("0")
    expense_count: int = 0


class TaxRateCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=60)
    tax_type: str = "gst"
    rate: MoneyField = Field(Decimal("0"), ge=0, le=100)
    cgst_rate: MoneyField = Decimal("0")
    sgst_rate: MoneyField = Decimal("0")
    igst_rate: MoneyField = Decimal("0")
    cess_rate: MoneyField = Decimal("0")
    is_default: bool = False


class TaxRateOut(ORMModel):
    id: str
    name: str
    tax_type: str
    rate: Decimal
    cgst_rate: Decimal
    sgst_rate: Decimal
    igst_rate: Decimal
    cess_rate: Decimal
    is_default: bool
    is_active: bool


class SettleRequest(InputModel):
    """'Ahmed ne 5000 diye' — settle against outstanding invoices, oldest first."""

    party_id: str
    amount: MoneyField = Field(gt=0)
    direction: PaymentDirection = PaymentDirection.IN
    mode: PaymentMode = PaymentMode.CASH
    account_id: str | None = None
    payment_date: date | None = None
    notes: str | None = None
    discount_given: MoneyField = Decimal("0")


class SettleResult(ORMModel):
    payment: PaymentOut
    settled_vouchers: list[dict[str, Any]] = []
    remaining_credit: Decimal = Decimal("0")
    party_balance_after: Decimal = Decimal("0")
