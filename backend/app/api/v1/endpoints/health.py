"""Liveness, readiness and build info."""

from __future__ import annotations

import asyncio
import os
import socket
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Response, status
from sqlalchemy.engine import make_url

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


@router.get("/health/db", summary="Why the database is or is not reachable")
async def database_diagnostics(response: Response) -> dict[str, object]:
    """Reports each step of reaching the database separately.

    "The database is unreachable" is not actionable — DNS, TCP and the Postgres
    handshake fail for completely different reasons and are fixed in different
    places. This walks them in order and names the one that broke.
    Deliberately no credentials, no full DSN, no traceback: host and port only.

    Written after moving the function to a region that could not reach the
    pooler. Every request died after ~25 seconds and the platform reported only
    FUNCTION_INVOCATION_FAILED, so there was nothing to act on.
    """
    url = make_url(settings.DATABASE_URL)
    host, port = url.host or "", url.port or 5432
    steps: dict[str, object] = {}

    # 1. DNS, per family — a host that only answers on a family the sandbox
    #    cannot route is a hang, not an error.
    for family, label in ((socket.AF_INET, "ipv4"), (socket.AF_INET6, "ipv6")):
        started = time.perf_counter()
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, family=family, type=socket.SOCK_STREAM
            )
            steps[f"dns_{label}"] = {
                "ok": True,
                "ms": round((time.perf_counter() - started) * 1000),
                "addresses": sorted({i[4][0] for i in infos})[:4],
            }
        except Exception as exc:  # noqa: BLE001 — reporting, not handling
            steps[f"dns_{label}"] = {
                "ok": False,
                "ms": round((time.perf_counter() - started) * 1000),
                "error": type(exc).__name__,
            }

    # 2. A plain TCP connection, so a routing problem is told apart from a
    #    Postgres authentication or pooler problem.
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=settings.DB_CONNECT_TIMEOUT
        )
        writer.close()
        steps["tcp"] = {"ok": True, "ms": round((time.perf_counter() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        steps["tcp"] = {
            "ok": False,
            "ms": round((time.perf_counter() - started) * 1000),
            "error": type(exc).__name__,
            "detail": str(exc)[:160],
        }

    # 3. The real thing, through the configured engine.
    started = time.perf_counter()
    db_ok = await ping_db()
    steps["query"] = {"ok": db_ok, "ms": round((time.perf_counter() - started) * 1000)}

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "target": {"host": host, "port": port, "driver": url.drivername},
        "function_region": os.getenv("VERCEL_REGION") or os.getenv("AWS_REGION") or "unknown",
        "connect_timeout_s": settings.DB_CONNECT_TIMEOUT,
        "steps": steps,
    }


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
