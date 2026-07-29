"""Liveness, readiness and build info."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Response, status

from app.ai.client import ai_client
from app.core.config import settings
from app.core.database import ping_db

router = APIRouter(tags=["health"])


@router.get("/health", summary="Basic health check")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness probe")
async def ready(response: Response) -> dict[str, object]:
    db_ok = await ping_db()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if db_ok else "degraded",
        "checks": {
            "database": "ok" if db_ok else "unreachable",
            "ai": "configured" if ai_client.available else "not_configured",
            "whatsapp": "configured" if settings.WHATSAPP_ENABLED else "not_configured",
            "email": "configured" if settings.SMTP_USER else "not_configured",
        },
    }
