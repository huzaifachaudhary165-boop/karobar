"""Auth request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field, field_validator, model_validator

from app.core.security import password_strength_issues
from app.schemas.common import InputModel, ORMModel
from app.utils.phone import normalise_phone


class DeviceInfo(InputModel):
    device_id: str | None = Field(None, max_length=64)
    device_name: str | None = Field(None, max_length=160)
    platform: str | None = Field(None, max_length=32)
    app_version: str | None = Field(None, max_length=32)
    push_token: str | None = Field(None, max_length=300)


class RegisterRequest(InputModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    language: str = Field("en", pattern="^(en|ur|hi)$")
    # optional: create the first business in the same call
    business_name: str | None = Field(None, max_length=200)
    business_type: str | None = None
    country: str = "Pakistan"
    currency: str | None = None
    device: DeviceInfo | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalise_phone(v) if v else None

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        issues = password_strength_issues(v)
        if issues:
            raise ValueError(" ".join(issues))
        return v

    @model_validator(mode="after")
    def _identity_required(self):
        if not self.email and not self.phone:
            raise ValueError("Provide an email address or a phone number.")
        return self


class LoginRequest(InputModel):
    identifier: str = Field(min_length=3, max_length=255, description="Email or phone")
    password: str = Field(min_length=1, max_length=128)
    device: DeviceInfo | None = None


class OtpRequest(InputModel):
    identifier: str = Field(min_length=3, max_length=255)
    purpose: str = Field("login", pattern="^(login|register|reset_password|verify|sensitive)$")


class OtpVerifyRequest(InputModel):
    identifier: str = Field(min_length=3, max_length=255)
    code: str = Field(min_length=4, max_length=8)
    purpose: str = Field("login", pattern="^(login|register|reset_password|verify|sensitive)$")
    name: str | None = Field(None, max_length=160)  # used when the OTP creates the account
    device: DeviceInfo | None = None


class GoogleAuthRequest(InputModel):
    id_token: str = Field(min_length=20)
    device: DeviceInfo | None = None
    # Only used the first time this Google account signs in. Without a business
    # the app has nothing to scope data to, so one is always created — this just
    # lets the user name their own shop instead of getting a generated name.
    business_name: str | None = Field(None, min_length=2, max_length=200)
    business_type: str | None = None
    country: str = "Pakistan"


class RefreshRequest(InputModel):
    refresh_token: str = Field(min_length=20)


class SwitchBusinessRequest(InputModel):
    business_id: str


class ChangePasswordRequest(InputModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        issues = password_strength_issues(v)
        if issues:
            raise ValueError(" ".join(issues))
        return v


class ResetPasswordRequest(InputModel):
    identifier: str
    code: str = Field(min_length=4, max_length=8)
    new_password: str = Field(min_length=8, max_length=128)


class BusinessSummary(ORMModel):
    id: str
    name: str
    business_type: str
    logo_url: str | None = None
    currency: str
    currency_symbol: str
    role: str | None = None
    plan: str = "free"


class UserOut(ORMModel):
    id: str
    name: str
    email: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    email_verified: bool = False
    phone_verified: bool = False
    language: str = "en"
    timezone: str = "Asia/Karachi"
    active_business_id: str | None = None
    is_superuser: bool = False
    created_at: datetime


class TokenPair(ORMModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class AuthResponse(ORMModel):
    user: UserOut
    tokens: TokenPair
    businesses: list[BusinessSummary] = []
    active_business: BusinessSummary | None = None
    permissions: list[str] = []
    is_new_user: bool = False


class OtpSentResponse(ORMModel):
    message: str
    expires_in: int
    # only populated when OTP_DEV_MODE is on
    debug_code: str | None = None


class SessionOut(ORMModel):
    id: str
    device_name: str | None = None
    platform: str | None = None
    ip_address: str | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    is_current: bool = False
