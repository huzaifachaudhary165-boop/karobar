"""Registration, login, OTP, Google sign-in, sessions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, DbSession
from app.core.rate_limit import auth_limit
from app.schemas.auth import (
    AuthResponse, ChangePasswordRequest, GoogleAuthRequest, LoginRequest, OtpRequest,
    OtpSentResponse, OtpVerifyRequest, RefreshRequest, RegisterRequest, ResetPasswordRequest,
    SessionOut, SwitchBusinessRequest, UserOut,
)
from app.schemas.common import Message
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(auth_limit)])


def _ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED,
             summary="Create an account (optionally with a business)")
async def register(payload: RegisterRequest, request: Request, db: DbSession) -> AuthResponse:
    result = await AuthService(db).register(payload, ip=_ip(request))
    return AuthResponse.model_validate(result)


@router.post("/login", response_model=AuthResponse, summary="Sign in with a password")
async def login(payload: LoginRequest, request: Request, db: DbSession) -> AuthResponse:
    result = await AuthService(db).login(payload, ip=_ip(request))
    return AuthResponse.model_validate(result)


@router.post("/otp/send", response_model=OtpSentResponse, summary="Send a one-time code")
async def send_otp(payload: OtpRequest, db: DbSession) -> OtpSentResponse:
    return OtpSentResponse.model_validate(
        await AuthService(db).send_otp(payload.identifier, payload.purpose)
    )


@router.post("/otp/verify", response_model=AuthResponse,
             summary="Verify a code — signs in, or creates the account")
async def verify_otp(payload: OtpVerifyRequest, request: Request, db: DbSession) -> AuthResponse:
    result = await AuthService(db).verify_otp_login(
        payload.identifier, payload.code,
        purpose=payload.purpose, name=payload.name, device=payload.device, ip=_ip(request),
    )
    return AuthResponse.model_validate(result)


@router.post("/google", response_model=AuthResponse, summary="Sign in with Google")
async def google(payload: GoogleAuthRequest, request: Request, db: DbSession) -> AuthResponse:
    result = await AuthService(db).google_login(
        payload.id_token,
        device=payload.device,
        ip=_ip(request),
        business_name=payload.business_name,
        business_type=payload.business_type,
        country=payload.country,
    )
    return AuthResponse.model_validate(result)


@router.post("/refresh", response_model=AuthResponse, summary="Exchange a refresh token")
async def refresh(payload: RefreshRequest, request: Request, db: DbSession) -> AuthResponse:
    result = await AuthService(db).refresh(payload.refresh_token, ip=_ip(request))
    return AuthResponse.model_validate(result)


@router.post("/logout", response_model=Message, summary="End this session")
async def logout(
    payload: RefreshRequest | None, user: CurrentUser, db: DbSession
) -> Message:
    await AuthService(db).logout(payload.refresh_token if payload else None, user.id)
    return Message(message="Signed out.")


@router.post("/logout-all", response_model=Message, summary="End every session")
async def logout_all(user: CurrentUser, db: DbSession) -> Message:
    await AuthService(db).logout(None, user.id, all_devices=True)
    return Message(message="Signed out on all devices.")


@router.get("/me", response_model=UserOut, summary="The signed-in user")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/sessions", response_model=list[SessionOut], summary="Active sessions")
async def sessions(user: CurrentUser, db: DbSession) -> list[SessionOut]:
    rows = await AuthService(db).list_sessions(user.id)
    return [SessionOut.model_validate(r) for r in rows]


@router.delete("/sessions/{session_id}", response_model=Message, summary="Revoke a session")
async def revoke_session(session_id: str, user: CurrentUser, db: DbSession) -> Message:
    await AuthService(db).revoke_session(user.id, session_id)
    return Message(message="Session revoked.")


@router.post("/switch-business", response_model=AuthResponse, summary="Switch active business")
async def switch_business(
    payload: SwitchBusinessRequest, user: CurrentUser, db: DbSession
) -> AuthResponse:
    result = await AuthService(db).switch_business(user, payload.business_id)
    return AuthResponse.model_validate(result)


@router.post("/change-password", response_model=Message, summary="Change password")
async def change_password(
    payload: ChangePasswordRequest, user: CurrentUser, db: DbSession
) -> Message:
    await AuthService(db).change_password(user, payload.current_password, payload.new_password)
    return Message(message="Password changed. Please sign in again on your other devices.")


@router.post("/reset-password", response_model=Message, summary="Reset password with an OTP")
async def reset_password(payload: ResetPasswordRequest, db: DbSession) -> Message:
    await AuthService(db).reset_password(payload.identifier, payload.code, payload.new_password)
    return Message(message="Password reset. You can sign in now.")
