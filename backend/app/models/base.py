"""Declarative base + mixins shared by every model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.core.types import GUID, JSONType, TZDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """All models inherit from here. `__tablename__` is derived from the class name."""

    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        name = cls.__name__
        out = [name[0].lower()]
        for ch in name[1:]:
            out.append(f"_{ch.lower()}" if ch.isupper() else ch)
        table = "".join(out)
        # naive pluralisation is fine for this domain
        if table.endswith(("s", "x", "ch", "sh")):
            return table + "es"
        if table.endswith("y") and table[-2] not in "aeiou":
            return table[:-1] + "ies"
        return table + "s"

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        exclude = exclude or set()
        return {
            c.key: getattr(self, c.key)
            for c in self.__table__.columns
            if c.key not in exclude
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        label = getattr(self, "name", None) or getattr(self, "number", None)
        return f"<{type(self).__name__} id={pk}{f' {label!r}' if label else ''}>"


class UUIDMixin:
    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=gen_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime(), server_default=func.now(), default=utcnow, onupdate=utcnow, nullable=False
    )


class SoftDeleteMixin:
    """Nothing is hard-deleted — ledgers must stay auditable."""

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    deleted_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    def soft_delete(self, user_id: str | None = None) -> None:
        self.is_deleted = True
        self.deleted_at = utcnow()
        self.deleted_by = user_id

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None


class TenantMixin:
    """Every business-scoped row carries its business_id. Never query without it."""

    @declared_attr
    def business_id(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(
            GUID(), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
        )


class SyncMixin:
    """Fields the offline-first client needs for delta sync + conflict resolution.

    `client_uuid` is the id the phone generated while offline; the server keeps it so
    a retried upload is idempotent instead of creating a duplicate.
    """

    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    client_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    synced_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def bump_revision(self) -> None:
        self.revision = (self.revision or 0) + 1
        self.updated_at = utcnow()  # type: ignore[attr-defined]


class AuditedMixin:
    created_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)


def tenant_index(table: str, *columns: str, unique: bool = False) -> Index:
    """Composite index that always leads with business_id — the shape every query uses."""
    name = f"ix_{table}_biz_{'_'.join(columns)}"[:63]
    return Index(name, "business_id", *columns, unique=unique)
