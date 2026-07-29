"""Karobar API — application factory and lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, log
from app.core.middleware import register_middleware

DESCRIPTION = """
**Karobar** — AI-powered billing, inventory and accounting for small businesses.

* Multi-tenant: every request is scoped to one business via the `X-Business-Id` header.
* Offline-first: mobile clients push local changes and pull a delta feed (`/sync`).
* AI: `/ai/chat` runs a tool-calling assistant that creates real records; `/ai/ocr` turns a
  photographed bill into a draft purchase.

Authenticate with `Authorization: Bearer <access_token>` from `/auth/login`.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info(
        "app.starting",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )

    for warning in settings.sanity_check():
        log.warning("config.warning", detail=warning)

    if settings.ENVIRONMENT != "test":
        # Alembic owns the schema in production; this makes local dev zero-setup.
        await init_db()

    settings.storage_path.mkdir(parents=True, exist_ok=True)
    log.info("app.ready", docs="/docs" if not settings.is_production else "disabled")

    yield

    log.info("app.stopping")
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=DESCRIPTION,
        default_response_class=ORJSONResponse,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
        contact={"name": "Karobar", "url": "https://karobar.app"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "X-Response-Time-Ms", "X-Pdf-Fallback"],
    )
    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    # Unprefixed probes so load balancers don't need to know the API version.
    app.include_router(health.router, include_in_schema=False)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs" if not settings.is_production else "unavailable",
            "api": settings.API_V1_PREFIX,
        }

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
    )
