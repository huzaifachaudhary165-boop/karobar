"""Async SQLAlchemy engine/session. Works unchanged on SQLite and Postgres/Supabase."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import log


def _engine_kwargs() -> dict[str, Any]:
    kw: dict[str, Any] = {"echo": settings.DB_ECHO, "future": True, "pool_pre_ping": True}

    if settings.is_sqlite:
        # aiosqlite has no real pool tuning; NullPool avoids cross-thread handle reuse.
        kw["poolclass"] = NullPool
        kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
        return kw

    # How long a single connect attempt may take before it is treated as a
    # failure. Set here rather than left to the driver's default, which is long
    # enough that the platform kills the whole invocation first.

    if settings.is_serverless:
        # A serverless invocation is frozen between requests, so a pooled
        # connection is held open by a process that is not running — with enough
        # concurrent invocations that exhausts the database's connection limit
        # while almost none are doing work. NullPool hands the connection back
        # immediately and lets the *external* pooler do the pooling.
        kw["poolclass"] = NullPool
        kw.pop("pool_pre_ping")  # pointless when every connection is new
    else:
        kw["pool_size"] = settings.DB_POOL_SIZE
        kw["max_overflow"] = settings.DB_MAX_OVERFLOW
        kw["pool_recycle"] = 1800

    # pgbouncer in transaction mode hands a different backend to each statement,
    # so a cached prepared statement can be sent to a connection that never saw
    # it. Disabling the cache is the documented fix and costs little.
    connect_args: dict[str, Any] = {}
    if "pooler.supabase" in settings.DATABASE_URL or "6543" in settings.DATABASE_URL:
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0

    # A connect with no timeout can hang indefinitely, and on a serverless host
    # that does not surface as an error — the platform eventually kills the
    # invocation and reports only FUNCTION_INVOCATION_FAILED, with no clue which
    # of the app, the network or the database was at fault. Moving the function
    # to a region that could not reach the pooler produced exactly that: every
    # request died after ~25s and said nothing.
    #
    # Failing fast turns it into an exception the error handler can describe.
    connect_args["timeout"] = settings.DB_CONNECT_TIMEOUT
    kw["connect_args"] = connect_args

    return kw


engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


if settings.is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver level
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")       # concurrent readers while writing
        cur.execute("PRAGMA foreign_keys=ON")        # enforce FKs (off by default!)
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Commits on success, rolls back on exception."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create tables if they don't exist. Alembic owns schema in production."""
    from app.models import Base  # noqa: PLC0415 — avoid circular import at module load

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("db.ready", dialect=engine.dialect.name)


async def ping_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover
        log.error("db.ping_failed", error=str(exc))
        return False


async def close_db() -> None:
    await engine.dispose()
