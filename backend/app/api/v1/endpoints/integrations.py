"""Connect and use Gmail, WhatsApp and SMS."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import DbSession, Tenant
from app.core.config import settings
from app.core.permissions import Perm
from app.integrations.email import GmailService
from app.integrations.whatsapp import WhatsAppService, verify_webhook
from app.models.system import Integration
from app.schemas.common import Message
from app.services.share_service import ShareService

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", summary="Connection status for every channel")
async def list_integrations(tenant: Tenant, db: DbSession) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(Integration).where(Integration.business_id == tenant.business.id)
        )
    ).scalars().all()
    connected = {
        row.provider: {
            "connected": row.is_connected,
            "account": row.account_label,
            "last_used_at": row.last_used_at,
            "last_error": row.last_error,
        }
        for row in rows
    }
    return {
        "gmail": connected.get("gmail", {"connected": False}),
        "whatsapp": {
            "connected": settings.WHATSAPP_ENABLED and bool(settings.WHATSAPP_ACCESS_TOKEN),
            "phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID or None,
        },
        "smtp_fallback": {"configured": bool(settings.SMTP_USER)},
        "sms": {"provider": settings.SMS_PROVIDER or None},
    }


# ── Gmail OAuth ──────────────────────────────────────────────────
@router.get("/gmail/connect", summary="Start the Gmail connection flow")
async def gmail_connect(tenant: Tenant) -> dict[str, str]:
    tenant.require(Perm.INTEGRATION_MANAGE)
    return {"authorize_url": GmailService.authorize_url(state=tenant.business.id)}


@router.get("/gmail/callback", summary="Google OAuth redirect target")
async def gmail_callback(
    db: DbSession,
    code: str = Query(...),
    state: str = Query(..., description="The business id passed to /connect"),
) -> RedirectResponse:
    integration = await GmailService(db, state).exchange_code(code)
    return RedirectResponse(
        url=f"karobar://integrations/gmail?connected=1&account={integration.account_label or ''}",
        status_code=302,
    )


@router.delete("/gmail", response_model=Message, summary="Disconnect Gmail")
async def gmail_disconnect(tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.INTEGRATION_MANAGE)
    await GmailService(db, tenant.business.id).disconnect()
    return Message(message="Gmail disconnected.")


# ── WhatsApp ─────────────────────────────────────────────────────
@router.get("/whatsapp/webhook", summary="Meta webhook verification")
async def whatsapp_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> Response:
    return Response(content=verify_webhook(hub_mode, hub_token, hub_challenge), media_type="text/plain")


@router.post("/whatsapp/webhook", summary="Delivery status callbacks")
async def whatsapp_webhook(request: Request, db: DbSession) -> dict[str, Any]:
    payload = await request.json()
    business_id = _business_from_webhook(payload)
    updated = await WhatsAppService(db, business_id or "").handle_status_webhook(payload)
    return {"received": True, "updated": updated}


# ── reminders ────────────────────────────────────────────────────
@router.post("/reminders/{party_id}", summary="Send a payment reminder")
async def send_reminder(
    party_id: str,
    tenant: Tenant,
    db: DbSession,
    channel: Annotated[str, Body(embed=True)] = "whatsapp",
) -> dict[str, Any]:
    tenant.require(Perm.PAYMENT_READ)
    return await ShareService(db, tenant.actor).send_payment_reminder(party_id, channel)


def _business_from_webhook(payload: dict[str, Any]) -> str | None:
    """Meta does not echo our business id, so resolve by the phone-number id."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            metadata = change.get("value", {}).get("metadata", {})
            if metadata.get("phone_number_id") == settings.WHATSAPP_PHONE_NUMBER_ID:
                return None  # single-tenant WhatsApp app; log rows carry their own business_id
    return None
