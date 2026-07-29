"""Request-id, timing, security headers and body-size middleware."""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import log, request_id_ctx

SAFE_PATHS = {"/health", "/health/live", "/health/ready", "/metrics", "/favicon.ico"}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attaches a request id, times the request and logs one structured line."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        request.state.request_id = rid
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            log.exception("http.request_failed", method=request.method,
                          path=request.url.path, duration_ms=round(elapsed, 2))
            raise
        finally:
            request_id_ctx.reset(token)

        elapsed = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = rid
        response.headers["x-response-time-ms"] = f"{elapsed:.2f}"
        if request.url.path not in SAFE_PATHS:
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round(elapsed, 2),
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if settings.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects oversized uploads before they are buffered into memory."""

    def __init__(self, app, max_mb: int = 15):
        super().__init__(app)
        self.max_bytes = max_mb * 1024 * 1024

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > self.max_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": {
                        "code": "payload_too_large",
                        "message": f"Upload exceeds {self.max_bytes // (1024 * 1024)} MB.",
                        "details": {},
                    },
                    "request_id": request_id_ctx.get(),
                },
            )
        return await call_next(request)


def register_middleware(app: FastAPI) -> None:
    # Outermost first: size guard → security headers → context/logging.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_mb=settings.MAX_UPLOAD_MB)
