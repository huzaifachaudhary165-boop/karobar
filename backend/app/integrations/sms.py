"""SMS delivery for OTPs and reminders. Twilio is the only provider wired up;
with `SMS_PROVIDER` unset this is a no-op and OTPs fall back to `OTP_DEV_MODE`."""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.errors import IntegrationError
from app.core.logging import log
from app.utils.phone import normalise_phone


class SmsSender:
    def __init__(self, provider: str | None = None) -> None:
        self.provider = (provider or settings.SMS_PROVIDER or "").lower()

    @property
    def configured(self) -> bool:
        if self.provider == "twilio":
            return bool(
                settings.TWILIO_ACCOUNT_SID
                and settings.TWILIO_AUTH_TOKEN
                and settings.TWILIO_FROM_NUMBER
            )
        return False

    async def send(self, to: str, body: str) -> bool:
        number = normalise_phone(to)
        if not number:
            raise IntegrationError("That phone number is not valid.", code="invalid_phone")

        if not self.provider:
            log.warning("sms.not_configured", to=number[-4:])
            return False
        if self.provider == "twilio":
            return await self._twilio(number, body)

        raise IntegrationError(
            f"SMS provider '{self.provider}' is not supported.", code="sms_provider_unknown"
        )

    async def _twilio(self, to: str, body: str) -> bool:
        if not self.configured:
            raise IntegrationError("Twilio credentials are missing.", code="sms_not_configured")

        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/"
            f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
        )
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    url,
                    data={"To": to, "From": settings.TWILIO_FROM_NUMBER, "Body": body[:1600]},
                    auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                )
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Could not reach the SMS provider: {exc}") from exc

        if response.status_code >= 400:
            detail = response.json().get("message", response.text[:200])
            log.error("sms.send_failed", status=response.status_code, error=detail)
            raise IntegrationError(f"SMS delivery failed: {detail}")
        return True
