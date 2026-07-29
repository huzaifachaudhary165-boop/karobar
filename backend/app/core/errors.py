"""Typed application errors + FastAPI exception handlers with a stable envelope.

Every error response looks like:
    {"error": {"code": "not_found", "message": "...", "details": {...}}, "request_id": "..."}
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.logging import log, request_id_ctx


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "app_error"
    message: str = "Something went wrong."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        if status_code:
            self.status_code = status_code
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ValidationError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"
    message = "Validation failed."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource conflict."


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication required."


class PermissionError_(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "You do not have permission to do that."


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Please slow down."


class BusinessRuleError(AppError):
    """Domain rule violated — e.g. negative stock, closing a paid invoice."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "business_rule_violation"


class IntegrationError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "integration_error"
    message = "An external service failed."


class AIError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "ai_unavailable"
    message = "The AI service is unavailable."


def _envelope(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": request_id_ctx.get(),
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_r: Request, exc: AppError):
        if exc.status_code >= 500:
            log.error("app.error", code=exc.code, message=exc.message, details=exc.details)
        else:
            log.info("app.error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path"))
            fields[loc or "body"] = err["msg"]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope("validation_error", "Some fields are invalid.", {"fields": fields}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_r: Request, exc: StarletteHTTPException):
        code = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))

    @app.exception_handler(IntegrityError)
    async def _integrity(_r: Request, exc: IntegrityError):
        raw = str(getattr(exc, "orig", exc))
        message = "This record conflicts with an existing one."
        if "UNIQUE" in raw.upper() or "duplicate key" in raw.lower():
            message = "A record with these details already exists."
        elif "FOREIGN KEY" in raw.upper() or "violates foreign key" in raw.lower():
            message = "A referenced record does not exist."
        log.warning("db.integrity_error", error=raw[:500])
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content=_envelope("conflict", message)
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sql(_r: Request, exc: SQLAlchemyError):
        log.exception("db.error", error=str(exc)[:1000])
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("database_error", "A database error occurred."),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_r: Request, exc: Exception):
        log.exception("unhandled.error", error=str(exc))
        detail = {"exception": type(exc).__name__, "message": str(exc)} if settings.DEBUG else {}
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred.", detail),
        )
