"""How the database engine is configured per host.

This is not a detail. Measured against the deployment, opening one connection to
the Supabase transaction pooler costs ~2.9s while a query on an existing one
costs ~190ms — so whether a connection is reused decides whether a screen takes
seven seconds or one.
"""

from __future__ import annotations

import pytest
from sqlalchemy.pool import NullPool

from app.core import database
from app.core.config import Settings


def kwargs_for(monkeypatch, **env) -> dict:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(database, "settings", Settings(_env_file=""))
    return database._engine_kwargs()


POSTGRES = "postgresql+asyncpg://u:p@host.pooler.supabase.com:6543/postgres"


def test_a_warm_serverless_instance_reuses_its_connection(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    kw = kwargs_for(monkeypatch, DATABASE_URL=POSTGRES)

    assert kw.get("poolclass") is not NullPool, (
        "a connection per request pays ~2.9s of handshake every time"
    )
    assert kw["pool_size"] >= 1
    assert kw["pool_pre_ping"] is True, (
        "an instance frozen between requests can wake to a dead connection"
    )


def test_the_pool_stays_small(monkeypatch):
    """The pooler has a client limit, and the win here is latency rather than
    concurrency — a large pool per instance would trade one for the other."""
    monkeypatch.setenv("VERCEL", "1")
    kw = kwargs_for(monkeypatch, DATABASE_URL=POSTGRES)

    assert kw["pool_size"] + kw["max_overflow"] <= 5


def test_connections_are_recycled_before_the_pooler_drops_them(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    kw = kwargs_for(monkeypatch, DATABASE_URL=POSTGRES)

    assert 0 < kw["pool_recycle"] <= 300, (
        "a connection we replace ourselves beats one we find dead"
    )


def test_it_can_be_put_back_to_a_connection_per_request(monkeypatch):
    """An escape hatch that needs no deploy, in case pooling misbehaves."""
    monkeypatch.setenv("VERCEL", "1")
    kw = kwargs_for(monkeypatch, DATABASE_URL=POSTGRES, DB_SERVERLESS_POOL_SIZE="0")

    assert kw["poolclass"] is NullPool
    assert "pool_pre_ping" not in kw


def test_a_container_host_keeps_its_full_pool(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    kw = kwargs_for(monkeypatch, DATABASE_URL=POSTGRES, DB_POOL_SIZE="20")

    assert kw["pool_size"] == 20
    assert kw["pool_recycle"] == 1800


@pytest.mark.parametrize("url", [
    POSTGRES,
    "postgresql+asyncpg://u:p@aws-1-ap-south-1.pooler.supabase.com:6543/postgres",
])
def test_prepared_statement_caching_is_off_behind_pgbouncer(monkeypatch, url):
    """pgbouncer in transaction mode hands a different backend to each
    statement, so a cached plan can be sent to a connection that never saw it."""
    monkeypatch.setenv("VERCEL", "1")
    kw = kwargs_for(monkeypatch, DATABASE_URL=url)

    assert kw["connect_args"]["statement_cache_size"] == 0
    assert kw["connect_args"]["prepared_statement_cache_size"] == 0


def test_every_postgres_connect_has_a_timeout(monkeypatch):
    """Without one, a connect that hangs is killed by the platform instead of
    raising, and the failure arrives as FUNCTION_INVOCATION_FAILED with no
    indication of what went wrong."""
    monkeypatch.setenv("VERCEL", "1")
    kw = kwargs_for(monkeypatch, DATABASE_URL=POSTGRES)

    assert 0 < kw["connect_args"]["timeout"] <= 15


def test_sqlite_is_untouched_by_any_of_this(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    kw = kwargs_for(monkeypatch, DATABASE_URL="sqlite+aiosqlite:///./test.db")

    assert kw["poolclass"] is NullPool
    assert kw["connect_args"]["check_same_thread"] is False
