"""FastAPI dependencies: authentication, tenant resolution and permission gates."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AuthenticationError, NotFoundError, PermissionError_
from app.core.logging import business_id_ctx, user_id_ctx
from app.core.permissions import Perm, require_permission
from app.core.security import TokenError, decode_token
from app.models.business import Business, BusinessMember
from app.models.user import User
from app.services.base import ActorContext

bearer = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Sign in to continue.")

    try:
        payload = decode_token(credentials.credentials, "access")
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    user = (
        await db.execute(
            select(User).where(User.id == payload["sub"], User.is_deleted.is_(False))
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AuthenticationError("This account is no longer active.")

    request.state.user_id = user.id
    request.state.token_business_id = payload.get("biz")
    request.state.token_role = payload.get("role")
    user_id_ctx.set(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


class TenantContext:
    """The authenticated caller *plus* the business they are acting in."""

    __slots__ = ("user", "business", "member", "role", "actor")

    def __init__(self, user: User, business: Business, member: BusinessMember) -> None:
        self.user = user
        self.business = business
        self.member = member
        self.role = member.role
        self.actor = ActorContext(
            user_id=user.id,
            user_name=user.name,
            business_id=business.id,
            role=member.role,
        )

    def require(self, permission: Perm) -> None:
        require_permission(self.role, permission)


async def get_tenant(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    x_business_id: Annotated[str | None, Header(alias="X-Business-Id")] = None,
    x_device_id: Annotated[str | None, Header(alias="X-Device-Id")] = None,
) -> TenantContext:
    """Resolve the active business.

    Header wins over the token so a multi-business user can switch without
    re-issuing a token; membership is verified either way.
    """
    business_id = x_business_id or getattr(request.state, "token_business_id", None) or user.active_business_id
    if not business_id:
        raise NotFoundError(
            "No business selected. Create one to get started.", code="no_business"
        )

    row = (
        await db.execute(
            select(Business, BusinessMember)
            .join(BusinessMember, BusinessMember.business_id == Business.id)
            .where(
                Business.id == business_id,
                Business.is_deleted.is_(False),
                BusinessMember.user_id == user.id,
                BusinessMember.is_active.is_(True),
            )
        )
    ).one_or_none()

    if row is None:
        raise PermissionError_("You do not have access to this business.")

    business, member = row
    if not business.is_active:
        raise PermissionError_("This business has been deactivated.")

    context = TenantContext(user, business, member)
    context.actor.device_id = x_device_id
    context.actor.ip = _client_ip(request)
    context.actor.user_agent = request.headers.get("user-agent")

    request.state.business_id = business.id
    business_id_ctx.set(business.id)
    return context


Tenant = Annotated[TenantContext, Depends(get_tenant)]


def requires(permission: Perm):
    """Route-level permission gate: `dependencies=[Depends(requires(Perm.SALE_WRITE))]`."""

    async def _check(tenant: Tenant) -> None:
        tenant.require(permission)

    return _check


async def get_optional_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
) -> User | None:
    """For endpoints that behave differently when signed in but do not require it."""
    if credentials is None:
        return None
    try:
        return await get_current_user(request, db, credentials)
    except AuthenticationError:
        return None


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
