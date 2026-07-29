"""Offline-first delta-sync payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.models.enums import SyncOperation
from app.schemas.common import InputModel, ORMModel

EntityName = Literal[
    "party", "party_group", "item", "item_category", "unit", "godown", "item_batch",
    "voucher", "payment", "expense", "expense_category", "tax_rate", "account",
]


class SyncChange(InputModel):
    """One local mutation the device made while offline."""

    entity: EntityName
    operation: SyncOperation = SyncOperation.CREATE
    client_uuid: str = Field(min_length=8, max_length=64)
    server_id: str | None = None
    # full record body; server validates it against the entity's create/update schema
    data: dict[str, Any] = Field(default_factory=dict)
    base_revision: int = 0
    client_updated_at: datetime | None = None


class SyncPushRequest(InputModel):
    device_id: str = Field(min_length=4, max_length=64)
    platform: str | None = None
    app_version: str | None = None
    changes: list[SyncChange] = Field(default_factory=list, max_length=500)


class SyncConflict(ORMModel):
    entity: str
    client_uuid: str
    server_id: str | None = None
    reason: str                       # stale_revision | validation | not_found | permission
    message: str
    server_revision: int | None = None
    server_data: dict[str, Any] | None = None


class SyncApplied(ORMModel):
    entity: str
    client_uuid: str
    server_id: str
    revision: int
    operation: str


class SyncPushResponse(ORMModel):
    applied: list[SyncApplied] = []
    conflicts: list[SyncConflict] = []
    server_seq: int = 0
    server_time: datetime


class SyncRecord(ORMModel):
    entity: str
    operation: str
    id: str
    revision: int
    seq: int
    data: dict[str, Any] | None = None
    updated_at: datetime | None = None


class SyncPullResponse(ORMModel):
    records: list[SyncRecord] = []
    server_seq: int = 0
    has_more: bool = False
    server_time: datetime
    # true when the device is too far behind and must re-download everything
    requires_full_sync: bool = False


class SyncStatusOut(ORMModel):
    device_id: str
    last_pulled_seq: int
    server_seq: int
    pending_pull: int
    last_pulled_at: datetime | None = None
    last_pushed_at: datetime | None = None
    conflicts: list[Any] = []


class BootstrapResponse(ORMModel):
    """Everything a fresh install needs in one shot."""

    business: dict[str, Any]
    settings: dict[str, Any]
    parties: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    units: list[dict[str, Any]] = []
    tax_rates: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    expense_categories: list[dict[str, Any]] = []
    server_seq: int = 0
    server_time: datetime
