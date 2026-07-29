"""AI conversations, tool calls, OCR jobs and token accounting."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, JSONType, Money, TZDateTime
from app.models.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDMixin
from app.models.enums import MessageRole, OcrStatus


class AiConversation(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __table_args__ = (Index("ix_ai_conversations_biz_user", "business_id", "user_id", "updated_at"),)

    user_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), default="New chat", nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="auto", nullable=False)
    channel: Mapped[str] = mapped_column(String(16), default="app", nullable=False)  # app|whatsapp|voice
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    # rolling summary of older turns so long chats stay inside the context window
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summarised_upto: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    messages: Mapped[list["AiMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AiMessage.sequence",
    )


class AiMessage(Base, UUIDMixin, TenantMixin, TimestampMixin):
    __table_args__ = (Index("ix_ai_messages_conv_seq", "conversation_id", "sequence"),)

    conversation_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=MessageRole.USER, nullable=False)

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # raw content blocks, so tool_use/tool_result round-trip exactly
    blocks: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)

    # what the assistant actually did, surfaced in the UI as action chips
    actions: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)
    attachments: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # voice provenance
    audio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transcript_confidence: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)

    conversation: Mapped["AiConversation"] = relationship(back_populates="messages")


class AiToolCall(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Every write the assistant performs is logged here — the audit trail for AI actions."""

    __table_args__ = (Index("ix_ai_tool_calls_biz_tool", "business_id", "tool_name", "created_at"),)

    conversation_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    message_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    user_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_use_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)

    is_write: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # what record it touched, so the UI can deep-link
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)


class OcrJob(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """A scanned bill/receipt and the structured draft extracted from it."""

    __table_args__ = (Index("ix_ocr_jobs_biz_status", "business_id", "status", "created_at"),)

    user_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    document_type: Mapped[str] = mapped_column(String(24), default="purchase_bill", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=OcrStatus.PENDING, nullable=False, index=True)

    # Nullable: recognition happens on the device, so a scan does not require a
    # stored image. This is set only when the shopkeeper keeps the photo.
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    # per-field confidence so the review screen can highlight what to double-check
    field_confidence: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    warnings: Mapped[list[Any] | None] = mapped_column(JSONType, default=list, nullable=True)

    matched_party_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    created_voucher_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    created_expense_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class AiUsage(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Daily token roll-up per business — powers quota enforcement and billing."""

    __tablename__ = "ai_usage"
    __table_args__ = (Index("ix_ai_usage_biz_day", "business_id", "usage_date", unique=True),)

    usage_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ocr_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)


class AiInsight(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """Generated business insight / anomaly shown on the dashboard."""

    __table_args__ = (Index("ix_ai_insights_biz_kind", "business_id", "kind", "created_at"),)

    kind: Mapped[str] = mapped_column(String(32), nullable=False)   # trend|anomaly|suggestion|alert
    severity: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    action: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)
    period_start: Mapped[str | None] = mapped_column(String(10), nullable=True)
    period_end: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
