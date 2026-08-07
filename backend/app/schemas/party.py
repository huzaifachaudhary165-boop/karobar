"""Party (customer/supplier) schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import EmailStr, Field, field_validator

from app.models.enums import PartyType
from app.schemas.common import InputModel, MoneyField, ORMModel, SyncFields
from app.utils.phone import clean_phone


class PartyBase(InputModel):
    name: str = Field(min_length=1, max_length=200)
    party_type: PartyType = PartyType.CUSTOMER
    group_id: str | None = None

    phone: str | None = Field(None, max_length=20)
    alternate_phone: str | None = Field(None, max_length=20)
    whatsapp: str | None = Field(None, max_length=20)
    email: EmailStr | None = None
    contact_person: str | None = Field(None, max_length=160)

    billing_address: str | None = None
    shipping_address: str | None = None
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=100)
    state_code: str | None = Field(None, max_length=8)
    pincode: str | None = Field(None, max_length=16)
    country: str | None = Field(None, max_length=64)

    gstin: str | None = Field(None, max_length=20)
    ntn: str | None = Field(None, max_length=20)
    # Sales tax registration, and deliberately not the same field as the NTN:
    # an NTN is income tax registration and does not exempt a buyer from
    # further tax. This is what decides whether it is charged.
    strn: str | None = Field(None, max_length=24)
    pan: str | None = Field(None, max_length=20)

    credit_limit: MoneyField | None = None
    credit_days: int | None = Field(None, ge=0, le=365)
    default_discount_percent: MoneyField | None = Field(None, ge=0, le=100)
    price_list: str | None = Field(None, max_length=32)

    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @field_validator("phone", "alternate_phone", "whatsapp")
    @classmethod
    def _phone(cls, v):
        return clean_phone(v)

    @field_validator("gstin", "ntn", "pan")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if v else None


class PartyCreate(PartyBase, SyncFields):
    opening_balance: MoneyField = Decimal("0")
    opening_balance_date: date | None = None


class PartyUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    party_type: PartyType | None = None
    group_id: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    whatsapp: str | None = None
    email: EmailStr | None = None
    contact_person: str | None = None
    billing_address: str | None = None
    shipping_address: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    country: str | None = None
    gstin: str | None = None
    ntn: str | None = None
    strn: str | None = None
    pan: str | None = None
    credit_limit: MoneyField | None = None
    credit_days: int | None = None
    default_discount_percent: MoneyField | None = None
    price_list: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    is_active: bool | None = None
    opening_balance: MoneyField | None = None
    opening_balance_date: date | None = None

    @field_validator("phone", "alternate_phone", "whatsapp")
    @classmethod
    def _phone(cls, v):
        return clean_phone(v)


class PartyOut(ORMModel):
    id: str
    business_id: str
    name: str
    party_type: str
    group_id: str | None = None
    group_name: str | None = None

    phone: str | None = None
    alternate_phone: str | None = None
    whatsapp: str | None = None
    email: str | None = None
    contact_person: str | None = None

    billing_address: str | None = None
    shipping_address: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    country: str | None = None

    gstin: str | None = None
    ntn: str | None = None
    strn: str | None = None
    pan: str | None = None

    opening_balance: Decimal
    opening_balance_date: date | None = None
    balance: Decimal
    receivable: Decimal = Decimal("0")
    payable: Decimal = Decimal("0")
    credit_limit: Decimal | None = None
    credit_days: int | None = None
    is_over_credit_limit: bool = False
    default_discount_percent: Decimal | None = None

    total_sales: Decimal
    total_purchases: Decimal
    transaction_count: int
    last_transaction_at: datetime | None = None

    notes: str | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    is_active: bool
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class PartyListItem(ORMModel):
    """Slim payload for the parties list â€” keeps the mobile list screen fast."""

    id: str
    name: str
    party_type: str
    phone: str | None = None
    balance: Decimal
    last_transaction_at: datetime | None = None
    is_over_credit_limit: bool = False


class PartyGroupCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    color: str | None = Field(None, max_length=16)
    default_credit_days: int | None = Field(None, ge=0, le=365)
    default_discount_percent: MoneyField | None = Field(None, ge=0, le=100)


class PartyGroupOut(ORMModel):
    id: str
    name: str
    description: str | None = None
    color: str | None = None
    default_credit_days: int | None = None
    default_discount_percent: Decimal | None = None
    party_count: int = 0
    created_at: datetime


class LedgerEntry(ORMModel):
    date: date
    entry_type: str            # sale | purchase | payment_in | payment_out | opening | return
    reference_id: str | None = None
    reference_number: str | None = None
    description: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")


class PartyLedger(ORMModel):
    party: PartyListItem
    opening_balance: Decimal
    closing_balance: Decimal
    total_debit: Decimal
    total_credit: Decimal
    entries: list[LedgerEntry]
    start_date: date | None = None
    end_date: date | None = None


class PartyStatement(ORMModel):
    """Aged receivable breakdown for one party."""

    party_id: str
    party_name: str
    total_outstanding: Decimal
    current: Decimal = Decimal("0")
    days_1_30: Decimal = Decimal("0")
    days_31_60: Decimal = Decimal("0")
    days_61_90: Decimal = Decimal("0")
    days_90_plus: Decimal = Decimal("0")
    oldest_due_date: date | None = None
    unpaid_invoice_count: int = 0
