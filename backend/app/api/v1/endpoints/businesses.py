"""Business profile, settings and team members."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, Tenant
from app.core.permissions import Perm, Role, assignable_roles, permissions_for
from app.models.business import Business, BusinessMember
from app.schemas.business import (
    BusinessCreate, BusinessOut, BusinessUpdate, InvoiceThemeOut, MemberInvite, MemberOut,
    MemberUpdate, SettingsOut, SettingsUpdate,
)
from app.schemas.common import Message
from app.services.business_service import BusinessService
from app.services.invoice_themes import DEFAULT_THEME, THEMES
from app.services.pdf_service import PdfService

router = APIRouter(prefix="/businesses", tags=["business"])


@router.get("", response_model=list[BusinessOut], summary="Businesses you belong to")
async def list_businesses(user: CurrentUser, db: DbSession) -> list[BusinessOut]:
    rows = (
        await db.execute(
            select(Business, BusinessMember.role, func.count(BusinessMember.id).over(
                partition_by=Business.id
            ))
            .join(BusinessMember, BusinessMember.business_id == Business.id)
            .where(
                BusinessMember.user_id == user.id,
                BusinessMember.is_active.is_(True),
                Business.is_deleted.is_(False),
            )
            .order_by(Business.created_at)
        )
    ).all()
    out = []
    for business, role, _count in rows:
        item = BusinessOut.model_validate(business)
        item.role = role
        out.append(item)
    return out


@router.post("", response_model=BusinessOut, status_code=status.HTTP_201_CREATED,
             summary="Create a business")
async def create_business(
    payload: BusinessCreate, user: CurrentUser, db: DbSession
) -> BusinessOut:
    business = await BusinessService(db).create_for_owner(
        user, payload.model_dump(exclude_unset=True)
    )
    if not user.active_business_id:
        user.active_business_id = business.id
    item = BusinessOut.model_validate(business)
    item.role = Role.OWNER
    return item


@router.get("/current", response_model=BusinessOut, summary="The active business")
async def current_business(tenant: Tenant, db: DbSession) -> BusinessOut:
    item = BusinessOut.model_validate(tenant.business)
    item.role = tenant.role
    item.member_count = len(tenant.business.members)
    return item


@router.patch("/current", response_model=BusinessOut, summary="Update the active business")
async def update_business(
    payload: BusinessUpdate, tenant: Tenant, db: DbSession
) -> BusinessOut:
    tenant.require(Perm.BUSINESS_UPDATE)
    business = await BusinessService(db).update(
        tenant.business.id, payload.model_dump(exclude_unset=True)
    )
    item = BusinessOut.model_validate(business)
    item.role = tenant.role
    return item


@router.get("/current/settings", response_model=SettingsOut, summary="Business settings")
async def get_settings(tenant: Tenant, db: DbSession) -> SettingsOut:
    return SettingsOut.model_validate(await BusinessService(db).settings(tenant.business.id))


@router.patch("/current/settings", response_model=SettingsOut, summary="Update settings")
async def update_settings(
    payload: SettingsUpdate, tenant: Tenant, db: DbSession
) -> SettingsOut:
    tenant.require(Perm.SETTINGS_MANAGE)
    cfg = await BusinessService(db).update_settings(
        tenant.business.id, payload.model_dump(exclude_unset=True)
    )
    return SettingsOut.model_validate(cfg)


@router.get("/invoice-themes", response_model=list[InvoiceThemeOut],
            summary="The looks an invoice can print in")
async def invoice_themes() -> list[InvoiceThemeOut]:
    """Fixed data, so no tenant and no permission check — every shop sees the
    same list, and the picker should load before anything else has."""
    return [
        InvoiceThemeOut(
            key=theme.key, name=theme.name, layout=theme.layout,
            accent=theme.accent, paper=theme.paper, density=theme.density,
            is_roll=theme.is_roll,
        )
        for theme in THEMES.values()
    ]


@router.get("/current/invoice-preview", response_class=Response,
            summary="A sample invoice in a chosen look")
async def invoice_preview(
    tenant: Tenant,
    db: DbSession,
    theme: str = Query(DEFAULT_THEME, max_length=32),
) -> Response:
    """Renders a made-up bill so a shop can see a look before committing to it.

    Sample data rather than a real invoice: a shop deciding how its bills
    should look may not have raised one yet, and a picker that shows nothing
    until they do is a picker that cannot be used on the day it matters.
    """
    tenant.require(Perm.SETTINGS_MANAGE)
    html = await PdfService(db, tenant.actor).render_sample(theme)
    return Response(content=html, media_type="text/html")


@router.get("/current/permissions", summary="What your role can do here")
async def my_permissions(tenant: Tenant) -> dict[str, object]:
    return {
        "role": tenant.role,
        "permissions": sorted(str(p) for p in permissions_for(tenant.role)),
        "assignable_roles": [str(r) for r in assignable_roles(tenant.role)],
    }


@router.get("/current/members", response_model=list[MemberOut], summary="Team members")
async def list_members(tenant: Tenant, db: DbSession) -> list[MemberOut]:
    tenant.require(Perm.MEMBER_MANAGE)
    rows = await BusinessService(db).list_members(tenant.business.id)
    return [MemberOut.model_validate(r) for r in rows]


@router.post("/current/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED,
             summary="Invite a team member")
async def invite_member(
    payload: MemberInvite, tenant: Tenant, db: DbSession
) -> MemberOut:
    tenant.require(Perm.MEMBER_MANAGE)
    row = await BusinessService(db).invite_member(
        tenant.business.id, tenant.role, payload.model_dump(exclude_unset=True)
    )
    return MemberOut.model_validate(row)


@router.patch("/current/members/{member_id}", response_model=Message, summary="Change a member's role")
async def update_member(
    member_id: str, payload: MemberUpdate, tenant: Tenant, db: DbSession
) -> Message:
    tenant.require(Perm.MEMBER_MANAGE)
    await BusinessService(db).update_member(
        tenant.business.id, member_id, tenant.role, payload.model_dump(exclude_unset=True)
    )
    return Message(message="Member updated.")


@router.delete("/current/members/{member_id}", response_model=Message, summary="Remove a member")
async def remove_member(member_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.MEMBER_MANAGE)
    await BusinessService(db).remove_member(tenant.business.id, member_id)
    return Message(message="Member removed.")
