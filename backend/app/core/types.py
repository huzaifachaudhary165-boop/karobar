"""Portable column types — same code runs on SQLite (dev) and Postgres (Supabase)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, DateTime, Numeric, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

MONEY_PRECISION = 18
MONEY_SCALE = 4
QTY_SCALE = 4


class GUID(TypeDecorator):
    """UUID stored natively on Postgres, as CHAR(36) elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value: Any, dialect) -> str | None:
        return None if value is None else str(value)


class JSONType(TypeDecorator):
    """JSONB on Postgres, TEXT-encoded JSON elsewhere."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    def process_result_value(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql" or not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None


class Money(TypeDecorator):
    """Fixed-point money. NEVER float — always Decimal in, Decimal out."""

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int = MONEY_PRECISION, scale: int = MONEY_SCALE, **kw):
        super().__init__(precision=precision, scale=scale, asdecimal=True, **kw)

    def process_bind_param(self, value: Any, dialect) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def process_result_value(self, value: Any, dialect) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))


class Quantity(Money):
    cache_ok = True  # re-declared: subclassing a TypeDecorator resets the flag

    # precision/scale are accepted explicitly so Alembic can re-instantiate the
    # type from its rendered repr — `Quantity(precision=18, scale=4)`.
    def __init__(self, precision: int = MONEY_PRECISION, scale: int = QTY_SCALE, **kw):
        super().__init__(precision=precision, scale=scale, **kw)


class TZDateTime(TypeDecorator):
    """Always UTC, always timezone-aware — on every backend.

    SQLite has no timezone type and hands back naive datetimes, so comparing a
    stored `expires_at` against `datetime.now(timezone.utc)` raises. This
    normalises both directions: values are converted to UTC on the way in and
    re-tagged as UTC on the way out.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self, **kw):
        kw.setdefault("timezone", True)
        super().__init__(**kw)

    def process_bind_param(self, value: Any, dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        # SQLite stores naive text; keeping tzinfo would round-trip a local offset.
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: Any, dialect) -> datetime | None:
        if value is None or not isinstance(value, datetime):
            return value
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(
            timezone.utc
        )


class LowerString(TypeDecorator):
    """Case-insensitive storage for emails/codes so uniqueness actually works."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> str | None:
        return value.strip().lower() if isinstance(value, str) else value
