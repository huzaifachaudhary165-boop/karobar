"""The chat orchestrator: conversation state, the tool loop, and usage accounting.

A manual loop rather than the SDK tool runner, because every turn here has to
persist raw content blocks to Postgres, log each tool call for audit, enforce
per-role permissions, and surface action chips to the client.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AiResult, ai_client
from app.ai.prompts import (
    VOICE_HINT, business_context, chat_system_prompt, suggestions_for,
)
from app.ai.tools import DEEP_LINK, ToolExecutor, WRITE_TOOLS, available_tools
from app.core.config import settings
from app.core.errors import AIError, NotFoundError
from app.core.logging import log
from app.models.ai import AiConversation, AiMessage, AiUsage
from app.models.base import utcnow
from app.models.business import Business, BusinessSettings
from app.models.enums import MessageRole
from app.services.base import ActorContext
from app.utils.strings import detect_language, truncate

MAX_TOOL_ROUNDS = 6          # a chat turn may chain at most this many tool rounds
HISTORY_TURNS = 24           # messages replayed into the model's context
SUMMARISE_AFTER = 40         # older turns get rolled into a summary past this


class ChatAgent:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    # ── public API ───────────────────────────────────────────────
    async def chat(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        language: str | None = None,
        allow_writes: bool = True,
        attachments: list[dict[str, Any]] | None = None,
        is_voice: bool = False,
        client_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not ai_client.available:
            raise AIError(
                "The AI assistant is not set up yet. Add your GROQ_API_KEY to the server .env.",
                code="ai_not_configured",
            )
        await self._assert_quota()

        conversation = await self._load_or_create(conversation_id, message, language)
        lang = language if language and language != "auto" else detect_language(message)

        history = await self._history(conversation)
        user_content = self._user_content(message, attachments, is_voice)
        history.append({"role": "user", "content": user_content})

        await self._persist(conversation, MessageRole.USER, content=message, blocks=user_content,
                            attachments=attachments)

        system = chat_system_prompt(
            await self._context(lang, client_context), read_only=not allow_writes
        )
        tools = available_tools(self.actor.role, allow_writes=allow_writes)
        executor = ToolExecutor(self.db, self.actor, currency=await self._currency())

        actions: list[dict[str, Any]] = []
        totals = {"input": 0, "output": 0, "latency": 0}
        result: AiResult | None = None

        for round_index in range(MAX_TOOL_ROUNDS):
            result = await ai_client.complete(history, system=system, tools=tools)
            totals["input"] += result.input_tokens
            totals["output"] += result.output_tokens
            totals["latency"] += result.latency_ms

            if result.is_refusal:
                return await self._finish(
                    conversation, result,
                    reply=self._refusal_text(result, lang),
                    actions=actions, totals=totals, lang=lang,
                )

            history.append({"role": "assistant", "content": result.content})
            tool_uses = result.tool_uses
            if not tool_uses:
                break

            tool_results: list[dict[str, Any]] = []
            for call in tool_uses:
                output = await executor.run(
                    call["name"], call.get("input") or {}, conversation_id=conversation.id
                )
                actions.append(self._to_action(call, output))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call["id"],
                        "content": _dump(output),
                        "is_error": not output.get("ok", True),
                    }
                )
            # All results for a parallel batch go back in ONE user message.
            history.append({"role": "user", "content": tool_results})

            if round_index == MAX_TOOL_ROUNDS - 1:
                log.warning("ai.tool_rounds_exhausted", conversation_id=conversation.id)

        assert result is not None
        return await self._finish(
            conversation, result, reply=result.text, actions=actions, totals=totals, lang=lang
        )

    async def suggestions(self, language: str = "en") -> list[str]:
        top = await self.db.execute(
            select(func.max(AiConversation.title)).where(
                AiConversation.business_id == self.business_id
            )
        )
        _ = top  # placeholder for future personalisation
        from app.services.party_service import PartyService  # noqa: PLC0415

        parties = await PartyService(self.db, self.actor).top_parties(limit=1)
        return suggestions_for(language, parties[0]["name"] if parties else None)

    async def list_conversations(self, limit: int = 30) -> list[AiConversation]:
        rows = await self.db.execute(
            select(AiConversation)
            .where(
                AiConversation.business_id == self.business_id,
                AiConversation.user_id == self.actor.user_id,
                AiConversation.is_deleted.is_(False),
            )
            .order_by(AiConversation.is_pinned.desc(), AiConversation.updated_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def get_conversation(self, conversation_id: str) -> AiConversation:
        row = (
            await self.db.execute(
                select(AiConversation).where(
                    AiConversation.id == conversation_id,
                    AiConversation.business_id == self.business_id,
                    AiConversation.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Conversation not found.")
        return row

    async def messages(self, conversation_id: str, limit: int = 100) -> list[AiMessage]:
        await self.get_conversation(conversation_id)
        rows = await self.db.execute(
            select(AiMessage)
            .where(AiMessage.conversation_id == conversation_id)
            .order_by(AiMessage.sequence)
            .limit(limit)
        )
        return list(rows.scalars().all())

    async def delete_conversation(self, conversation_id: str) -> None:
        conversation = await self.get_conversation(conversation_id)
        conversation.soft_delete(self.actor.user_id)

    # ── internals ────────────────────────────────────────────────
    async def _load_or_create(
        self, conversation_id: str | None, first_message: str, language: str | None
    ) -> AiConversation:
        if conversation_id:
            return await self.get_conversation(conversation_id)
        conversation = AiConversation(
            business_id=self.business_id,
            user_id=self.actor.user_id,
            title=truncate(first_message, 60),
            language=language or "auto",
        )
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def _history(self, conversation: AiConversation) -> list[dict[str, Any]]:
        """Replay recent turns as content blocks.

        Tool-use and tool-result blocks are stored verbatim so the model sees the
        same transcript it produced — dropping them corrupts the turn.
        """
        rows = (
            await self.db.execute(
                select(AiMessage)
                .where(AiMessage.conversation_id == conversation.id)
                .order_by(AiMessage.sequence.desc())
                .limit(HISTORY_TURNS)
            )
        ).scalars().all()

        messages: list[dict[str, Any]] = []
        for row in reversed(rows):
            if row.role not in (MessageRole.USER, MessageRole.ASSISTANT):
                continue
            content = row.blocks or ([{"type": "text", "text": row.content}] if row.content else None)
            if content:
                messages.append({"role": row.role, "content": content})

        # A turn must not start with tool results that have no matching tool_use.
        while messages and _starts_with_orphan_tool_result(messages[0]):
            messages.pop(0)

        if conversation.summary:
            messages.insert(
                0,
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"[Earlier in this chat]\n{conversation.summary}"}
                    ],
                },
            )
        return messages

    def _user_content(
        self, message: str, attachments: list[dict[str, Any]] | None, is_voice: bool
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for attachment in attachments or []:
            if attachment.get("media_type", "").startswith("image/") and attachment.get("data"):
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": attachment["media_type"],
                            "data": attachment["data"],
                        },
                    }
                )
        text = f"{VOICE_HINT}\n\n{message}" if is_voice else message
        blocks.append({"type": "text", "text": text})
        return blocks

    async def _persist(
        self,
        conversation: AiConversation,
        role: str,
        *,
        content: str | None,
        blocks: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        result: AiResult | None = None,
    ) -> AiMessage:
        sequence = (
            await self.db.execute(
                select(func.coalesce(func.max(AiMessage.sequence), 0)).where(
                    AiMessage.conversation_id == conversation.id
                )
            )
        ).scalar_one()

        # Never persist base64 image payloads — keep the reference only.
        safe_blocks = _strip_image_payloads(blocks) if blocks else None
        row = AiMessage(
            business_id=self.business_id,
            conversation_id=conversation.id,
            sequence=int(sequence) + 1,
            role=role,
            content=content,
            blocks=safe_blocks,
            actions=actions or [],
            attachments=[{k: v for k, v in a.items() if k != "data"} for a in (attachments or [])],
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            model=result.model if result else None,
            latency_ms=result.latency_ms if result else None,
            stop_reason=result.stop_reason if result else None,
        )
        self.db.add(row)
        conversation.message_count += 1
        conversation.last_message_at = utcnow()
        await self.db.flush()
        return row

    async def _finish(
        self,
        conversation: AiConversation,
        result: AiResult,
        *,
        reply: str,
        actions: list[dict[str, Any]],
        totals: dict[str, int],
        lang: str,
    ) -> dict[str, Any]:
        if not reply:
            reply = _fallback_reply(actions, lang)

        message = await self._persist(
            conversation, MessageRole.ASSISTANT,
            content=reply, blocks=result.content, actions=actions, result=result,
        )
        conversation.total_input_tokens += totals["input"]
        conversation.total_output_tokens += totals["output"]
        await self._record_usage(totals["input"], totals["output"])

        if conversation.message_count > SUMMARISE_AFTER and not conversation.summary:
            await self._summarise(conversation)

        return {
            "conversation_id": conversation.id,
            "message_id": message.id,
            "reply": reply,
            "language": lang,
            "actions": actions,
            "suggestions": await self._followups(actions, lang),
            "requires_confirmation": False,
            "input_tokens": totals["input"],
            "output_tokens": totals["output"],
            "latency_ms": totals["latency"],
            "model": result.model,
        }

    def _to_action(self, call: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
        meta = output.get("_meta") or {}
        ok = output.get("ok", True)
        name = call["name"]
        return {
            "tool": name,
            "label": _ACTION_LABELS.get(name, name.replace("_", " ").title()),
            "status": "done" if ok else "failed",
            "entity_type": meta.get("entity_type"),
            "entity_id": meta.get("entity_id"),
            "summary": _summarise_output(name, output),
            "arguments": call.get("input"),
            "error": output.get("error") if not ok else None,
            "deep_link": meta.get("deep_link"),
        }

    async def _followups(self, actions: list[dict[str, Any]], lang: str) -> list[str]:
        """Contextual next steps shown as chips under the reply."""
        done = {a["tool"] for a in actions if a["status"] == "done"}
        if "create_invoice" in done:
            return (
                ["Share on WhatsApp", "Record payment", "Create another invoice"]
                if lang == "en"
                else ["WhatsApp par bhejo", "Payment entry karo", "Ek aur bill banao"]
            )
        if "record_payment" in done:
            return (
                ["Show remaining balance", "Send receipt"]
                if lang == "en"
                else ["Baqi balance dikhao", "Receipt bhejo"]
            )
        if not actions:
            return (await self.suggestions(lang))[:3]
        return []

    async def _context(self, lang: str, client_context: dict[str, Any] | None) -> str:
        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        extra: dict[str, Any] = {}
        if client_context:
            if screen := client_context.get("screen"):
                extra["User is currently on screen"] = screen
            if viewing := client_context.get("viewing"):
                extra["Currently viewing"] = viewing
        extra["Reply language"] = {"ur": "Roman Urdu", "hi": "Roman Hindi"}.get(lang, "English")
        return business_context(
            business_name=business.name,
            currency_symbol=business.currency_symbol,
            country=business.country,
            tax_type=business.tax_type,
            today=date.today(),
            user_name=self.actor.user_name,
            role=self.actor.role,
            extra=extra,
        )

    async def _currency(self) -> str:
        return (
            await self.db.execute(
                select(Business.currency_symbol).where(Business.id == self.business_id)
            )
        ).scalar_one() or "Rs"

    async def _summarise(self, conversation: AiConversation) -> None:
        """Roll older turns into a short summary so long chats stay in budget."""
        rows = (
            await self.db.execute(
                select(AiMessage)
                .where(
                    AiMessage.conversation_id == conversation.id,
                    AiMessage.sequence > conversation.summarised_upto,
                    AiMessage.sequence <= conversation.message_count - HISTORY_TURNS,
                )
                .order_by(AiMessage.sequence)
            )
        ).scalars().all()
        if not rows:
            return

        transcript = "\n".join(f"{r.role}: {truncate(r.content, 300)}" for r in rows if r.content)
        try:
            result = await ai_client.complete(
                [
                    {
                        "role": "user",
                        "content": (
                            "Summarise this shop-assistant conversation in under 150 words. "
                            "Keep names, amounts, invoice numbers and any unresolved request. "
                            "Drop pleasantries.\n\n" + transcript
                        ),
                    }
                ],
                model=settings.AI_FAST_MODEL,
                max_tokens=512,
                effort="low",
            )
            conversation.summary = result.text
            conversation.summarised_upto = rows[-1].sequence
        except AIError:
            log.warning("ai.summarise_failed", conversation_id=conversation.id)

    async def _record_usage(self, input_tokens: int, output_tokens: int) -> None:
        today = date.today().isoformat()
        row = (
            await self.db.execute(
                select(AiUsage).where(
                    AiUsage.business_id == self.business_id, AiUsage.usage_date == today
                )
            )
        ).scalar_one_or_none()
        if row is None:
            # Counters are set explicitly rather than relying on the columns'
            # `default=0`: that default is applied by the INSERT, so a row that
            # has not been flushed yet still holds None — and the `+=` below
            # would blow up on it.
            row = AiUsage(
                business_id=self.business_id,
                usage_date=today,
                input_tokens=0,
                output_tokens=0,
                request_count=0,
                ocr_count=0,
                estimated_cost_usd=Decimal("0"),
            )
            self.db.add(row)
        row.input_tokens += input_tokens
        row.output_tokens += output_tokens
        row.request_count += 1
        row.estimated_cost_usd += Decimal(
            str(
                input_tokens / 1_000_000 * settings.AI_INPUT_COST_PER_MTOK
                + output_tokens / 1_000_000 * settings.AI_OUTPUT_COST_PER_MTOK
            )
        )

    async def _assert_quota(self) -> None:
        cfg = (
            await self.db.execute(
                select(BusinessSettings).where(BusinessSettings.business_id == self.business_id)
            )
        ).scalar_one_or_none()
        if cfg and not cfg.ai_enabled:
            raise AIError("The AI assistant is turned off for this business.", code="ai_disabled")

        cap = cfg.ai_monthly_token_cap if cfg else 0
        if not cap:
            return
        month = date.today().strftime("%Y-%m")
        used = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(AiUsage.input_tokens + AiUsage.output_tokens), 0)
                ).where(
                    AiUsage.business_id == self.business_id,
                    AiUsage.usage_date.like(f"{month}%"),
                )
            )
        ).scalar_one()
        if int(used) >= cap:
            raise AIError(
                "This month's AI usage limit has been reached. It resets next month.",
                code="ai_quota_exceeded",
                details={"used": int(used), "cap": cap},
            )

    def _refusal_text(self, result: AiResult, lang: str) -> str:
        log.info("ai.refused", category=result.refusal_category)
        if lang in ("ur", "hi"):
            return "Maaf kijiye, is request par main kaam nahi kar sakta. Koi aur cheez poochein?"
        return "I can't help with that request. Is there something else about your business I can do?"


_ACTION_LABELS = {
    "create_invoice": "Invoice created",
    "record_payment": "Payment recorded",
    "record_expense": "Expense recorded",
    "create_party": "Customer added",
    "create_item": "Item added",
    "adjust_stock": "Stock adjusted",
    "update_item_price": "Price updated",
    "search_parties": "Looked up customers",
    "search_items": "Looked up items",
    "get_party_details": "Checked account",
    "get_business_summary": "Checked figures",
    "get_stock_report": "Checked stock",
    "list_invoices": "Listed invoices",
    "get_outstanding": "Checked outstanding",
    "get_top_items": "Checked top items",
}


def _summarise_output(tool: str, output: dict[str, Any]) -> str | None:
    if not output.get("ok", True):
        return output.get("error")
    match tool:
        case "create_invoice":
            return f"{output.get('number')} · {output.get('party') or 'Walk-in'} · {output.get('total')}"
        case "record_payment":
            return f"{output.get('amount')} {output.get('direction')} · {output.get('party')}"
        case "record_expense":
            return f"{output.get('title')} · {output.get('amount')}"
        case "create_party" | "create_item":
            return output.get("name")
        case "adjust_stock":
            return f"{output.get('item')}: {output.get('before')} → {output.get('after')}"
        case "update_item_price":
            return output.get("item")
    return None


def _fallback_reply(actions: list[dict[str, Any]], lang: str) -> str:
    done = [a for a in actions if a["status"] == "done" and a["tool"] in WRITE_TOOLS]
    if done:
        summary = "; ".join(filter(None, (a.get("summary") for a in done)))
        return f"Ho gaya. {summary}" if lang in ("ur", "hi") else f"Done. {summary}"
    if lang in ("ur", "hi"):
        return "Samajh nahi aaya. Thoda tafseel se batayein?"
    return "I didn't quite catch that — could you say a bit more?"


def _dump(value: Any) -> str:
    import json  # noqa: PLC0415

    return json.dumps(value, ensure_ascii=False, default=str)


def _strip_image_payloads(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("type") == "image":
            out.append({"type": "text", "text": "[image attached]"})
        else:
            out.append(block)
    return out


def _starts_with_orphan_tool_result(message: dict[str, Any]) -> bool:
    content = message.get("content")
    if message.get("role") != "user" or not isinstance(content, list):
        return False
    return bool(content) and content[0].get("type") == "tool_result"
