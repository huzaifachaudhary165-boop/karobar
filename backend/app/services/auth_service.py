"""Registration, login, OTP, Google sign-in, sessions and token refresh."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError, NotFoundError, ValidationError
from app.core.logging import log
from app.core.permissions import Role, permissions_for
from app.core.security import (
    TokenError, create_access_token, create_refresh_token, decode_token, digest,
    generate_otp, hash_otp, hash_password, verify_otp, verify_password,
)
from app.models.base import utcnow
from app.models.business import Business, BusinessMember
from app.models.user import OtpChallenge, User, UserSession
from app.schemas.auth import DeviceInfo, LoginRequest, RegisterRequest
from app.utils.phone import is_phone_like, normalise_phone

MAX_FAILED_LOGINS = 6
LOCKOUT_MINUTES = 15
GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── registration ─────────────────────────────────────────────
    async def register(self, payload: RegisterRequest, *, ip: str | None = None) -> dict[str, Any]:
        email = payload.email.lower() if payload.email else None
        phone = normalise_phone(payload.phone) if payload.phone else None

        if email and await self._find_by_email(email):
            raise ConflictError("An account with this email already exists.", details={"field": "email"})
        if phone and await self._find_by_phone(phone):
            raise ConflictError("An account with this phone number already exists.", details={"field": "phone"})

        user = User(
            name=payload.name.strip(),
            email=email,
            phone=phone,
            password_hash=hash_password(payload.password),
            language=payload.language,
            timezone="Asia/Karachi" if payload.country.lower() == "pakistan" else "Asia/Kolkata",
        )
        self.db.add(user)
        await self.db.flush()

        business = None
        if payload.business_name:
            from app.services.business_service import BusinessService

            business = await BusinessService(self.db).create_for_owner(
                user,
                {
                    "name": payload.business_name,
                    "business_type": payload.business_type or "retail",
                    "country": payload.country,
                    "currency": payload.currency or ("PKR" if payload.country.lower() == "pakistan" else "INR"),
                    "phone": phone,
                    "email": email,
                },
            )
            user.active_business_id = business.id

        tokens = await self.issue_tokens(user, payload.device, ip=ip)
        log.info("auth.registered", user_id=user.id, has_business=business is not None)
        return await self.build_auth_response(user, tokens, is_new_user=True)

    # ── password login ───────────────────────────────────────────
    async def login(self, payload: LoginRequest, *, ip: str | None = None) -> dict[str, Any]:
        user = await self._find_by_identifier(payload.identifier)
        if user is None or not user.password_hash:
            raise AuthenticationError("Incorrect credentials. Please check and try again.")
        if user.is_locked:
            raise AuthenticationError(
                "Too many failed attempts. Try again in a few minutes.",
                details={"locked_until": user.locked_until.isoformat() if user.locked_until else None},
            )
        if not user.is_active:
            raise AuthenticationError("This account has been deactivated.")

        if not verify_password(payload.password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_LOGINS:
                user.locked_until = utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                user.failed_login_count = 0
            raise AuthenticationError("Incorrect credentials. Please check and try again.")

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = utcnow()

        tokens = await self.issue_tokens(user, payload.device, ip=ip)
        return await self.build_auth_response(user, tokens)

    # ── OTP ──────────────────────────────────────────────────────
    async def send_otp(self, identifier: str, purpose: str = "login") -> dict[str, Any]:
        target = normalise_phone(identifier) if is_phone_like(identifier) else identifier.strip().lower()
        channel = "sms" if is_phone_like(identifier) else "email"

        if purpose == "reset_password":
            # Say up front that there is no such account. This does tell an
            # anonymous caller which addresses are registered, which is a real
            # (if mild) disclosure — the alternative is a shopkeeper who typed
            # the wrong address staring at an inbox, waiting for a code that was
            # never going to arrive, with nothing on screen to suggest why.
            # For a shop app that trade is worth making; rate limiting is the
            # right defence against someone mining the endpoint.
            if await self._find_by_identifier(target) is None:
                raise NotFoundError(
                    "No account is registered with that email or phone number. "
                    "Check the spelling, or create a new account."
                )

            # Nor should it promise a code down a channel that cannot carry one.
            if channel == "sms" and not settings.OTP_DEV_MODE:
                from app.integrations.sms import SmsSender  # noqa: PLC0415

                if not SmsSender().configured:
                    raise ValidationError(
                        "Password reset by SMS is not available yet. "
                        "Use the email address on your account instead."
                    )

        # invalidate any live challenge for the same identifier+purpose
        for row in (
            await self.db.execute(
                select(OtpChallenge).where(
                    OtpChallenge.identifier == target,
                    OtpChallenge.purpose == purpose,
                    OtpChallenge.consumed_at.is_(None),
                )
            )
        ).scalars():
            row.consumed_at = utcnow()

        code = generate_otp()
        salt = secrets.token_hex(16)
        challenge = OtpChallenge(
            identifier=target,
            channel=channel,
            purpose=purpose,
            code_hash=hash_otp(code, salt),
            salt=salt,
            expires_at=utcnow() + timedelta(seconds=settings.OTP_TTL_SECONDS),
        )
        self.db.add(challenge)
        await self.db.flush()

        delivered = await self._deliver_otp(target, code, channel)
        log.info("auth.otp_sent", identifier=target[-4:], channel=channel, delivered=delivered)

        # "Code sent" when nothing was sent leaves someone waiting on an inbox
        # that will stay empty. The code is valid either way — in dev mode it
        # comes back in `debug_code` — so the honest message still lets them
        # continue, it just does not send them somewhere pointless to look.
        return {
            "message": (
                f"Verification code sent to {_mask(target)}."
                if delivered
                else f"Could not send the code to {_mask(target)} right now. "
                "Please check the address and try again."
            ),
            "delivered": delivered,
            "expires_in": settings.OTP_TTL_SECONDS,
            "debug_code": code if settings.OTP_DEV_MODE else None,
        }

    async def verify_otp_login(
        self,
        identifier: str,
        code: str,
        *,
        purpose: str = "login",
        name: str | None = None,
        device: DeviceInfo | None = None,
        ip: str | None = None,
    ) -> dict[str, Any]:
        target = normalise_phone(identifier) if is_phone_like(identifier) else identifier.strip().lower()
        challenge = (
            await self.db.execute(
                select(OtpChallenge)
                .where(
                    OtpChallenge.identifier == target,
                    OtpChallenge.purpose == purpose,
                    OtpChallenge.consumed_at.is_(None),
                )
                .order_by(OtpChallenge.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if challenge is None:
            raise AuthenticationError("No verification code was requested. Please request a new one.")
        if not challenge.is_usable:
            raise AuthenticationError("This code has expired. Please request a new one.")

        challenge.attempts += 1
        if not verify_otp(code.strip(), challenge.salt, challenge.code_hash):
            remaining = max(0, challenge.max_attempts - challenge.attempts)
            raise AuthenticationError(
                "Incorrect code.", details={"attempts_remaining": remaining}
            )

        challenge.consumed_at = utcnow()

        user = await self._find_by_identifier(target)
        is_new = user is None
        if user is None:
            is_email = "@" in target
            user = User(
                name=(name or "").strip() or _default_name(target),
                email=target if is_email else None,
                phone=None if is_email else target,
                email_verified=is_email,
                phone_verified=not is_email,
            )
            self.db.add(user)
            await self.db.flush()
        else:
            if "@" in target:
                user.email_verified = True
            else:
                user.phone_verified = True
            user.last_login_at = utcnow()

        tokens = await self.issue_tokens(user, device, ip=ip)
        return await self.build_auth_response(user, tokens, is_new_user=is_new)

    # ── Google ───────────────────────────────────────────────────
    async def google_login(
        self,
        id_token: str,
        *,
        device: DeviceInfo | None = None,
        ip: str | None = None,
        business_name: str | None = None,
        business_type: str | None = None,
        country: str = "Pakistan",
    ) -> dict[str, Any]:
        claims = await self._verify_google_token(id_token)
        sub = claims.get("sub")
        email = (claims.get("email") or "").lower() or None
        if not sub:
            raise AuthenticationError("Google sign-in failed: the token did not contain a user id.")

        user = (
            await self.db.execute(select(User).where(User.google_sub == sub).limit(1))
        ).scalar_one_or_none()
        is_new = False
        if user is None and email:
            user = await self._find_by_email(email)
            if user:
                user.google_sub = sub
        if user is None:
            user = User(
                name=claims.get("name") or _default_name(email or sub),
                email=email,
                google_sub=sub,
                email_verified=str(claims.get("email_verified", "true")).lower() == "true",
                avatar_url=claims.get("picture"),
            )
            self.db.add(user)
            await self.db.flush()
            is_new = True
        else:
            user.last_login_at = utcnow()
            if not user.avatar_url and claims.get("picture"):
                user.avatar_url = claims["picture"]

        # A user with no business has nowhere to put data — every tenant-scoped
        # request would fail. Password signup takes a shop name up front; Google
        # signup cannot, so one is created here. This also covers a user who was
        # invited to someone else's shop and later signs in with Google: they
        # already have a membership, so nothing is created.
        if not await self._has_any_business(user):
            from app.services.business_service import BusinessService  # noqa: PLC0415

            business = await BusinessService(self.db).create_for_owner(
                user,
                {
                    "name": (business_name or "").strip() or _default_shop_name(user.name),
                    "business_type": business_type or "retail",
                    "country": country,
                    "currency": "PKR" if country.lower() == "pakistan" else "INR",
                    "email": user.email,
                },
            )
            user.active_business_id = business.id
            await self.db.flush()

        tokens = await self.issue_tokens(user, device, ip=ip)
        return await self.build_auth_response(user, tokens, is_new_user=is_new)

    async def _has_any_business(self, user: User) -> bool:
        from app.models.business import BusinessMember  # noqa: PLC0415

        return (
            await self.db.execute(
                select(BusinessMember.id).where(BusinessMember.user_id == user.id).limit(1)
            )
        ).scalar_one_or_none() is not None

    async def _verify_google_token(self, id_token: str) -> dict[str, Any]:
        """Prefer local signature verification; fall back to Google's tokeninfo.

        A Google ID token proves who the user is *to a particular app*. Anyone
        can stand up a Google app and mint a valid token for their own signed-in
        users, so the signature alone means nothing — it is the `aud` claim,
        matched against our own client id, that makes it proof for *us*.

        Without GOOGLE_CLIENT_ID there is nothing to match against, and this
        used to fall through to tokeninfo with the audience check skipped: any
        valid Google token from any app on the internet would be accepted and
        would log in — or silently create — the account holding that email.
        Refusing outright is the only safe behaviour, and a server missing one
        env var should fail visibly rather than authenticate strangers.
        """
        if not settings.GOOGLE_CLIENT_ID:
            raise AuthenticationError(
                "Google sign-in is not configured on this server. "
                "Sign in with your phone number and password instead."
            )

        try:
            from google.auth.transport import requests as g_requests  # noqa: PLC0415
            from google.oauth2 import id_token as g_id_token  # noqa: PLC0415

            return g_id_token.verify_oauth2_token(
                id_token, g_requests.Request(), settings.GOOGLE_CLIENT_ID
            )
        except ImportError:
            pass  # google-auth absent — verify over the network instead
        except ValueError as exc:
            raise AuthenticationError(f"Google sign-in failed: {exc}") from exc

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(GOOGLE_TOKENINFO, params={"id_token": id_token})
        if resp.status_code != 200:
            raise AuthenticationError("Google sign-in failed: the token could not be verified.")
        claims = resp.json()
        if claims.get("aud") != settings.GOOGLE_CLIENT_ID:
            raise AuthenticationError("Google sign-in failed: token was issued for another app.")
        return claims

    # ── tokens & sessions ────────────────────────────────────────
    async def issue_tokens(
        self, user: User, device: DeviceInfo | None = None, *, ip: str | None = None
    ) -> dict[str, Any]:
        business_id = user.active_business_id
        role = None
        if business_id:
            role = await self._role_for(user.id, business_id)
            if role is None:  # stale pointer — fall back to any membership
                business_id, role = await self._first_membership(user.id)
                user.active_business_id = business_id
        else:
            business_id, role = await self._first_membership(user.id)
            if business_id:
                user.active_business_id = business_id

        access = create_access_token(user.id, business_id=business_id, role=role)
        refresh = create_refresh_token(user.id, business_id=business_id)

        self.db.add(
            UserSession(
                user_id=user.id,
                refresh_token_hash=digest(refresh),
                device_id=device.device_id if device else None,
                device_name=device.device_name if device else None,
                platform=device.platform if device else None,
                push_token=device.push_token if device else None,
                ip_address=ip,
                expires_at=utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                last_used_at=utcnow(),
            )
        )
        await self._prune_sessions(user.id)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    async def refresh(self, refresh_token: str, *, ip: str | None = None) -> dict[str, Any]:
        try:
            payload = decode_token(refresh_token, "refresh")
        except TokenError as exc:
            raise AuthenticationError(str(exc)) from exc

        session = (
            await self.db.execute(
                select(UserSession).where(UserSession.refresh_token_hash == digest(refresh_token))
            )
        ).scalar_one_or_none()
        if session is None or not session.is_valid:
            raise AuthenticationError("This session has expired. Please sign in again.")

        user = (
            await self.db.execute(select(User).where(User.id == payload["sub"]))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            raise AuthenticationError("Account is no longer active.")

        # rotate: the old refresh token stops working the moment a new one is issued
        session.revoked_at = utcnow()
        tokens = await self.issue_tokens(user, ip=ip)
        return await self.build_auth_response(user, tokens)

    async def logout(self, refresh_token: str | None, user_id: str, *, all_devices: bool = False) -> None:
        if all_devices:
            for row in (
                await self.db.execute(
                    select(UserSession).where(
                        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
                    )
                )
            ).scalars():
                row.revoked_at = utcnow()
            return
        if refresh_token:
            session = (
                await self.db.execute(
                    select(UserSession).where(UserSession.refresh_token_hash == digest(refresh_token))
                )
            ).scalar_one_or_none()
            if session:
                session.revoked_at = utcnow()

    async def list_sessions(self, user_id: str) -> list[UserSession]:
        return list(
            (
                await self.db.execute(
                    select(UserSession)
                    .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
                    .order_by(UserSession.last_used_at.desc().nullslast())
                )
            ).scalars().all()
        )

    async def revoke_session(self, user_id: str, session_id: str) -> None:
        session = (
            await self.db.execute(
                select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user_id)
            )
        ).scalar_one_or_none()
        if session is None:
            raise NotFoundError("Session not found.")
        session.revoked_at = utcnow()

    # ── password management ──────────────────────────────────────
    async def change_password(self, user: User, current: str, new: str) -> None:
        if not user.password_hash or not verify_password(current, user.password_hash):
            raise AuthenticationError("Your current password is incorrect.")
        user.password_hash = hash_password(new)
        for row in (
            await self.db.execute(
                select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            )
        ).scalars():
            row.revoked_at = utcnow()

    async def reset_password(self, identifier: str, code: str, new_password: str) -> None:
        target = normalise_phone(identifier) if is_phone_like(identifier) else identifier.strip().lower()
        challenge = (
            await self.db.execute(
                select(OtpChallenge)
                .where(
                    OtpChallenge.identifier == target,
                    OtpChallenge.purpose == "reset_password",
                    OtpChallenge.consumed_at.is_(None),
                )
                .order_by(OtpChallenge.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if challenge is None or not challenge.is_usable:
            raise AuthenticationError("This reset code has expired. Please request a new one.")
        challenge.attempts += 1
        if not verify_otp(code.strip(), challenge.salt, challenge.code_hash):
            raise AuthenticationError("Incorrect reset code.")
        challenge.consumed_at = utcnow()

        user = await self._find_by_identifier(target)
        if user is None:
            raise NotFoundError("No account found for that email or phone number.")
        user.password_hash = hash_password(new_password)

    async def switch_business(self, user: User, business_id: str) -> dict[str, Any]:
        role = await self._role_for(user.id, business_id)
        if role is None:
            raise NotFoundError("You are not a member of that business.")
        user.active_business_id = business_id
        tokens = await self.issue_tokens(user)
        return await self.build_auth_response(user, tokens)

    # ── response assembly ────────────────────────────────────────
    async def build_auth_response(
        self, user: User, tokens: dict[str, Any], *, is_new_user: bool = False
    ) -> dict[str, Any]:
        rows = (
            await self.db.execute(
                select(Business, BusinessMember.role)
                .join(BusinessMember, BusinessMember.business_id == Business.id)
                .where(
                    BusinessMember.user_id == user.id,
                    BusinessMember.is_active.is_(True),
                    Business.is_deleted.is_(False),
                )
                .order_by(Business.created_at)
            )
        ).all()

        businesses = [
            {
                "id": b.id, "name": b.name, "business_type": b.business_type,
                "logo_url": b.logo_url, "currency": b.currency,
                "currency_symbol": b.currency_symbol, "role": role, "plan": b.plan,
            }
            for b, role in rows
        ]
        active = next((b for b in businesses if b["id"] == user.active_business_id), None)
        if active is None and businesses:
            active = businesses[0]
            user.active_business_id = active["id"]

        perms = sorted(str(p) for p in permissions_for(active["role"])) if active else []
        return {
            "user": user,
            "tokens": tokens,
            "businesses": businesses,
            "active_business": active,
            "permissions": perms,
            "is_new_user": is_new_user,
        }

    # ── internals ────────────────────────────────────────────────
    async def _find_by_identifier(self, identifier: str) -> User | None:
        value = identifier.strip()
        if is_phone_like(value):
            return await self._find_by_phone(normalise_phone(value) or value)
        return await self._find_by_email(value.lower())

    async def _find_by_email(self, email: str) -> User | None:
        return (
            await self.db.execute(
                select(User).where(
                    func.lower(User.email) == email.lower(), User.is_deleted.is_(False)
                ).limit(1)
            )
        ).scalar_one_or_none()

    async def _find_by_phone(self, phone: str) -> User | None:
        return (
            await self.db.execute(
                select(User).where(User.phone == phone, User.is_deleted.is_(False)).limit(1)
            )
        ).scalar_one_or_none()

    async def _role_for(self, user_id: str, business_id: str) -> str | None:
        return (
            await self.db.execute(
                select(BusinessMember.role).where(
                    BusinessMember.user_id == user_id,
                    BusinessMember.business_id == business_id,
                    BusinessMember.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def _first_membership(self, user_id: str) -> tuple[str | None, str | None]:
        row = (
            await self.db.execute(
                select(BusinessMember.business_id, BusinessMember.role)
                .where(BusinessMember.user_id == user_id, BusinessMember.is_active.is_(True))
                .order_by(BusinessMember.created_at)
                .limit(1)
            )
        ).one_or_none()
        return (row[0], row[1]) if row else (None, None)

    async def _prune_sessions(self, user_id: str, keep: int = 10) -> None:
        sessions = list(
            (
                await self.db.execute(
                    select(UserSession)
                    .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
                    .order_by(UserSession.created_at.desc())
                )
            ).scalars().all()
        )
        for stale in sessions[keep:]:
            stale.revoked_at = utcnow()

    async def _deliver_otp(self, target: str, code: str, channel: str) -> bool:
        if settings.OTP_DEV_MODE:
            log.warning("auth.otp_dev_mode", identifier=_mask(target), code=code)
            return False
        try:
            if channel == "email":
                from app.integrations.email import EmailSender  # noqa: PLC0415

                return await EmailSender().send_plain(
                    target,
                    f"Your {settings.APP_NAME} verification code",
                    f"Your verification code is {code}. It expires in "
                    f"{settings.OTP_TTL_SECONDS // 60} minutes.",
                )
            from app.integrations.sms import SmsSender  # noqa: PLC0415

            return await SmsSender().send(
                target, f"{code} is your {settings.APP_NAME} verification code."
            )
        except Exception as exc:  # never leak delivery failures as auth failures
            log.error("auth.otp_delivery_failed", error=str(exc), channel=channel)
            return False


def _default_name(identifier: str) -> str:
    local = identifier.split("@")[0] if "@" in identifier else identifier
    return local.replace(".", " ").replace("_", " ").strip().title()[:60] or "User"


def _default_shop_name(user_name: str | None) -> str:
    """A placeholder the owner can rename in Settings → Shop details.

    Named after the person because "Ahmed's Shop" reads like a real shop on an
    invoice, whereas "My Business" reads like an app that was not set up.
    """
    first = (user_name or "").strip().split(" ")[0]
    return f"{first}'s Shop"[:200] if first else "My Shop"


def _mask(value: str) -> str:
    if "@" in value:
        from app.utils.strings import mask_email

        return mask_email(value)
    from app.utils.phone import mask_phone

    return mask_phone(value)
