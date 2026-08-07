"""Repeating bills."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.schemas.common import InputModel, MoneyField, ORMModel, QtyField, SyncFields

FREQUENCY = "^(daily|weekly|monthly|quarterly|half_yearly|yearly)$"


class RecurringLineIn(InputModel):
    item_id: str | None = None
    item_name: str = Field(min_length=1, max_length=240)
    qty: QtyField = Field(Decimal("1"), gt=0)
    rate: MoneyField = Field(Decimal("0"), ge=0)
    tax_rate: MoneyField = Field(Decimal("0"), ge=0, le=100)


class RecurringCreate(InputModel, SyncFields):
    name: str = Field(min_length=1, max_length=120)
    voucher_type: str = Field("sale", pattern="^(sale|purchase)$")
    party_id: str | None = None
    lines: list[RecurringLineIn] = Field(min_length=1, max_length=100)
    notes: str | None = None

    frequency: str = Field("monthly", pattern=FREQUENCY)
    interval: int = Field(1, ge=1, le=24)

    starts_on: date | None = None
    ends_on: date | None = None
    max_occurrences: int | None = Field(None, ge=1, le=999)

    auto_create: bool = True
    is_active: bool = True

    @model_validator(mode="after")
    def _sane(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("The schedule would end before it starts.")
        return self


class RecurringUpdate(InputModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    lines: list[RecurringLineIn] | None = Field(None, min_length=1, max_length=100)
    notes: str | None = None
    frequency: str | None = Field(None, pattern=FREQUENCY)
    interval: int | None = Field(None, ge=1, le=24)
    ends_on: date | None = None
    max_occurrences: int | None = Field(None, ge=1, le=999)
    next_run_on: date | None = None
    auto_create: bool | None = None
    is_active: bool | None = None


class RecurringOut(ORMModel):
    id: str
    name: str
    voucher_type: str
    party_id: str | None = None
    party_name: str | None = None
    lines: list[dict] = []
    notes: str | None = None

    frequency: str
    interval: int
    schedule_label: str = ""

    starts_on: date
    ends_on: date | None = None
    max_occurrences: int | None = None

    next_run_on: date
    last_run_on: date | None = None
    occurrences: int
    total_billed: Decimal

    auto_create: bool
    is_active: bool
    is_due: bool = False
    is_finished: bool = False
    last_error: str | None = None
    created_at: datetime


class RaisedBill(ORMModel):
    id: str
    name: str
    voucher_id: str
    number: str
    total: Decimal
    voucher_date: date


class DueReminder(ORMModel):
    id: str
    name: str
    due_count: int
    next_run_on: date


class ScheduleProblem(ORMModel):
    id: str
    name: str
    reason: str


class RunResult(ORMModel):
    """What happened when the due schedules were looked at."""

    created: list[RaisedBill] = []
    reminders: list[DueReminder] = []
    problems: list[ScheduleProblem] = []
    checked_on: date
