"""Users, sessions, OTP challenges."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, JSONType, LowerString, TZDateTime
from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.business import BusinessMember


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        UniqueConstraint("phone", name="uq_users_phone"),
        Index("ix_users_google_sub", "google_sub"),
    )

    # identity — at least one of email/phone is required (enforced in the service layer)
    email: Mapped[str | None] = mapped_column(LowerString(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # auth
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # state
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    # prefs
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)  # en | ur | hi
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi", nullable=False)
    active_business_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONType, default=dict, nullable=True)

    memberships: Mapped[list["BusinessMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_locked(self) -> bool:
        from app.models.base import utcnow

        return bool(self.locked_until and self.locked_until > utcnow())

    @property
    def display_identity(self) -> str:
        return self.email or self.phone or self.name


class UserSession(Base, UUIDMixin, TimestampMixin):
    """One row per refresh token so sessions can be listed and revoked individually."""

    __table_args__ = (Index("ix_user_sessions_user_active", "user_id", "revoked_at"),)

    user_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    device_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)  # android | ios | web
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    push_token: Mapped[str | None] = mapped_column(String(300), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")

    @property
    def is_valid(self) -> bool:
        from app.models.base import utcnow

        return self.revoked_at is None and self.expires_at > utcnow()


class OtpChallenge(Base, UUIDMixin, TimestampMixin):
    """Short-lived OTP for phone/email login and sensitive-action confirmation."""

    __table_args__ = (Index("ix_otp_identifier_purpose", "identifier", "purpose"),)

    identifier: Mapped[str] = mapped_column(String(255), nullable=False)  # phone or email
    channel: Mapped[str] = mapped_column(String(16), default="sms", nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), default="login", nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    @property
    def is_usable(self) -> bool:
        from app.models.base import utcnow

        return (
            self.consumed_at is None
            and self.attempts < self.max_attempts
            and self.expires_at > utcnow()
        )
