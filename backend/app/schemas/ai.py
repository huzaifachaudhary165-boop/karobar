"""AI assistant, OCR and insight schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import InputModel, ORMModel


class ChatRequest(InputModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    language: str | None = Field(None, pattern="^(auto|en|ur|hi)$")
    # ids of files already uploaded via /files — images go to the vision model
    attachment_ids: list[str] = Field(default_factory=list)
    # when false the assistant proposes writes instead of performing them
    allow_writes: bool = True
    stream: bool = False
    client_context: dict[str, Any] = Field(default_factory=dict)


class ToolAction(ORMModel):
    """A single thing the assistant did (or wants to do)."""

    tool: str
    label: str
    status: str = "done"          # done | failed | pending_confirmation | rejected
    entity_type: str | None = None
    entity_id: str | None = None
    summary: str | None = None
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    # a deep link the app opens when the chip is tapped
    deep_link: str | None = None


class ChatResponse(ORMModel):
    conversation_id: str
    message_id: str
    reply: str
    language: str = "en"
    actions: list[ToolAction] = []
    suggestions: list[str] = []
    requires_confirmation: bool = False
    pending_action: ToolAction | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    model: str | None = None


class ConfirmActionRequest(InputModel):
    conversation_id: str
    tool_call_id: str
    approve: bool = True
    edits: dict[str, Any] | None = None


class MessageOut(ORMModel):
    id: str
    conversation_id: str
    sequence: int
    role: str
    content: str | None = None
    actions: list[Any] | None = None
    attachments: list[Any] | None = None
    audio_url: str | None = None
    error: str | None = None
    created_at: datetime


class ConversationOut(ORMModel):
    id: str
    title: str
    language: str
    channel: str
    is_pinned: bool
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = []


class VoiceRequest(InputModel):
    """Client does speech-to-text on-device (free, offline) and posts the text.
    `audio_attachment_id` is optional and only used for later review."""

    transcript: str = Field(min_length=1, max_length=4000)
    confidence: float | None = Field(None, ge=0, le=1)
    language: str | None = None
    conversation_id: str | None = None
    audio_attachment_id: str | None = None
    allow_writes: bool = True


class OcrRequest(InputModel):
    """A bill the device has already read.

    Character recognition happens on the phone (Google ML Kit — free, offline),
    so what arrives here is text, not an image. `attachment_id` is optional and
    only links the photo the shopkeeper chose to keep for their records.
    """

    raw_text: str = Field(
        min_length=12,
        max_length=50_000,
        description="Text extracted from the bill photo on the device.",
    )
    attachment_id: str | None = None
    document_type: Literal["purchase_bill", "sale_invoice", "receipt", "expense", "auto"] = "auto"
    auto_create: bool = False
    auto_create_party: bool = True
    auto_create_items: bool = False


class OcrLineItem(ORMModel):
    name: str
    description: str | None = None
    hsn_code: str | None = None
    qty: Decimal = Decimal("1")
    unit: str | None = None
    rate: Decimal = Decimal("0")
    discount: Decimal = Decimal("0")
    tax_rate: Decimal | None = None
    amount: Decimal = Decimal("0")
    matched_item_id: str | None = None
    match_confidence: float | None = None


class OcrExtract(ORMModel):
    document_type: str = "purchase_bill"
    vendor_name: str | None = None
    vendor_phone: str | None = None
    vendor_gstin: str | None = None
    vendor_address: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None

    lines: list[OcrLineItem] = []

    subtotal: Decimal | None = None
    discount: Decimal | None = None
    tax_amount: Decimal | None = None
    shipping: Decimal | None = None
    total: Decimal | None = None
    paid: Decimal | None = None
    balance: Decimal | None = None
    currency: str | None = None
    payment_mode: str | None = None
    notes: str | None = None


class OcrJobOut(ORMModel):
    id: str
    status: str
    document_type: str
    # Null when the shopkeeper scanned without keeping the photo — the text was
    # read on their device, so no image is required for the scan to work.
    file_url: str | None = None
    file_name: str | None = None
    extracted: dict[str, Any] | None = None
    confidence: Decimal | None = None
    field_confidence: dict[str, Any] | None = None
    warnings: list[Any] | None = None
    matched_party_id: str | None = None
    created_voucher_id: str | None = None
    created_expense_id: str | None = None
    error: str | None = None
    processing_ms: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


class OcrApplyRequest(InputModel):
    """Turn a reviewed OCR draft into a real purchase bill or expense."""

    job_id: str
    target: Literal["purchase", "expense", "sale"] = "purchase"
    corrections: dict[str, Any] = Field(default_factory=dict)
    create_missing_items: bool = True
    create_missing_party: bool = True


class InsightOut(ORMModel):
    id: str
    kind: str
    severity: str
    title: str
    body: str
    metrics: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    period_start: str | None = None
    period_end: str | None = None
    is_read: bool
    created_at: datetime


class InsightRequest(InputModel):
    period: str = "this_month"
    refresh: bool = False
    kinds: list[str] = Field(default_factory=list)


class AiUsageOut(ORMModel):
    period_start: str
    period_end: str
    input_tokens: int
    output_tokens: int
    request_count: int
    ocr_count: int
    estimated_cost_usd: Decimal
    monthly_cap: int
    percent_used: float


class SuggestionsResponse(ORMModel):
    """Contextual prompt chips shown above the chat input."""

    suggestions: list[str]
    context: str | None = None
