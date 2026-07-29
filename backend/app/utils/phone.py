"""Phone normalisation. Defaults to Pakistan; falls back to a lenient cleanup
so a shopkeeper typing '0300-1234567' never gets a validation wall."""

from __future__ import annotations

import re

DEFAULT_REGION = "PK"
_NON_DIGIT = re.compile(r"[^\d+]")

# Common local prefixes → country code
_LOCAL_PREFIX = {"PK": ("92", 10), "IN": ("91", 10), "AE": ("971", 9), "BD": ("880", 10)}


def normalise_phone(value: str | None, region: str = DEFAULT_REGION) -> str | None:
    """Return an E.164-ish number ('+923001234567') or a cleaned fallback."""
    if not value:
        return None
    raw = _NON_DIGIT.sub("", value.strip())
    if not raw:
        return None

    try:
        import phonenumbers  # noqa: PLC0415 — optional dependency

        parsed = phonenumbers.parse(value, region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass

    if raw.startswith("+"):
        return raw
    cc, national_len = _LOCAL_PREFIX.get(region, ("92", 10))
    digits = raw.lstrip("0")
    if digits.startswith(cc) and len(digits) > national_len:
        return f"+{digits}"
    if len(digits) == national_len:
        return f"+{cc}{digits}"
    return f"+{digits}" if len(digits) >= 8 else raw


def is_phone_like(value: str) -> bool:
    digits = re.sub(r"\D", "", value or "")
    return 7 <= len(digits) <= 15 and not re.search(r"[a-zA-Z@]", value or "")


def whatsapp_number(value: str | None, region: str = DEFAULT_REGION) -> str | None:
    """WhatsApp Cloud API wants digits only, no '+'."""
    e164 = normalise_phone(value, region)
    return e164.lstrip("+") if e164 else None


def mask_phone(value: str | None) -> str:
    if not value or len(value) < 5:
        return value or ""
    return f"{value[:-4].rstrip()[:5]}****{value[-2:]}"
