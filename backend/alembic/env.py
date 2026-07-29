"""Alembic environment.

Reads the URL from application settings rather than alembic.ini, so there is one
source of truth, and converts the async driver to its sync equivalent because
Alembic runs migrations synchronously.
"""

from __future__ import annotations

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def sync_url() -> str:
    """postgresql+asyncpg://… → postgresql://…, sqlite+aiosqlite://… → sqlite://…"""
    return re.sub(r"\+(asyncpg|aiosqlite|aiomysql)", "", settings.DATABASE_URL)


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    # Never let autogenerate try to drop tables it doesn't know about.
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        render_as_batch=settings.is_sqlite,  # SQLite cannot ALTER most columns
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = sync_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
            render_as_batch=settings.is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
