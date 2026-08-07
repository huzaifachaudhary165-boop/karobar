"""Price lists, discount schemes and line quotes."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.models.enums import DiscountType
from app.schemas.common import InputModel, MoneyField, ORMModel, QtyField, SyncFields


# ── price lists ────────────────────────────────────────────────────
class PriceListCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(None, max_length=300)
    adjust_percent: MoneyField = Field(Decimal("0"), ge=-100, le=1000)
    base_price: str = Field("sale", pattern="^(sale|purchase|mrp|wholesale)$")
    is_default: bool = False
    is_active: bool = True


class PriceListUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = None
    adjust_percent: MoneyField | None = Field(None, ge=-100, le=1000)
    base_price: str | None = Field(None, pattern="^(sale|purchase|mrp|wholesale)$")
    is_default: bool | None = None
    is_active: bool | None = None


class PriceListOut(ORMModel):
    id: str
    name: str
    description: str | None = None
    adjust_percent: Decimal
    base_price: str
    is_default: bool
    is_active: bool
    item_count: int = 0
    created_at: datetime


class PriceEntryIn(InputModel):
    item_id: str
    price: MoneyField = Field(ge=0)
    min_qty: QtyField | None = Field(None, gt=0)


class PriceEntryOut(ORMModel):
    id: str
    item_id: str
    item_name: str
    sku: str | None = None
    unit_label: str = "Pcs"
    sale_price: Decimal
    price: Decimal
    min_qty: Decimal | None = None


# ── discount schemes ───────────────────────────────────────────────
class SchemeCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    scope: str = Field("bill", pattern="^(bill|item|category|party)$")

    item_id: str | None = None
    category_id: str | None = None
    party_id: str | None = None
    price_list_id: str | None = None

    min_amount: MoneyField | None = Field(None, ge=0)
    min_qty: QtyField | None = Field(None, gt=0)

    discount_type: DiscountType = DiscountType.PERCENT
    discount_value: MoneyField = Field(gt=0)
    max_discount: MoneyField | None = Field(None, gt=0)

    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool = True
    priority: int = Field(0, ge=0, le=1000)

    @model_validator(mode="after")
    def _sane(self):
        if self.discount_type == DiscountType.PERCENT and self.discount_value > 100:
            raise ValueError("A percentage discount cannot be more than 100%.")
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("The offer would end before it starts.")
        if self.scope == "item" and not self.item_id:
            raise ValueError("Choose the item this offer is on.")
        if self.scope == "category" and not self.category_id:
            raise ValueError("Choose the category this offer is on.")
        return self


class SchemeUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = None
    min_amount: MoneyField | None = Field(None, ge=0)
    min_qty: QtyField | None = Field(None, gt=0)
    discount_value: MoneyField | None = Field(None, gt=0)
    max_discount: MoneyField | None = Field(None, gt=0)
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool | None = None
    priority: int | None = Field(None, ge=0, le=1000)


class SchemeOut(ORMModel):
    id: str
    name: str
    description: str | None = None
    scope: str
    item_id: str | None = None
    category_id: str | None = None
    party_id: str | None = None
    price_list_id: str | None = None
    min_amount: Decimal | None = None
    min_qty: Decimal | None = None
    discount_type: str
    discount_value: Decimal
    max_discount: Decimal | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    is_active: bool
    priority: int
    times_used: int = 0
    is_running: bool = False
    created_at: datetime


# ── quoting a line ─────────────────────────────────────────────────
class QuoteLineIn(InputModel):
    item_id: str
    qty: QtyField = Field(Decimal("1"), gt=0)


class QuoteRequest(InputModel):
    lines: list[QuoteLineIn] = Field(min_length=1, max_length=200)
    party_id: str | None = None
    on_date: date | None = None


class QuoteLineOut(ORMModel):
    item_id: str
    qty: Decimal
    rate: Decimal
    line_total: Decimal
    discount: Decimal
    net: Decimal

    # Where the rate came from, so the bill screen can say so rather than
    # showing a number the shopkeeper cannot account for.
    source: str
    price_list_id: str | None = None
    price_list_name: str | None = None
    scheme_name: str | None = None
    held_at_minimum: bool = False
