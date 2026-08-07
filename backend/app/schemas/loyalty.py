"""Loyalty points."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import InputModel, MoneyField, ORMModel, QtyField


class ProgramUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    earn_rate: QtyField | None = Field(None, ge=0, le=1)
    point_value: MoneyField | None = Field(None, ge=0)
    min_bill_to_earn: MoneyField | None = Field(None, ge=0)
    min_points_to_redeem: int | None = Field(None, ge=0, le=100000)
    max_redeem_percent: MoneyField | None = Field(None, ge=0, le=100)
    expires_after_months: int | None = Field(None, ge=0, le=120)
    is_active: bool | None = None


class ProgramOut(ORMModel):
    id: str
    name: str
    earn_rate: Decimal
    point_value: Decimal
    min_bill_to_earn: Decimal | None = None
    min_points_to_redeem: int
    max_redeem_percent: Decimal
    expires_after_months: int | None = None
    is_active: bool

    # What the scheme costs, so a shopkeeper sees it before saving.
    cost_percent: Decimal = Decimal("0")
    summary: str = ""


class EntryOut(ORMModel):
    id: str
    party_id: str
    kind: str
    points: int
    balance_after: int
    value: Decimal
    voucher_id: str | None = None
    voucher_number: str | None = None
    note: str | None = None
    expires_on: date | None = None
    remaining: int = 0
    created_at: datetime


class BalanceOut(ORMModel):
    party_id: str
    party_name: str | None = None
    balance: int
    value: Decimal = Decimal("0")
    expiring_soon: int = 0
    next_expiry: date | None = None


class QuoteRequest(InputModel):
    party_id: str
    bill_total: MoneyField = Field(gt=0)


class QuoteOut(ORMModel):
    enabled: bool
    balance: int
    redeemable: int
    value: Decimal
    point_value: Decimal = Decimal("0")
    min_points: int = 0


class RedeemRequest(InputModel):
    party_id: str
    points: int = Field(gt=0)
    bill_total: MoneyField = Field(gt=0)
    voucher_id: str | None = None
    voucher_number: str | None = None


class AdjustRequest(InputModel):
    party_id: str
    points: int = Field(description="Signed: positive gives, negative takes away")
    note: str = Field(min_length=1, max_length=300)


class ExpiryRun(ORMModel):
    customers: int
    points: int
    checked_on: date


class TopCustomer(ORMModel):
    party_id: str
    party_name: str
    points: int
    value: Decimal = Decimal("0")
