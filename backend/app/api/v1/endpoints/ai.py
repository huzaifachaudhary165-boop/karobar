"""The assistant: chat, voice, OCR scanning and insights."""

from __future__ import annotations

import base64
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.ai.agent import ChatAgent
from app.ai.insights import InsightService
from app.ai.ocr import OcrService
from app.api.deps import DbSession, Tenant
from app.ai.client import ai_client
from app.core.errors import BusinessRuleError, NotFoundError
from app.core.permissions import Perm
from app.core.rate_limit import ai_limit
from app.schemas.ai import (
    AiUsageOut, ChatRequest, ChatResponse, ConversationDetail, ConversationOut, InsightOut,
    InsightRequest, MessageOut, OcrApplyRequest, OcrJobOut, OcrRequest, SuggestionsResponse,
    VoiceRequest,
)
from app.schemas.common import Message
from app.services.storage_service import storage

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(ai_limit)])


# ── chat ─────────────────────────────────────────────────────────
@router.post("/chat", response_model=ChatResponse, summary="Talk to the assistant")
async def chat(payload: ChatRequest, tenant: Tenant, db: DbSession) -> ChatResponse:
    tenant.require(Perm.AI_USE)
    attachments = await _load_attachments(db, tenant, payload.attachment_ids)
    result = await ChatAgent(db, tenant.actor).chat(
        payload.message,
        conversation_id=payload.conversation_id,
        language=payload.language,
        allow_writes=payload.allow_writes,
        attachments=attachments,
        client_context=payload.client_context,
    )
    return ChatResponse.model_validate(result)


@router.post("/voice", response_model=ChatResponse,
             summary="Send a speech transcript (client does speech-to-text)")
async def voice(payload: VoiceRequest, tenant: Tenant, db: DbSession) -> ChatResponse:
    tenant.require(Perm.AI_USE)
    result = await ChatAgent(db, tenant.actor).chat(
        payload.transcript,
        conversation_id=payload.conversation_id,
        language=payload.language,
        allow_writes=payload.allow_writes,
        is_voice=True,
    )
    return ChatResponse.model_validate(result)


@router.post("/transcribe", summary="Turn a recording into text")
async def transcribe(
    tenant: Tenant,
    db: DbSession,
    file: UploadFile = File(...),
    language: str | None = Form(None),
) -> dict[str, str]:
    """Whisper transcription, for when the phone's own recogniser struggles.

    The app records offline and transcribes on-device for free by default; this
    is the accurate fallback. Item and customer names from this shop are passed
    to Whisper as a vocabulary hint, which is what turns "bori seement" into
    "bori cement" and a customer's name into the right spelling.
    """
    tenant.require(Perm.AI_USE)

    audio = await file.read()
    if len(audio) > 25 * 1024 * 1024:
        raise BusinessRuleError("That recording is too long. Keep it under a minute.")

    text = await ai_client.transcribe(
        audio,
        filename=file.filename or "speech.m4a",
        language=language,
        prompt=await _vocabulary_hint(db, tenant),
    )
    return {"text": text}


