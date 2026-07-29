"""Shared Pydantic building blocks."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")

# Money/quantity aliases — everything stays Decimal, never float.
MoneyField = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]
QtyField = Annotated[Decimal, Field(max_digits=18, decimal_places=4)]
PercentField = Annotated[Decimal, Field(ge=0, le=100, max_digits=7, decimal_places=4)]


class ORMModel(BaseModel):
    """Base for anything read out of SQLAlchemy."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        ser_json_timedelta="float",
        arbitrary_types_allowed=True,
    )


class InputModel(BaseModel):
    """Base for request bodies — rejects unknown fields so typos surface early."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


class Message(BaseModel):
    message: str
    success: bool = True
    data: dict[str, Any] | None = None


class IdResponse(BaseModel):
    id: str
    message: str = "Saved."


class BulkResult(BaseModel):
    succeeded: int = 0
    failed: int = 0
    ids: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class DateRange(InputModel):
    start_date: date | None = None
    end_date: date | None = None

    @field_validator("end_date")
    @classmethod
    def _order(cls, v: date | None, info):
        start = info.data.get("start_date")
        if v and start and v < start:
            raise ValueError("end_date cannot be before start_date")
        return v


class SyncFields(BaseModel):
    """Fields an offline client sends with every write for idempotency."""

    client_uuid: str | None = Field(None, max_length=64)
    device_id: str | None = Field(None, max_length=64)


class Timestamped(BaseModel):
    created_at: datetime
    updated_at: datetime


class PageMeta(BaseModel):
    total: int
    page: int
    size: int
    pages: int
    has_next: bool
    has_prev: bool


class Paginated(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int
    has_next: bool
    has_prev: bool


class Trend(BaseModel):
    """A metric with its comparison against the previous period."""

    value: Decimal
    previous: Decimal | None = None
    change_percent: Decimal | None = None
    direction: str = "flat"  # up | down | flat


class SeriesPoint(BaseModel):
    label: str
    value: Decimal
    secondary: Decimal | None = None
    meta: dict[str, Any] | None = None
