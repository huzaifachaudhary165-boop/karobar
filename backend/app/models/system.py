"""Cross-cutting tables: audit log, sync change-feed, numbering, attachments,
notifications and third-party integration credentials."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID, JSONType, TZDateTime
from app.models.base import Base, TenantMixin, TimestampMixin, UUIDMixin
from app.models.enums import NotificationChannel, SyncOperation


class AuditLog(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Who changed what, when. Written by AuditService on every mutating call."""

    __table_args__ = (
        Index("ix_audit_biz_entity", "business_id", "entity_type", "entity_id"),
        Index("ix_audit_biz_created", "business_id", "created_at"),
    )

    user_id: Mapped[str | None] = mapped_column(GUID(), nullable=True, index=True)
    user_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)   # create|update|delete|login|export…
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    entity_label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="api", nullable=False)


class ChangeLog(Base, TenantMixin, TimestampMixin):
    """Monotonic change feed the mobile client pulls with `?since=<seq>`.

    Uses a plain integer PK (not UUID) because ordering *is* the contract.
    """

    __tablename__ = "change_logs"
    __table_args__ = (
        Index("ix_changelog_biz_seq", "business_id", "id"),
        Index("ix_changelog_biz_entity", "business_id", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"),
                                    primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str] = mapped_column(GUID(), nullable=False)
    operation: Mapped[str] = mapped_column(String(12), default=SyncOperation.UPDATE, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)


class SyncState(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Per-device cursor so each phone knows where it left off."""

    __table_args__ = (UniqueConstraint("business_id", "device_id", name="uq_sync_state_device"),)

    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    last_pulled_seq: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"),
                                                 default=0, nullable=False)
    last_pushed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_pulled_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pending_conflicts: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)


class NumberSequence(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Row-locked counter that guarantees gap-free, collision-free document numbers."""

    __table_args__ = (
        UniqueConstraint("business_id", "series_key", "period", name="uq_number_sequence"),
    )

    series_key: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. "sale", "purchase"
    period: Mapped[str] = mapped_column(String(12), default="all", nullable=False)  # "all" | "2026-27"
    prefix: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    padding: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Attachment(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __table_args__ = (Index("ix_attachments_owner", "owner_type", "owner_id"),)

    owner_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Notification(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __table_args__ = (Index("ix_notifications_biz_user_read", "business_id", "user_id", "is_read"),)

    user_id: Mapped[str | None] = mapped_column(GUID(), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(16), default=NotificationChannel.IN_APP, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # payment_due|low_stock|ai_insight…
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)

    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    delivery_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True, index=True)


class Integration(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Connected third-party account (Gmail, WhatsApp, …).

    Tokens are stored encrypted at rest by IntegrationService — never in plaintext.
    """

    __table_args__ = (UniqueConstraint("business_id", "provider", name="uq_integration_provider"),)

    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # gmail|whatsapp|google_drive
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    account_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    scopes: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)

    config: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)


class MessageLog(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Outbound WhatsApp/email/SMS log — dedupe, delivery status and retries."""

    __table_args__ = (Index("ix_message_log_biz_channel", "business_id", "channel", "created_at"),)

    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), default="out", nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)

    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    provider_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    sent_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
