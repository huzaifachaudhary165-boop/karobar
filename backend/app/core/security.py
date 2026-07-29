"""Password hashing, JWT issue/verify, OTP + API-key helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

TokenType = Literal["access", "refresh"]


# ── Passwords ────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    # bcrypt silently truncates >72 bytes; pre-hash so long passwords keep entropy.
    return pwd_context.hash(_prehash(plain))


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(_prehash(plain), hashed)
    except Exception:
        return False


def _prehash(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def password_strength_issues(pw: str) -> list[str]:
    issues = []
    if len(pw) < 8:
        issues.append("Password must be at least 8 characters.")
    if not any(c.isdigit() for c in pw):
        issues.append("Password must contain a number.")
    if not any(c.isalpha() for c in pw):
        issues.append("Password must contain a letter.")
    return issues


# ── JWT ──────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    subject: str,
    token_type: TokenType = "access",
    *,
    business_id: str | None = None,
    role: str | None = None,
    extra: dict[str, Any] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta is None:
        expires_delta = (
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            if token_type == "access"
            else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": settings.APP_NAME,
    }
    if business_id:
        payload["biz"] = str(business_id)
    if role:
        payload["role"] = role
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(subject: str, **kw: Any) -> str:
    return create_token(subject, "access", **kw)


def create_refresh_token(subject: str, **kw: Any) -> str:
    return create_token(subject, "refresh", **kw)


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired or of the wrong type."""


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            issuer=settings.APP_NAME,
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc

    if expected_type and payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token")
    return payload


# ── OTP ──────────────────────────────────────────────────────────
def generate_otp(length: int | None = None) -> str:
    n = length or settings.OTP_LENGTH
    return "".join(secrets.choice("0123456789") for _ in range(n))


def hash_otp(code: str, salt: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"{salt}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def verify_otp(code: str, salt: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_otp(code, salt), hashed)


# ── API keys / device tokens ─────────────────────────────────────
def generate_api_key(prefix: str = "kbr") -> tuple[str, str]:
    """Returns (plaintext_key, sha256_digest_to_store)."""
    raw = f"{prefix}_{secrets.token_urlsafe(32)}"
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_id() -> str:
    return str(uuid.uuid4())
