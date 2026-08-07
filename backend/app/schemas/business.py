"""Business, membership and settings schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import EmailStr, Field, field_validator

from app.models.enums import BusinessType, TaxType
from app.schemas.common import InputModel, MoneyField, ORMModel
from app.utils.phone import clean_phone


class BusinessCreate(InputModel):
    name: str = Field(min_length=2, max_length=200)
    legal_name: str | None = Field(None, max_length=200)
    business_type: BusinessType = BusinessType.RETAIL
    description: str | None = None

    phone: str | None = None
    email: EmailStr | None = None
    website: str | None = Field(None, max_length=255)

    address_line1: str | None = Field(None, max_length=255)
    address_line2: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=100)
    state: str | None = Field(None, max_length=100)
    state_code: str | None = Field(None, max_length=8)
    pincode: str | None = Field(None, max_length=16)
    country: str = "Pakistan"

    tax_type: TaxType = TaxType.NONE
    gstin: str | None = Field(None, max_length=20)
    ntn: str | None = Field(None, max_length=20)
    strn: str | None = Field(None, max_length=20)
    pan: str | None = Field(None, max_length=20)
    is_composite: bool = False

    currency: str | None = Field(None, max_length=8)
    currency_symbol: str | None = Field(None, max_length=8)
    financial_year_start_month: int = Field(7, ge=1, le=12)
    book_start_date: date | None = None

    logo_url: str | None = None
    theme_color: str = "#F97316"

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return clean_phone(v)

    @field_validator("gstin", "ntn", "strn", "pan")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if v else None


class BusinessUpdate(InputModel):
    name: str | None = Field(None, min_length=2, max_length=200)
    legal_name: str | None = None
    business_type: BusinessType | None = None
    description: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    email: EmailStr | None = None
    website: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    country: str | None = None
    tax_type: TaxType | None = None
    gstin: str | None = None
    ntn: str | None = None
    strn: str | None = None
    pan: str | None = None
    is_composite: bool | None = None
    currency: str | None = None
    currency_symbol: str | None = None
    financial_year_start_month: int | None = Field(None, ge=1, le=12)
    book_start_date: date | None = None
    logo_url: str | None = None
    signature_url: str | None = None
    theme_color: str | None = None

    # This class had no validators at all, so the shop's own phone number was
    # never normalised — stored exactly as typed, unlike every party's — and
    # never length-checked, which is the same 500 waiting to happen. Editing
    # shop details is not a rarer path than adding a customer; it is just a
    # quieter one.
    @field_validator("phone", "alternate_phone")
    @classmethod
    def _phone(cls, v):
        return clean_phone(v)

    @field_validator("gstin", "ntn", "strn", "pan")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if v else None


class BusinessOut(ORMModel):
    id: str
    name: str
    legal_name: str | None = None
    business_type: str
    description: str | None = None
    phone: str | None = None
    alternate_phone: str | None = None
    email: str | None = None
    website: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    state_code: str | None = None
    pincode: str | None = None
    country: str
    logo_url: str | None = None
    signature_url: str | None = None
    theme_color: str
    tax_type: str
    gstin: str | None = None
    ntn: str | None = None
    strn: str | None = None
    pan: str | None = None
    is_composite: bool
    currency: str
    currency_symbol: str
    financial_year_start_month: int
    book_start_date: date | None = None
    plan: str
    plan_expires_at: datetime | None = None
    is_active: bool
    owner_id: str
    created_at: datetime
    # attached by the API layer for the calling user
    role: str | None = None
    member_count: int | None = None


class SettingsUpdate(InputModel):
    invoice_prefix: str | None = Field(None, max_length=16)
    purchase_prefix: str | None = Field(None, max_length=16)
    quotation_prefix: str | None = Field(None, max_length=16)
    payment_prefix: str | None = Field(None, max_length=16)
    number_padding: int | None = Field(None, ge=1, le=10)
    reset_numbering_yearly: bool | None = None

    default_due_days: int | None = Field(None, ge=0, le=365)
    prices_include_tax: bool | None = None
    allow_negative_stock: bool | None = None
    auto_round_off: bool | None = None
    show_hsn: bool | None = None
    enable_batches: bool | None = None
    enable_serial_numbers: bool | None = None
    enable_multi_godown: bool | None = None

    # Validated against the registry rather than by a pattern: a hard-coded
    # alternation meant adding a theme silently made it unsavable, which looks
    # from the outside like a picker that does not work.
    invoice_template: str | None = Field(None, max_length=32)
    print_size: str | None = Field(None, pattern="^(A4|A5|thermal58|thermal80)$")
    terms_and_conditions: str | None = None
    invoice_footer: str | None = None
    show_amount_in_words: bool | None = None
    show_qr_code: bool | None = None
    bank_details: dict[str, Any] | None = None

    payment_reminder_enabled: bool | None = None
    reminder_days_before: int | None = Field(None, ge=0, le=90)
    reminder_days_after: int | None = Field(None, ge=0, le=365)
    low_stock_alerts: bool | None = None
    daily_summary_enabled: bool | None = None

    whatsapp_enabled: bool | None = None
    email_enabled: bool | None = None
    sms_enabled: bool | None = None

    ai_enabled: bool | None = None
    ai_auto_confirm: bool | None = None
    ai_language: str | None = Field(None, pattern="^(auto|en|ur|hi)$")

    default_low_stock_qty: MoneyField | None = None
    extra: dict[str, Any] | None = None

    # ── Pakistani sales tax ────────────────────────────────────────
    fbr_enabled: bool | None = None
    sales_tax_rate: MoneyField | None = Field(None, ge=0, le=100)
    further_tax_enabled: bool | None = None
    further_tax_rate: MoneyField | None = Field(None, ge=0, le=100)
    withholding_enabled: bool | None = None
    withholding_rate: MoneyField | None = Field(None, ge=0, le=100)
    province: str | None = Field(
        None, pattern="^(punjab|sindh|kpk|balochistan|islamabad)$"
    )

    @field_validator("invoice_template")
    @classmethod
    def _known_theme(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.services.invoice_templates import TEMPLATES
        from app.services.invoice_themes import THEMES

        chosen = value.lower().strip()
        if chosen not in THEMES and chosen not in TEMPLATES:
            raise ValueError(f"'{value}' is not one of the invoice looks on offer.")
        return chosen


class InvoiceThemeOut(ORMModel):
    """One of the looks a shop can print in."""

    key: str
    name: str
    layout: str
    accent: str
    paper: str
    density: str
    is_roll: bool


class SettingsOut(ORMModel):
    id: str
    business_id: str
    invoice_prefix: str
    purchase_prefix: str
    quotation_prefix: str
    payment_prefix: str
    number_padding: int
    reset_numbering_yearly: bool
    default_due_days: int
    prices_include_tax: bool
    allow_negative_stock: bool
    auto_round_off: bool
    show_hsn: bool
    enable_batches: bool
    enable_serial_numbers: bool
    enable_multi_godown: bool

    fbr_enabled: bool = False
    sales_tax_rate: Decimal = Decimal("18")
    further_tax_enabled: bool = True
    further_tax_rate: Decimal = Decimal("3")
    withholding_enabled: bool = False
    withholding_rate: Decimal = Decimal("0")
    province: str | None = None

    invoice_template: str
    print_size: str
    terms_and_conditions: str | None = None
    invoice_footer: str | None = None
    show_amount_in_words: bool
    show_qr_code: bool
    bank_details: dict[str, Any] | None = None
    payment_reminder_enabled: bool
    reminder_days_before: int
    reminder_days_after: int
    low_stock_alerts: bool
    daily_summary_enabled: bool
    whatsapp_enabled: bool
    email_enabled: bool
    sms_enabled: bool
    ai_enabled: bool
    ai_auto_confirm: bool
    ai_language: str
    default_low_stock_qty: Decimal
    extra: dict[str, Any] | None = None


class MemberInvite(InputModel):
    email: EmailStr | None = None
    phone: str | None = None
    name: str | None = Field(None, max_length=160)
    role: str = Field("viewer", pattern="^(owner|admin|accountant|salesman|storekeeper|viewer)$")

    @field_validator("phone")
    @classmethod
    def _phone(cls, v):
        return clean_phone(v)


class MemberUpdate(InputModel):
    role: str | None = Field(None, pattern="^(owner|admin|accountant|salesman|storekeeper|viewer)$")
    is_active: bool | None = None


class MemberOut(ORMModel):
    id: str
    user_id: str
    business_id: str
    role: str
    is_active: bool
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    invite_accepted_at: datetime | None = None
    created_at: datetime
