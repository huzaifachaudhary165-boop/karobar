"""Business (tenant), its members and per-business settings."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, JSONType, LowerString, Money, TZDateTime
from app.models.base import Base, SoftDeleteMixin, SyncMixin, TimestampMixin, UUIDMixin
from app.models.enums import BusinessType, TaxType

if TYPE_CHECKING:
    from app.models.user import User


class Business(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin, SyncMixin):
    """The tenant boundary. Every other business row FKs to this."""

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    business_type: Mapped[str] = mapped_column(String(32), default=BusinessType.RETAIL, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # contact
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    alternate_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(LowerString(255), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # address
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state_code: Mapped[str | None] = mapped_column(String(8), nullable=True)   # GST place-of-supply
    pincode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    country: Mapped[str] = mapped_column(String(64), default="Pakistan", nullable=False)

    # branding
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    signature_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    theme_color: Mapped[str] = mapped_column(String(16), default="#F97316", nullable=False)

    # tax identity
    tax_type: Mapped[str] = mapped_column(String(16), default=TaxType.NONE, nullable=False)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)   # India
    ntn: Mapped[str | None] = mapped_column(String(20), nullable=True)     # Pakistan
    strn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_composite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # accounting
    currency: Mapped[str] = mapped_column(String(8), default="PKR", nullable=False)
    currency_symbol: Mapped[str] = mapped_column(String(8), default="Rs", nullable=False)
    financial_year_start_month: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    book_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    decimal_places: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # subscription
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    plan_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    owner_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    members: Mapped[list["BusinessMember"]] = relationship(
        back_populates="business", cascade="all, delete-orphan", lazy="selectin"
    )
    settings: Mapped["BusinessSettings"] = relationship(
        back_populates="business", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )

    @property
    def full_address(self) -> str:
        parts = [self.address_line1, self.address_line2, self.city, self.state, self.pincode, self.country]
        return ", ".join(p for p in parts if p)

    @property
    def tax_number(self) -> str | None:
        return self.gstin or self.ntn


class BusinessMember(Base, UUIDMixin, TimestampMixin):
    """User ↔ Business join carrying the role. This is where RBAC is anchored."""

    __table_args__ = (UniqueConstraint("business_id", "user_id", name="uq_member_business_user"),)

    business_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(24), default="viewer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    invited_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    invite_accepted_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    # optional per-member overrides on top of the role defaults
    extra_permissions: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class BusinessSettings(Base, UUIDMixin, TimestampMixin):
    """Everything a shopkeeper can toggle. One row per business."""

    __tablename__ = "business_settings"  # the auto-pluraliser would say "settingses"

    business_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )

    # invoice numbering
    invoice_prefix: Mapped[str] = mapped_column(String(16), default="INV-", nullable=False)
    purchase_prefix: Mapped[str] = mapped_column(String(16), default="PUR-", nullable=False)
    quotation_prefix: Mapped[str] = mapped_column(String(16), default="QTN-", nullable=False)
    payment_prefix: Mapped[str] = mapped_column(String(16), default="PAY-", nullable=False)
    number_padding: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    reset_numbering_yearly: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # invoice behaviour
    default_due_days: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_round_off: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_hsn: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enable_batches: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enable_serial_numbers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enable_multi_godown: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Pakistani sales tax (FBR) ──────────────────────────────────
    # Off by default and deliberately so: most small shops are not registered
    # for sales tax at all, and putting an output-tax column in front of one
    # is how they conclude the app is meant for somebody else.
    fbr_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # A setting, not a constant — the standard rate has moved between 16, 17
    # and 18 percent inside a decade.
    sales_tax_rate: Mapped[Decimal] = mapped_column(
        Money(), default=Decimal("18"), nullable=False
    )
    # Charged on top when the buyer has no STRN. The rule shops get assessed
    # for years later, with penalty, having never heard of it.
    further_tax_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    further_tax_rate: Mapped[Decimal] = mapped_column(
        Money(), default=Decimal("3"), nullable=False
    )
    withholding_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    withholding_rate: Mapped[Decimal] = mapped_column(
        Money(), default=Decimal("0"), nullable=False
    )
    # Which authority collects the services tax where the shop trades.
    province: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # print
    invoice_template: Mapped[str] = mapped_column(String(32), default="classic", nullable=False)
    print_size: Mapped[str] = mapped_column(String(16), default="A4", nullable=False)  # A4|A5|thermal58|thermal80
    terms_and_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    invoice_footer: Mapped[str | None] = mapped_column(Text, nullable=True)
    show_amount_in_words: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_qr_code: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bank_details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)

    # reminders / automation
    payment_reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reminder_days_before: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    reminder_days_after: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    low_stock_alerts: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    daily_summary_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # channels
    whatsapp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # AI
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_auto_confirm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_language: Mapped[str] = mapped_column(String(8), default="auto", nullable=False)
    ai_monthly_token_cap: Mapped[int] = mapped_column(Integer, default=2_000_000, nullable=False)

    # thresholds
    default_low_stock_qty: Mapped[Decimal] = mapped_column(Money(), default=Decimal("5"), nullable=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)

    business: Mapped["Business"] = relationship(back_populates="settings")
