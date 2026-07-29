"""WhatsApp Cloud API — invoice sharing and payment reminders.

Every send is logged to MessageLog so delivery can be traced and retried, and so
the same reminder is never sent twice in a day.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import IntegrationError
from app.core.logging import log
from app.models.base import utcnow
from app.models.system import MessageLog
from app.utils.phone import whatsapp_number

GRAPH_BASE = "https://graph.facebook.com"


class WhatsAppClient:
    """Thin wrapper over the Cloud API send endpoint."""

    def __init__(self, phone_number_id: str | None = None, access_token: str | None = None) -> None:
        self.phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        self.access_token = access_token or settings.WHATSAPP_ACCESS_TOKEN
        self.api_version = settings.WHATSAPP_API_VERSION

    @property
    def configured(self) -> bool:
        return bool(settings.WHATSAPP_ENABLED and self.phone_number_id and self.access_token)

    @property
    def _url(self) -> str:
        return f"{GRAPH_BASE}/{self.api_version}/{self.phone_number_id}/messages"

    async def send_text(self, to: str, body: str, *, preview_url: bool = True) -> dict[str, Any]:
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": preview_url, "body": body[:4096]},
            }
        )

    async def send_document(
        self, to: str, *, link: str, filename: str, caption: str | None = None
    ) -> dict[str, Any]:
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "document",
                "document": {
                    "link": link,
                    "filename": filename[:100],
                    **({"caption": caption[:1024]} if caption else {}),
                },
            }
        )

    async def send_template(
        self, to: str, *, template: str, language: str = "en", params: list[str] | None = None
    ) -> dict[str, Any]:
        """Templates are required to open a conversation outside the 24-hour window."""
        components = (
            [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in params],
                }
            ]
            if params
            else []
        )
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": language},
                    "components": components,
                },
            }
        )

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise IntegrationError(
                "WhatsApp is not connected. Add it in Settings → Integrations.",
                code="whatsapp_not_configured",
            )
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(self._url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach WhatsApp: {exc}") from exc

        if response.status_code >= 400:
            detail = _error_message(response)
            log.error("whatsapp.send_failed", status=response.status_code, error=detail)
            raise IntegrationError(f"WhatsApp rejected the message: {detail}")

        data = response.json()
        return {
            "message_id": (data.get("messages") or [{}])[0].get("id"),
            "raw": data,
        }


class WhatsAppService:
    """Business-facing operations, with logging and dedupe."""

    def __init__(self, db: AsyncSession, business_id: str, user_id: str | None = None) -> None:
        self.db = db
        self.business_id = business_id
        self.user_id = user_id
        self.client = WhatsAppClient()

    async def share_invoice(
        self,
        *,
        recipient: str,
        voucher_number: str,
        voucher_id: str,
        total: str,
        business_name: str,
        pdf_url: str | None = None,
        custom_message: str | None = None,
    ) -> dict[str, Any]:
        to = whatsapp_number(recipient)
        if not to:
            raise IntegrationError("That phone number is not valid for WhatsApp.")

        body = custom_message or (
            f"*{business_name}*\n\n"
            f"Invoice {voucher_number}\n"
            f"Amount: {total}\n\n"
            f"Thank you for your business."
        )

        entry = MessageLog(
            business_id=self.business_id,
            channel="whatsapp",
            recipient=to,
            body=body,
            template="invoice_share",
            entity_type="voucher",
            entity_id=voucher_id,
            status="queued",
            sent_by=self.user_id,
        )
        self.db.add(entry)

        try:
            if pdf_url and pdf_url.startswith("http"):
                result = await self.client.send_document(
                    to, link=pdf_url, filename=f"{voucher_number}.pdf", caption=body
                )
            else:
                result = await self.client.send_text(to, body)
            entry.status = "sent"
            entry.provider_message_id = result["message_id"]
            entry.attempts += 1
            return {"success": True, "message_id": result["message_id"], "recipient": to}
        except IntegrationError as exc:
            entry.status = "failed"
            entry.error = exc.message
            entry.attempts += 1
            raise

    async def send_payment_reminder(
        self,
        *,
        recipient: str,
        party_name: str,
        amount_due: str,
        business_name: str,
        invoice_number: str | None = None,
        days_overdue: int = 0,
        party_id: str | None = None,
    ) -> dict[str, Any]:
        to = whatsapp_number(recipient)
        if not to:
            raise IntegrationError("That phone number is not valid for WhatsApp.")

        if await self._already_sent_today("payment_reminder", to):
            return {"success": False, "skipped": True, "reason": "Already reminded today."}

        overdue = f" ({days_overdue} days overdue)" if days_overdue > 0 else ""
        reference = f" against invoice {invoice_number}" if invoice_number else ""
        body = (
            f"*{business_name}*\n\n"
            f"Dear {party_name},\n"
            f"A payment of {amount_due}{reference} is pending{overdue}.\n\n"
            f"Kindly arrange the payment at your earliest convenience. Thank you."
        )

        entry = MessageLog(
            business_id=self.business_id,
            channel="whatsapp",
            recipient=to,
            body=body,
            template="payment_reminder",
            entity_type="party",
            entity_id=party_id,
            status="queued",
            sent_by=self.user_id,
        )
        self.db.add(entry)

        try:
            result = await self.client.send_text(to, body)
            entry.status = "sent"
            entry.provider_message_id = result["message_id"]
            entry.attempts += 1
            return {"success": True, "message_id": result["message_id"], "recipient": to}
        except IntegrationError as exc:
            entry.status = "failed"
            entry.error = exc.message
            entry.attempts += 1
            raise

    async def handle_status_webhook(self, payload: dict[str, Any]) -> int:
        """Update delivery state from Meta's status callbacks."""
        updated = 0
        for entry_data in payload.get("entry", []):
            for change in entry_data.get("changes", []):
                for status in change.get("value", {}).get("statuses", []):
                    row = (
                        await self.db.execute(
                            select(MessageLog).where(
                                MessageLog.provider_message_id == status.get("id")
                            )
                        )
                    ).scalar_one_or_none()
                    if not row:
                        continue
                    state = status.get("status")
                    row.status = state or row.status
                    if state == "delivered":
                        row.delivered_at = utcnow()
                    elif state == "read":
                        row.read_at = utcnow()
                    elif state == "failed":
                        errors = status.get("errors") or [{}]
                        row.error = errors[0].get("title") or "Delivery failed"
                    updated += 1
        return updated

    async def _already_sent_today(self, template: str, recipient: str) -> bool:
        cutoff = utcnow() - timedelta(hours=20)
        count = (
            await self.db.execute(
                select(func.count()).select_from(MessageLog).where(
                    MessageLog.business_id == self.business_id,
                    MessageLog.template == template,
                    MessageLog.recipient == recipient,
                    MessageLog.status == "sent",
                    MessageLog.created_at >= cutoff,
                )
            )
        ).scalar_one()
        return int(count) > 0


def verify_webhook(mode: str | None, token: str | None, challenge: str | None) -> str:
    """Meta's GET verification handshake."""
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN and challenge:
        return challenge
    raise IntegrationError("WhatsApp webhook verification failed.", code="webhook_verify_failed")


def wa_me_link(phone: str, message: str) -> str:
    """Client-side fallback when the Cloud API isn't connected — opens WhatsApp."""
    from urllib.parse import quote  # noqa: PLC0415

    number = whatsapp_number(phone) or ""
    return f"https://wa.me/{number}?text={quote(message)}"


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json().get("error", {}).get("message", response.text[:200])
    except Exception:
        return response.text[:200]