async def _vocabulary_hint(db: DbSession, tenant: Tenant) -> str:
    """A comma-separated list of this shop's own words.

    Whisper treats the prompt as context about what it is likely to hear, not as
    an instruction, so feeding it real item and customer names measurably
    improves the spelling of exactly the words that matter.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.item import Item  # noqa: PLC0415
    from app.models.party import Party  # noqa: PLC0415

    names: list[str] = []
    for model in (Item, Party):
        rows = (
            await db.execute(
                select(model.name)
                .where(model.business_id == tenant.business.id, model.is_deleted.is_(False))
                .limit(40)
            )
        ).scalars().all()
        names.extend(rows)
    return ", ".join(names)


@router.post("/chat/stream", summary="Stream a reply (no tool use)")
async def chat_stream(payload: ChatRequest, tenant: Tenant, db: DbSession) -> StreamingResponse:
    """Text-only streaming for a fast conversational reply.

    Tool-using turns go through POST /ai/chat — a tool loop cannot be streamed
    token-by-token without losing the action chips the client renders.
    """
    tenant.require(Perm.AI_USE)
    from app.ai.prompts import chat_system_prompt  # noqa: PLC0415

    agent = ChatAgent(db, tenant.actor)
    context = await agent._context(payload.language or "en", payload.client_context)  # noqa: SLF001

    async def generate():
        yield 'event: start\ndata: {"status":"streaming"}\n\n'
        try:
            async for chunk in ai_client.stream_text(
                [{"role": "user", "content": payload.message}],
                system=chat_system_prompt(context, read_only=True),
            ):
                yield f"data: {chunk}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f'event: error\ndata: {{"error":"{str(exc)[:200]}"}}\n\n'
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/suggestions", response_model=SuggestionsResponse, summary="Prompt suggestions")
async def suggestions(
    tenant: Tenant, db: DbSession, language: str = Query("en", pattern="^(en|ur|hi)$")
) -> SuggestionsResponse:
    tenant.require(Perm.AI_USE)
    return SuggestionsResponse(suggestions=await ChatAgent(db, tenant.actor).suggestions(language))


@router.get("/conversations", response_model=list[ConversationOut], summary="Chat history")
async def conversations(tenant: Tenant, db: DbSession) -> list[ConversationOut]:
    tenant.require(Perm.AI_USE)
    rows = await ChatAgent(db, tenant.actor).list_conversations()
    return [ConversationOut.model_validate(c) for c in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail,
            summary="One conversation with its messages")
async def conversation(
    conversation_id: str, tenant: Tenant, db: DbSession
) -> ConversationDetail:
    tenant.require(Perm.AI_USE)
    agent = ChatAgent(db, tenant.actor)
    row = await agent.get_conversation(conversation_id)
    detail = ConversationDetail.model_validate(row)
    detail.messages = [
        MessageOut.model_validate(m) for m in await agent.messages(conversation_id)
    ]
    return detail


@router.delete("/conversations/{conversation_id}", response_model=Message,
               summary="Delete a conversation")
async def delete_conversation(
    conversation_id: str, tenant: Tenant, db: DbSession
) -> Message:
    tenant.require(Perm.AI_USE)
    await ChatAgent(db, tenant.actor).delete_conversation(conversation_id)
    return Message(message="Conversation deleted.")


# ── OCR ──────────────────────────────────────────────────────────
@router.post("/ocr/scan", response_model=OcrJobOut, status_code=status.HTTP_201_CREATED,
             summary="Turn text read off a bill into a structured draft")
async def scan(payload: OcrRequest, tenant: Tenant, db: DbSession) -> OcrJobOut:
    tenant.require(Perm.AI_USE)
    job = await OcrService(db, tenant.actor).scan(
        raw_text=payload.raw_text,
        attachment_id=payload.attachment_id,
        document_type=payload.document_type,
        auto_create=payload.auto_create,
        auto_create_party=payload.auto_create_party,
        auto_create_items=payload.auto_create_items,
    )
    return OcrJobOut.model_validate(job)


@router.post("/ocr/apply", response_model=OcrJobOut,
             summary="Turn a reviewed scan into a real record")
async def apply_scan(payload: OcrApplyRequest, tenant: Tenant, db: DbSession) -> OcrJobOut:
    tenant.require(Perm.PURCHASE_WRITE)
    job = await OcrService(db, tenant.actor).apply(
        payload.job_id,
        target=payload.target,
        corrections=payload.corrections,
        create_missing_party=payload.create_missing_party,
        create_missing_items=payload.create_missing_items,
    )
    return OcrJobOut.model_validate(job)


@router.get("/ocr/jobs", response_model=list[OcrJobOut], summary="Recent scans")
async def ocr_jobs(tenant: Tenant, db: DbSession) -> list[OcrJobOut]:
    tenant.require(Perm.AI_USE)
    return [OcrJobOut.model_validate(j) for j in await OcrService(db, tenant.actor).recent()]


@router.get("/ocr/jobs/{job_id}", response_model=OcrJobOut, summary="One scan")
async def ocr_job(job_id: str, tenant: Tenant, db: DbSession) -> OcrJobOut:
    tenant.require(Perm.AI_USE)
    return OcrJobOut.model_validate(await OcrService(db, tenant.actor).get(job_id))


# ── insights ─────────────────────────────────────────────────────
@router.post("/insights", response_model=list[InsightOut], summary="Generate business insights")
async def generate_insights(
    payload: InsightRequest, tenant: Tenant, db: DbSession
) -> list[InsightOut]:
    tenant.require(Perm.REPORT_READ)
    rows = await InsightService(db, tenant.actor).generate(payload.period, refresh=payload.refresh)
    return [InsightOut.model_validate(r) for r in rows]


@router.get("/insights", response_model=list[InsightOut], summary="Recent insights")
async def list_insights(tenant: Tenant, db: DbSession) -> list[InsightOut]:
    tenant.require(Perm.REPORT_READ)
    rows = await InsightService(db, tenant.actor).list_recent()
    return [InsightOut.model_validate(r) for r in rows]


@router.post("/insights/{insight_id}/dismiss", response_model=Message, summary="Dismiss an insight")
async def dismiss_insight(insight_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.REPORT_READ)
    await InsightService(db, tenant.actor).dismiss(insight_id)
    return Message(message="Dismissed.")


# ── usage ────────────────────────────────────────────────────────
@router.get("/usage", response_model=AiUsageOut, summary="This month's AI usage")
async def usage(tenant: Tenant, db: DbSession) -> AiUsageOut:
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.models.ai import AiUsage  # noqa: PLC0415
    from app.models.business import BusinessSettings  # noqa: PLC0415

    month = date.today().strftime("%Y-%m")
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(AiUsage.input_tokens), 0),
                func.coalesce(func.sum(AiUsage.output_tokens), 0),
                func.coalesce(func.sum(AiUsage.request_count), 0),
                func.coalesce(func.sum(AiUsage.ocr_count), 0),
                func.coalesce(func.sum(AiUsage.estimated_cost_usd), 0),
            ).where(
                AiUsage.business_id == tenant.business.id,
                AiUsage.usage_date.like(f"{month}%"),
            )
        )
    ).one()
    cap = (
        await db.execute(
            select(BusinessSettings.ai_monthly_token_cap).where(
                BusinessSettings.business_id == tenant.business.id
            )
        )
    ).scalar_one_or_none() or 0
    used = int(row[0]) + int(row[1])
    return AiUsageOut(
        period_start=f"{month}-01",
        period_end=month,
        input_tokens=int(row[0]),
        output_tokens=int(row[1]),
        request_count=int(row[2]),
        ocr_count=int(row[3]),
        estimated_cost_usd=row[4],
        monthly_cap=cap,
        percent_used=round(used / cap * 100, 2) if cap else 0.0,
    )


async def _load_attachments(db, tenant, attachment_ids: list[str]) -> list[dict]:
    """Read uploaded images and inline them as base64 for the vision model."""
    if not attachment_ids:
        return []
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.system import Attachment  # noqa: PLC0415

    rows = (
        await db.execute(
            select(Attachment).where(
                Attachment.id.in_(attachment_ids),
                Attachment.business_id == tenant.business.id,
            )
        )
    ).scalars().all()
    if len(rows) != len(attachment_ids):
        raise NotFoundError("One or more attachments were not found.")

    out = []
    for row in rows:
        if not (row.mime_type or "").startswith("image/"):
            continue
        raw = await storage.read(row.stored_name)
        out.append(
            {
                "id": row.id,
                "file_name": row.file_name,
                "media_type": row.mime_type,
                "data": base64.standard_b64encode(raw).decode(),
            }
        )
    return out
