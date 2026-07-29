"""Email delivery — Gmail OAuth when connected, SMTP otherwise."""

from __future__ import annotations

import base64
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import IntegrationError
from app.core.logging import log
from app.models.base import utcnow
from app.models.system import Integration, MessageLog

GMAIL_SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
]


@dataclass(slots=True)
class OutgoingEmail:
    to: str
    subject: str
    body_text: str
    body_html: str | None = None
    attachments: list[tuple[str, bytes, str]] | None = None  # (filename, data, mime)
    cc: list[str] | None = None
    reply_to: str | None = None


class EmailSender:
    """SMTP path. Works with a Gmail App Password out of the box."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        from_name: str | None = None,
    ) -> None:
        self.host = host or settings.SMTP_HOST
        self.port = port or settings.SMTP_PORT
        self.user = user or settings.SMTP_USER
        self.password = password or settings.SMTP_PASSWORD
        self.from_name = from_name or settings.SMTP_FROM_NAME

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password)

    async def send(self, email: OutgoingEmail) -> bool:
        if not self.configured:
            raise IntegrationError(
                "Email is not set up. Add SMTP credentials or connect Gmail in Settings.",
                code="email_not_configured",
            )

        message = self._build(email)
        try:
            import asyncio  # noqa: PLC0415

            await asyncio.to_thread(self._send_sync, message, email)
            return True
        except (smtplib.SMTPException, OSError) as exc:
            log.error("email.send_failed", error=str(exc)[:300], to=email.to)
            raise IntegrationError(f"Could not send the email: {exc}") from exc

    async def send_plain(self, to: str, subject: str, body: str) -> bool:
        return await self.send(OutgoingEmail(to=to, subject=subject, body_text=body))

    def _build(self, email: OutgoingEmail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = f"{self.from_name} <{self.user}>"
        message["To"] = email.to
        message["Subject"] = email.subject
        if email.cc:
            message["Cc"] = ", ".join(email.cc)
        if email.reply_to:
            message["Reply-To"] = email.reply_to

        message.set_content(email.body_text)
        if email.body_html:
            message.add_alternative(email.body_html, subtype="html")

        for filename, data, mime in email.attachments or []:
            maintype, _, subtype = mime.partition("/")
            message.add_attachment(
                data, maintype=maintype or "application", subtype=subtype or "octet-stream",
                filename=filename,
            )
        return message

    def _send_sync(self, message: EmailMessage, email: OutgoingEmail) -> None:
        context = ssl.create_default_context()
        recipients = [email.to, *(email.cc or [])]
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=30) as server:
                server.login(self.user, self.password)
                server.send_message(message, to_addrs=recipients)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls(context=context)
                server.login(self.user, self.password)
                server.send_message(message, to_addrs=recipients)


class GmailService:
    """Gmail API path — used when the owner has connected their Google account."""

    def __init__(self, db: AsyncSession, business_id: str, user_id: str | None = None) -> None:
        self.db = db
        self.business_id = business_id
        self.user_id = user_id

    # ── OAuth ────────────────────────────────────────────────────
    @staticmethod
    def authorize_url(state: str) -> str:
        from urllib.parse import urlencode  # noqa: PLC0415

        if not settings.GOOGLE_CLIENT_ID:
            raise IntegrationError("Google sign-in is not configured on this server.")
        return f"{GOOGLE_AUTH}?" + urlencode(
            {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(GMAIL_SCOPES),
                "access_type": "offline",
                "prompt": "consent",
                "state": state,
            }
        )

    async def exchange_code(self, code: str) -> Integration:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                GOOGLE_TOKEN,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
            )
        if response.status_code >= 400:
            raise IntegrationError(f"Google rejected the connection: {response.text[:200]}")

        tokens = response.json()
        email = await self._account_email(tokens["access_token"])

        integration = await self._get_or_create("gmail")
        integration.is_connected = True
        integration.account_label = email
        integration.access_token_enc = _encrypt(tokens["access_token"])
        if tokens.get("refresh_token"):
            integration.refresh_token_enc = _encrypt(tokens["refresh_token"])
        integration.token_expires_at = utcnow() + _seconds(tokens.get("expires_in", 3600))
        integration.scopes = GMAIL_SCOPES
        integration.connected_by = self.user_id
        integration.last_error = None
        await self.db.flush()
        return integration

    async def disconnect(self) -> None:
        integration = await self._find("gmail")
        if integration:
            integration.is_connected = False
            integration.access_token_enc = None
            integration.refresh_token_enc = None

    # ── send ─────────────────────────────────────────────────────
    async def send(self, email: OutgoingEmail) -> dict[str, Any]:
        entry = MessageLog(
            business_id=self.business_id,
            channel="email",
            recipient=email.to,
            subject=email.subject,
            body=email.body_text[:5000],
            status="queued",
            sent_by=self.user_id,
        )
        self.db.add(entry)

        integration = await self._find("gmail")
        try:
            if integration and integration.is_connected:
                message_id = await self._send_via_gmail(integration, email)
                entry.provider_message_id = message_id
            else:
                await EmailSender().send(email)
            entry.status = "sent"
            entry.delivered_at = utcnow()
            entry.attempts += 1
            return {"success": True, "recipient": email.to, "message_id": entry.provider_message_id}
        except IntegrationError as exc:
            entry.status = "failed"
            entry.error = exc.message
            entry.attempts += 1
            if integration:
                integration.last_error = exc.message
            raise

    async def _send_via_gmail(self, integration: Integration, email: OutgoingEmail) -> str:
        token = await self._fresh_token(integration)
        raw = EmailSender(user=integration.account_label)._build(email)  # noqa: SLF001
        encoded = base64.urlsafe_b64encode(raw.as_bytes()).decode()

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                GMAIL_SEND,
                json={"raw": encoded},
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code >= 400:
            raise IntegrationError(f"Gmail rejected the message: {response.text[:200]}")

        integration.last_used_at = utcnow()
        return response.json().get("id", "")

    async def _fresh_token(self, integration: Integration) -> str:
        if integration.token_expires_at and integration.token_expires_at > utcnow():
            return _decrypt(integration.access_token_enc or "")
        if not integration.refresh_token_enc:
            raise IntegrationError("Gmail needs to be reconnected.", code="gmail_reauth_required")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                GOOGLE_TOKEN,
                data={
                    "refresh_token": _decrypt(integration.refresh_token_enc),
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                },
            )
        if response.status_code >= 400:
            integration.is_connected = False
            raise IntegrationError("Gmail needs to be reconnected.", code="gmail_reauth_required")

        tokens = response.json()
        integration.access_token_enc = _encrypt(tokens["access_token"])
        integration.token_expires_at = utcnow() + _seconds(tokens.get("expires_in", 3600))
        return tokens["access_token"]

    async def _account_email(self, access_token: str) -> str | None:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        return response.json().get("email") if response.status_code == 200 else None

    async def _find(self, provider: str) -> Integration | None:
        return (
            await self.db.execute(
                select(Integration).where(
                    Integration.business_id == self.business_id,
                    Integration.provider == provider,
                )
            )
        ).scalar_one_or_none()

    async def _get_or_create(self, provider: str) -> Integration:
        integration = await self._find(provider)
        if integration is None:
            integration = Integration(business_id=self.business_id, provider=provider)
            self.db.add(integration)
            await self.db.flush()
        return integration


# ── token encryption ─────────────────────────────────────────────
def _fernet():
    from cryptography.fernet import Fernet  # noqa: PLC0415

    import base64 as b64  # noqa: PLC0415
    import hashlib  # noqa: PLC0415

    key = b64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def _encrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().encrypt(value.encode()).decode()
    except Exception:  # pragma: no cover — cryptography missing in a minimal install
        log.warning("integration.encryption_unavailable")
        return value


def _decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except Exception:
        return value


def _seconds(value: Any):
    from datetime import timedelta  # noqa: PLC0415

    return timedelta(seconds=int(value or 3600) - 60)
