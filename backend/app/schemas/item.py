"""Item, category, unit, batch and stock schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from app.models.enums import ItemType, StockMovement
from app.schemas.common import InputModel, MoneyField, ORMModel, QtyField, SyncFields


class ItemBase(InputModel):
    name: str = Field(min_length=1, max_length=240)
    item_type: ItemType = ItemType.PRODUCT
    sku: str | None = Field(None, max_length=64)
    barcode: str | None = Field(None, max_length=64)
    hsn_code: str | None = Field(None, max_length=16)
    description: str | None = None
    image_url: str | None = Field(None, max_length=500)

    category_id: str | None = None
    unit_id: str | None = None
    unit_label: str = Field("Pcs", max_length=16)

    sale_price: MoneyField = Decimal("0")
    purchase_price: MoneyField = Decimal("0")
    mrp: MoneyField | None = None
    wholesale_price: MoneyField | None = None
    min_sale_price: MoneyField | None = None
    price_includes_tax: bool = False

    tax_rate: MoneyField = Decimal("0")
    tax_rate_id: str | None = None
    is_tax_exempt: bool = False
    cess_rate: MoneyField = Decimal("0")

    track_inventory: bool = True
    low_stock_qty: QtyField | None = None
    reorder_qty: QtyField | None = None
    track_batches: bool = False
    track_expiry: bool = False
    track_serial: bool = False

    tags: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _service_has_no_stock(self):
        if self.item_type == ItemType.SERVICE:
            self.track_inventory = False
            self.track_batches = False
        return self


class ItemCreate(ItemBase, SyncFields):
    opening_stock: QtyField = Decimal("0")
    opening_stock_value: MoneyField = Decimal("0")
    opening_stock_date: date | None = None


class ItemUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=240)
    item_type: ItemType | None = None
    sku: str | None = None
    barcode: str | None = None
    hsn_code: str | None = None
    description: str | None = None
    image_url: str | None = None
    category_id: str | None = None
    unit_id: str | None = None
    unit_label: str | None = None
    sale_price: MoneyField | None = None
    purchase_price: MoneyField | None = None
    mrp: MoneyField | None = None
    wholesale_price: MoneyField | None = None
    min_sale_price: MoneyField | None = None
    price_includes_tax: bool | None = None
    tax_rate: MoneyField | None = None
    tax_rate_id: str | None = None
    is_tax_exempt: bool | None = None
    cess_rate: MoneyField | None = None
    track_inventory: bool | None = None
    low_stock_qty: QtyField | None = None
    reorder_qty: QtyField | None = None
    track_batches: bool | None = None
    track_expiry: bool | None = None
    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    is_active: bool | None = None


class ItemOut(ORMModel):
    id: str
    business_id: str
    name: str
    item_type: str
    sku: str | None = None
    barcode: str | None = None
    hsn_code: str | None = None
    description: str | None = None
    image_url: str | None = None

    category_id: str | None = None
    category_name: str | None = None
    unit_id: str | None = None
    unit_label: str

    sale_price: Decimal
    purchase_price: Decimal
    mrp: Decimal | None = None
    wholesale_price: Decimal | None = None
    min_sale_price: Decimal | None = None
    price_includes_tax: bool
    avg_cost: Decimal

    tax_rate: Decimal
    is_tax_exempt: bool
    cess_rate: Decimal

    track_inventory: bool
    stock_qty: Decimal
    opening_stock: Decimal
    low_stock_qty: Decimal | None = None
    reorder_qty: Decimal | None = None
    is_low_stock: bool = False
    stock_value: Decimal = Decimal("0")
    margin_percent: Decimal | None = None

    track_batches: bool
    track_expiry: bool
    track_serial: bool

    total_sold_qty: Decimal
    total_sold_value: Decimal
    last_sold_at: datetime | None = None
    last_purchased_at: datetime | None = None

    tags: list[str] | None = None
    custom_fields: dict[str, Any] | None = None
    is_active: bool
    revision: int = 1
    created_at: datetime
    updated_at: datetime


class ItemListItem(ORMModel):
    id: str
    name: str
    sku: str | None = None
    barcode: str | None = None
    unit_label: str
    sale_price: Decimal
    purchase_price: Decimal
    stock_qty: Decimal
    tax_rate: Decimal
    track_inventory: bool
    is_low_stock: bool = False
    image_url: str | None = None


class CategoryCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=120)
    parent_id: str | None = None
    description: str | None = None
    color: str | None = Field(None, max_length=16)
    icon: str | None = Field(None, max_length=48)
    sort_order: int = 0


class CategoryOut(ORMModel):
    id: str
    name: str
    parent_id: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None
    sort_order: int
    item_count: int = 0
    created_at: datetime


class UnitCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=60)
    short_name: str = Field(min_length=1, max_length=16)
    base_unit_id: str | None = None
    conversion_factor: QtyField = Decimal("1")
    allow_decimal: bool = True


class UnitOut(ORMModel):
    id: str
    name: str
    short_name: str
    base_unit_id: str | None = None
    conversion_factor: Decimal
    allow_decimal: bool


class BatchCreate(InputModel, SyncFields):
    item_id: str
    batch_number: str = Field(min_length=1, max_length=64)
    manufacture_date: date | None = None
    expiry_date: date | None = None
    qty: QtyField = Decimal("0")
    purchase_price: MoneyField | None = None
    sale_price: MoneyField | None = None
    mrp: MoneyField | None = None
    godown_id: str | None = None


class BatchOut(ORMModel):
    id: str
    item_id: str
    batch_number: str
    manufacture_date: date | None = None
    expiry_date: date | None = None
    qty: Decimal
    purchase_price: Decimal | None = None
    sale_price: Decimal | None = None
    mrp: Decimal | None = None
    is_expired: bool = False
    days_to_expiry: int | None = None


class BatchUpdate(InputModel):
    batch_number: str | None = Field(None, min_length=1, max_length=64)
    manufacture_date: date | None = None
    expiry_date: date | None = None
    purchase_price: MoneyField | None = None
    sale_price: MoneyField | None = None
    mrp: MoneyField | None = None
    godown_id: str | None = None


class BatchAllocation(ORMModel):
    batch_id: str
    batch_number: str
    expiry_date: date | None = None
    qty: Decimal
    available: Decimal


class ExpiringBatch(ORMModel):
    batch: BatchOut
    item_id: str
    item_name: str
    unit_label: str
    value: Decimal
    days_to_expiry: int | None = None


# ── locations ──────────────────────────────────────────────────────
class GodownCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=120)
    address: str | None = None
    is_default: bool = False


class GodownUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    address: str | None = None
    is_default: bool | None = None


class GodownOut(ORMModel):
    id: str
    name: str
    address: str | None = None
    is_default: bool
    item_count: int = 0
    stock_value: Decimal = Decimal("0")
    created_at: datetime


class GodownStockRow(ORMModel):
    item_id: str
    item_name: str
    sku: str | None = None
    unit_label: str
    qty: Decimal
    value: Decimal


class ItemGodownRow(ORMModel):
    godown_id: str
    godown_name: str
    is_default: bool
    qty: Decimal


class StockTransfer(InputModel):
    item_id: str
    from_godown_id: str
    to_godown_id: str
    qty: QtyField = Field(gt=0, description="How much to move — always positive")
    batch_id: str | None = None
    note: str | None = Field(None, max_length=300)
    entry_date: date | None = None

    @model_validator(mode="after")
    def _different_locations(self):
        if self.from_godown_id == self.to_godown_id:
            raise ValueError("Pick two different locations to transfer between.")
        return self


class TransferResult(ORMModel):
    item_id: str
    item_name: str
    qty: Decimal
    from_godown_id: str
    from_qty_after: Decimal
    to_godown_id: str
    to_qty_after: Decimal


# ── serial numbers ─────────────────────────────────────────────────
class SerialAdd(InputModel):
    item_id: str
    serials: list[str] = Field(min_length=1, max_length=500)
    godown_id: str | None = None
    batch_id: str | None = None
    purchase_price: MoneyField | None = None
    warranty_months: int | None = Field(None, ge=0, le=600)
    purchase_voucher_id: str | None = None
    received_on: date | None = None


class SerialOut(ORMModel):
    id: str
    item_id: str
    serial_number: str
    status: str
    batch_id: str | None = None
    godown_id: str | None = None
    purchase_price: Decimal | None = None
    sale_price: Decimal | None = None
    warranty_months: int | None = None
    warranty_until: date | None = None
    in_warranty: bool = False
    sold_at: datetime | None = None
    purchase_voucher_id: str | None = None
    sale_voucher_id: str | None = None
    note: str | None = None


class SerialAddResult(ORMModel):
    added: list[SerialOut] = []
    duplicates: list[str] = []
    added_count: int = 0
    available_count: int = 0


class SerialLookupOut(ORMModel):
    serial: SerialOut
    item_id: str
    item_name: str
    sku: str | None = None


class StockAdjustment(InputModel):
    item_id: str
    qty: QtyField = Field(description="Signed: positive adds stock, negative removes it")
    movement: StockMovement = StockMovement.ADJUSTMENT
    rate: MoneyField | None = None
    reason: str | None = Field(None, max_length=300)
    batch_id: str | None = None
    godown_id: str | None = None
    entry_date: date | None = None

    @model_validator(mode="after")
    def _non_zero(self):
        if self.qty == 0:
            raise ValueError("Adjustment quantity cannot be zero.")
        return self


class StockLedgerOut(ORMModel):
    id: str
    item_id: str
    item_name: str | None = None
    movement: str
    qty: Decimal
    balance_after: Decimal
    rate: Decimal
    value: Decimal
    entry_date: datetime
    reference_type: str | None = None
    reference_id: str | None = None
    reference_number: str | None = None
    party_id: str | None = None
    note: str | None = None


class StockSummary(ORMModel):
    total_items: int
    total_stock_value: Decimal
    low_stock_count: int
    out_of_stock_count: int
    expiring_soon_count: int = 0
    top_value_items: list[ItemListItem] = []
