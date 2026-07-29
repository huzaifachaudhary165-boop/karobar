"""Offline-first delta sync."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query

from app.api.deps import DbSession, Tenant
from app.core.errors import ValidationError
from app.schemas.sync import (
    BootstrapResponse, SyncPullResponse, SyncPushRequest, SyncPushResponse, SyncStatusOut,
)
from app.services.sync_service import SyncService

router = APIRouter(prefix="/sync", tags=["sync"])


def _device(header: str | None, body: str | None = None) -> str:
    device_id = body or header
    if not device_id:
        raise ValidationError(
            "A device id is required for sync. Send the X-Device-Id header.",
            details={"header": "X-Device-Id"},
        )
    return device_id


@router.post("/push", response_model=SyncPushResponse, summary="Upload offline changes")
async def push(payload: SyncPushRequest, tenant: Tenant, db: DbSession) -> SyncPushResponse:
    result = await SyncService(db, tenant.actor).push(
        payload.device_id,
        payload.changes,
        platform=payload.platform,
        app_version=payload.app_version,
    )
    return SyncPushResponse.model_validate(result)


@router.get("/pull", response_model=SyncPullResponse, summary="Download server changes")
async def pull(
    tenant: Tenant,
    db: DbSession,
    since: int = Query(0, ge=0, description="Last server_seq this device saw"),
    limit: int = Query(200, ge=1, le=500),
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> SyncPullResponse:
    result = await SyncService(db, tenant.actor).pull(_device(x_device_id), since=since, limit=limit)
    return SyncPullResponse.model_validate(result)


@router.get("/bootstrap", response_model=BootstrapResponse,
            summary="Full dataset for a fresh install")
async def bootstrap(
    tenant: Tenant,
    db: DbSession,
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> BootstrapResponse:
    result = await SyncService(db, tenant.actor).bootstrap(_device(x_device_id))
    return BootstrapResponse.model_validate(result)


@router.get("/status", response_model=SyncStatusOut, summary="How far behind this device is")
async def status(
    tenant: Tenant,
    db: DbSession,
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> SyncStatusOut:
    result = await SyncService(db, tenant.actor).status(_device(x_device_id))
    return SyncStatusOut.model_validate(result)
