"""Sending documents out: WhatsApp, email, SMS or a shareable link."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BusinessRuleError, IntegrationError, NotFoundError
from app.core.money import format_money
from app.integrations.email import GmailService, OutgoingEmail
from app.integrations.sms import SmsSender
from app.integrations.whatsapp import WhatsAppService, wa_me_link
from app.models.base import utcnow
from app.models.business import Business
from app.models.party import Party
from app.models.voucher import Voucher
from app.schemas.voucher import ShareRequest
from app.services.base import ActorContext
from app.services.pdf_service import DOC_TITLES, PdfService


class ShareService:
    def __init__(self, db: AsyncSession, actor: ActorContext) -> None:
        self.db = db
        self.actor = actor
        self.business_id = actor.business_id or ""

    async def share_voucher(self, voucher_id: str, request: ShareRequest) -> dict[str, Any]:
        voucher = (
            await self.db.execute(
                select(Voucher).where(
                    Voucher.id == voucher_id,
                    Voucher.business_id == self.business_id,
                    Voucher.is_deleted.is_(False),
                )
            )
        ).scalar_one_or_none()
        if voucher is None:
            raise NotFoundError("Invoice not found.", details={"id": voucher_id})

        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        party = None
        if voucher.party_id:
            party = (
                await self.db.execute(select(Party).where(Party.id == voucher.party_id))
            ).scalar_one_or_none()

        total = format_money(voucher.total, symbol=f"{business.currency_symbol} ")
        title = DOC_TITLES.get(voucher.voucher_type, "Invoice").title()
        recipient = request.recipient or self._default_recipient(request.channel, party)

        match request.channel:
            case "whatsapp":
                result = await self._whatsapp(voucher, business, party, recipient, total, request)
            case "email":
                result = await self._email(voucher, business, party, recipient, total, title, request)
            case "sms":
                result = await self._sms(voucher, business, recipient, total, title)
            case "link":
                result = {
                    "success": True,
                    "channel": "link",
                    "share_url": self._public_link(voucher),
                    "detail": "Link generated.",
                }
            case _:
                raise BusinessRuleError(f"Unsupported channel '{request.channel}'.")

        if result.get("success"):
            voucher.sent_at = utcnow()
            channels = set(voucher.sent_channels or [])
            channels.add(request.channel)
            voucher.sent_channels = sorted(channels)
            voucher.bump_revision()
        return result

    # ── channels ─────────────────────────────────────────────────
    async def _whatsapp(
        self, voucher, business, party, recipient, total, request: ShareRequest
    ) -> dict[str, Any]:
        if not recipient:
            raise BusinessRuleError("No WhatsApp number for this customer.")

        service = WhatsAppService(self.db, self.business_id, self.actor.user_id)
        if not service.client.configured:
            # Not connected — hand the client a wa.me link to open the app instead.
            message = request.message or self._default_message(voucher, business, total)
            return {
                "success": True,
                "channel": "whatsapp",
                "recipient": recipient,
                "share_url": wa_me_link(recipient, message),
                "detail": "WhatsApp Business API is not connected — opening WhatsApp instead.",
            }

        return await service.share_invoice(
            recipient=recipient,
            voucher_number=voucher.number,
            voucher_id=voucher.id,
            total=total,
            business_name=business.name,
            pdf_url=self._public_link(voucher) if request.attach_pdf else None,
            custom_message=request.message,
        ) | {"channel": "whatsapp"}

    async def _email(
        self, voucher, business, party, recipient, total, title, request: ShareRequest
    ) -> dict[str, Any]:
        if not recipient:
            raise BusinessRuleError("No email address for this customer.")

        html = await PdfService(self.db, self.actor).render_html(voucher.id)
        attachments: list[tuple[str, bytes, str]] = []
        if request.attach_pdf:
            pdf = await PdfService(self.db, self.actor).render_pdf(voucher.id)
            if pdf:
                attachments.append((f"{voucher.number}.pdf", pdf, "application/pdf"))

        body = request.message or self._default_message(voucher, business, total)
        result = await GmailService(self.db, self.business_id, self.actor.user_id).send(
            OutgoingEmail(
                to=recipient,
                subject=f"{title} {voucher.number} from {business.name}",
                body_text=body,
                body_html=html,
                attachments=attachments or None,
                reply_to=business.email,
            )
        )
        return result | {"channel": "email"}

    async def _sms(self, voucher, business, recipient, total, title) -> dict[str, Any]:
        if not recipient:
            raise BusinessRuleError("No phone number for this customer.")
        body = f"{business.name}: {title} {voucher.number} for {total}. Thank you."
        try:
            sent = await SmsSender().send(recipient, body)
        except IntegrationError as exc:
            return {"success": False, "channel": "sms", "recipient": recipient, "detail": exc.message}
        return {
            "success": sent,
            "channel": "sms",
            "recipient": recipient,
            "detail": "Sent." if sent else "SMS is not configured.",
        }

    # ── reminders ────────────────────────────────────────────────
    async def send_payment_reminder(self, party_id: str, channel: str = "whatsapp") -> dict[str, Any]:
        party = (
            await self.db.execute(
                select(Party).where(Party.id == party_id, Party.business_id == self.business_id)
            )
        ).scalar_one_or_none()
        if party is None:
            raise NotFoundError("Party not found.")
        if party.balance <= 0:
            raise BusinessRuleError(f"{party.name} has no outstanding balance.")

        business = (
            await self.db.execute(select(Business).where(Business.id == self.business_id))
        ).scalar_one()
        amount = format_money(party.receivable, symbol=f"{business.currency_symbol} ")

        oldest = (
            await self.db.execute(
                select(Voucher)
                .where(
                    Voucher.business_id == self.business_id,
                    Voucher.party_id == party_id,
                    Voucher.balance_amount > 0,
                    Voucher.is_deleted.is_(False),
                )
                .order_by(Voucher.voucher_date)
                .limit(1)
            )
        ).scalar_one_or_none()

        if channel == "whatsapp":
            return await WhatsAppService(
                self.db, self.business_id, self.actor.user_id
            ).send_payment_reminder(
                recipient=party.contact_number or "",
                party_name=party.name,
                amount_due=amount,
                business_name=business.name,
                invoice_number=oldest.number if oldest else None,
                days_overdue=oldest.days_overdue if oldest else 0,
                party_id=party.id,
            )

        if channel == "email" and party.email:
            body = (
                f"Dear {party.name},\n\n"
                f"A payment of {amount} is pending"
                + (f" against invoice {oldest.number}" if oldest else "")
                + ".\n\nKindly arrange the payment at your earliest convenience.\n\n"
                f"Regards,\n{business.name}"
            )
            return await GmailService(self.db, self.business_id, self.actor.user_id).send(
                OutgoingEmail(
                    to=party.email, subject=f"Payment reminder from {business.name}", body_text=body
                )
            )

        raise BusinessRuleError(f"Cannot send a reminder to {party.name} on '{channel}'.")

    # ── helpers ──────────────────────────────────────────────────
    def _default_recipient(self, channel: str, party: Party | None) -> str | None:
        if party is None:
            return None
        if channel == "email":
            return party.email
        return party.contact_number

    def _default_message(self, voucher, business, total: str) -> str:
        title = DOC_TITLES.get(voucher.voucher_type, "Invoice").title()
        lines = [
            f"*{business.name}*",
            "",
            f"{title}: {voucher.number}",
            f"Date: {voucher.voucher_date.strftime('%d %b %Y')}",
            f"Amount: {total}",
        ]
        if voucher.balance_amount > 0 and voucher.paid_amount > 0:
            lines.append(
                f"Balance due: {format_money(voucher.balance_amount, symbol=f'{business.currency_symbol} ')}"
            )
        lines += ["", "Thank you for your business."]
        return "\n".join(lines)

    def _public_link(self, voucher: Voucher) -> str:
        base = settings.GOOGLE_REDIRECT_URI.split("/api/")[0] if settings.GOOGLE_REDIRECT_URI else ""
        return f"{base}/api/v1/public/vouchers/{voucher.id}"
