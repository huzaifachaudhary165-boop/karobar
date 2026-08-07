"""Recipes and production runs."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import InputModel, MoneyField, ORMModel, QtyField, SyncFields


class ComponentIn(InputModel):
    item_id: str
    qty: QtyField = Field(gt=0)
    note: str | None = Field(None, max_length=200)


class ComponentOut(ORMModel):
    id: str
    item_id: str
    item_name: str = ""
    unit_label: str = "Pcs"
    qty: Decimal
    rate: Decimal = Decimal("0")
    available: Decimal | None = None
    note: str | None = None


class BomCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=120)
    item_id: str
    output_qty: QtyField = Field(Decimal("1"), gt=0)
    components: list[ComponentIn] = Field(min_length=1, max_length=100)

    labour_cost: MoneyField = Field(Decimal("0"), ge=0)
    overhead_cost: MoneyField = Field(Decimal("0"), ge=0)
    wastage_percent: MoneyField = Field(Decimal("0"), ge=0, le=100)
    notes: str | None = None
    is_active: bool = True


class BomUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    output_qty: QtyField | None = Field(None, gt=0)
    components: list[ComponentIn] | None = Field(None, min_length=1, max_length=100)
    labour_cost: MoneyField | None = Field(None, ge=0)
    overhead_cost: MoneyField | None = Field(None, ge=0)
    wastage_percent: MoneyField | None = Field(None, ge=0, le=100)
    notes: str | None = None
    is_active: bool | None = None


class BomOut(ORMModel):
    id: str
    name: str
    item_id: str
    item_name: str = ""
    output_qty: Decimal
    labour_cost: Decimal
    overhead_cost: Decimal
    wastage_percent: Decimal
    notes: str | None = None
    is_active: bool

    components: list[ComponentOut] = []
    # Worked out from today's costs and today's stock.
    unit_cost: Decimal = Decimal("0")
    batch_cost: Decimal = Decimal("0")
    can_make: Decimal = Decimal("0")
    created_at: datetime


class ShortageOut(ORMModel):
    item_id: str
    item_name: str
    needed: Decimal
    available: Decimal | None = None
    short_by: Decimal = Decimal("0")


class CostingOut(ORMModel):
    making: Decimal
    material_cost: Decimal
    labour_cost: Decimal
    overhead_cost: Decimal
    wastage_cost: Decimal
    total_cost: Decimal
    unit_cost: Decimal
    requirements: list[ShortageOut] = []
    shortages: list[ShortageOut] = []
    can_make_now: bool = True


class RunCreate(InputModel, SyncFields):
    bom_id: str
    qty: QtyField = Field(gt=0)
    run_date: date | None = None
    godown_id: str | None = None
    notes: str | None = None


class ConsumedOut(ORMModel):
    item_id: str
    item_name: str
    qty: Decimal
    rate: Decimal
    value: Decimal


class RunOut(ORMModel):
    id: str
    number: str
    bom_id: str | None = None
    item_id: str
    item_name: str
    run_date: date
    qty: Decimal

    material_cost: Decimal
    labour_cost: Decimal
    overhead_cost: Decimal
    wastage_cost: Decimal
    total_cost: Decimal
    unit_cost: Decimal

    godown_id: str | None = None
    notes: str | None = None
    consumed: list[ConsumedOut] = []
    created_at: datetime


class ProductionSummary(ORMModel):
    runs: int
    units_made: Decimal
    material_cost: Decimal
    labour_cost: Decimal
    wastage_cost: Decimal
    total_cost: Decimal
