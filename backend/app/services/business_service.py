"""Business creation (with sensible starter data), members and settings."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, PermissionError_
from app.core.permissions import Role, assignable_roles
from app.models.base import utcnow
from app.models.business import Business, BusinessMember, BusinessSettings
from app.models.expense import ExpenseCategory, TaxRate
from app.models.item import Unit
from app.models.payment import Account
from app.models.user import User
from app.utils.phone import normalise_phone

# Starter masters so a new business is usable immediately, not an empty shell.
# What a shop is asked to pick from on the very first item it adds.
#
# The old list held twelve, all of them metric or retail, and a wholesaler was
# stuck the moment they tried to enter anything real: cloth is sold by the
# thaan, grain by the maund, timber by the cubic foot, marble by the square
# foot, and none of those could be typed at all. A unit a business cannot name
# is a business that cannot use the app.
#
# These are the ones actually spoken in Pakistani markets, English name first
# so the app can show it and the short form so the bill stays narrow. It is a
# starting point, not a limit — a shop adds its own from the item form, which
# is the part that matters for the trades nobody thought of.
DEFAULT_UNITS = [
    # Counted
    ("Pieces", "Pcs"), ("Dozen", "Dzn"), ("Pair", "Pair"), ("Set", "Set"),
    # Weight — maund and seer are still how grain, sugar and produce are traded
    ("Kilogram", "Kg"), ("Gram", "g"), ("Maund", "Maund"), ("Seer", "Seer"),
    ("Ton", "Ton"), ("Quintal", "Qtl"), ("Tola", "Tola"),
    # Volume
    ("Litre", "L"), ("Millilitre", "ml"), ("Drum", "Drum"),
    # Length and cloth
    ("Metre", "m"), ("Gaz / Yard", "Gaz"), ("Foot", "Ft"),
    ("Thaan", "Thaan"), ("Roll", "Roll"),
    # Area and volume — timber, marble, tiles, glass
    ("Square Foot", "Sqft"), ("Square Metre", "Sqm"),
    ("Cubic Foot", "Cft"), ("Running Foot", "Rft"),
    # Packing
    ("Box", "Box"), ("Carton", "Ctn"), ("Peti", "Peti"), ("Packet", "Pkt"),
    ("Bag", "Bag"), ("Bori", "Bori"), ("Bottle", "Btl"), ("Tin", "Tin"),
    ("Ream", "Ream"), ("Bundle", "Bnd"),
    # Sold as time
    ("Hour", "Hr"), ("Day", "Day"),
]

DEFAULT_EXPENSE_CATEGORIES = [
    ("Rent", "home", False), ("Salaries", "users", False), ("Utilities", "zap", False),
    ("Transport", "truck", True), ("Packaging", "package", True), ("Marketing", "megaphone", False),
    ("Repairs & Maintenance", "wrench", False), ("Office Supplies", "clipboard", False),
    ("Tea & Refreshments", "coffee", False), ("Bank Charges", "landmark", False),
    ("Miscellaneous", "more-horizontal", False),
]

TAX_PRESETS: dict[str, list[tuple[str, str]]] = {
    "india": [("GST 0%", "0"), ("GST 5%", "5"), ("GST 12%", "12"), ("GST 18%", "18"), ("GST 28%", "28")],
    "pakistan": [("Exempt 0%", "0"), ("Sales Tax 5%", "5"), ("Sales Tax 16%", "16"), ("Sales Tax 18%", "18")],
}

CURRENCY_BY_COUNTRY = {
    "pakistan": ("PKR", "Rs"), "india": ("INR", "₹"), "bangladesh": ("BDT", "৳"),
    "united arab emirates": ("AED", "د.إ"), "saudi arabia": ("SAR", "﷼"),
}


class BusinessService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_for_owner(self, owner: User, data: dict[str, Any]) -> Business:
        name = (data.get("name") or "").strip()
        if not name:
            raise BusinessRuleError("Business name is required.")

        country = (data.get("country") or "Pakistan").strip()
        currency, symbol = CURRENCY_BY_COUNTRY.get(country.lower(), ("PKR", "Rs"))

        business = Business(
            owner_id=owner.id,
            name=name,
            legal_name=data.get("legal_name"),
            business_type=data.get("business_type", "retail"),
            description=data.get("description"),
            phone=normalise_phone(data.get("phone")) if data.get("phone") else None,
            email=data.get("email"),
            website=data.get("website"),
            address_line1=data.get("address_line1"),
            address_line2=data.get("address_line2"),
            city=data.get("city"),
            state=data.get("state"),
            state_code=data.get("state_code"),
            pincode=data.get("pincode"),
            country=country,
            tax_type=data.get("tax_type", "none"),
            gstin=data.get("gstin"),
            ntn=data.get("ntn"),
            strn=data.get("strn"),
            pan=data.get("pan"),
            is_composite=data.get("is_composite", False),
            currency=data.get("currency") or currency,
            currency_symbol=data.get("currency_symbol") or symbol,
            financial_year_start_month=data.get(
                "financial_year_start_month", 7 if country.lower() == "pakistan" else 4
            ),
            book_start_date=data.get("book_start_date"),
            logo_url=data.get("logo_url"),
            theme_color=data.get("theme_color", "#F97316"),
        )
        self.db.add(business)
        await self.db.flush()

        self.db.add(
            BusinessMember(
                business_id=business.id,
                user_id=owner.id,
                role=Role.OWNER,
                invite_accepted_at=utcnow(),
            )
        )
        self.db.add(BusinessSettings(business_id=business.id))
        await self._seed_masters(business)
        await self.db.flush()
        return business

    async def _seed_masters(self, business: Business) -> None:
        for name, short in DEFAULT_UNITS:
            self.db.add(Unit(business_id=business.id, name=name, short_name=short))

        for order, (name, icon, direct) in enumerate(DEFAULT_EXPENSE_CATEGORIES):
            self.db.add(
                ExpenseCategory(
                    business_id=business.id, name=name, icon=icon,
                    is_direct_cost=direct, sort_order=order,
                )
            )

        presets = TAX_PRESETS.get(business.country.lower(), TAX_PRESETS["pakistan"])
        for name, rate in presets:
            r = Decimal(rate)
            self.db.add(
                TaxRate(
                    business_id=business.id, name=name, tax_type=business.tax_type or "gst",
                    rate=r, cgst_rate=r / 2, sgst_rate=r / 2, igst_rate=r,
                    is_default=(rate in ("17", "18")),
                )
            )

        self.db.add(
            Account(business_id=business.id, name="Cash", account_type="cash", is_default=True)
        )
        self.db.add(Account(business_id=business.id, name="Bank", account_type="bank"))

    async def get(self, business_id: str) -> Business:
        row = (
            await self.db.execute(
                select(Business).where(Business.id == business_id, Business.is_deleted.is_(False))
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Business not found.")
        return row

    async def update(self, business_id: str, data: dict[str, Any]) -> Business:
        business = await self.get(business_id)
        for key, value in data.items():
            if value is not None and hasattr(business, key) and key not in ("id", "owner_id", "created_at"):
                setattr(business, key, value)
        business.bump_revision()
        return business

    async def settings(self, business_id: str) -> BusinessSettings:
        row = (
            await self.db.execute(
                select(BusinessSettings).where(BusinessSettings.business_id == business_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = BusinessSettings(business_id=business_id)
            self.db.add(row)
            await self.db.flush()
        return row

    async def update_settings(self, business_id: str, data: dict[str, Any]) -> BusinessSettings:
        cfg = await self.settings(business_id)
        for key, value in data.items():
            if value is not None and hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg

    # ── members ──────────────────────────────────────────────────
    async def list_members(self, business_id: str) -> list[dict[str, Any]]:
        rows = (
            await self.db.execute(
                select(BusinessMember, User)
                .join(User, User.id == BusinessMember.user_id)
                .where(BusinessMember.business_id == business_id)
                .order_by(BusinessMember.created_at)
            )
        ).all()
        return [
            {
                "id": m.id, "user_id": m.user_id, "business_id": m.business_id,
                "role": m.role, "is_active": m.is_active, "name": u.name,
                "email": u.email, "phone": u.phone, "avatar_url": u.avatar_url,
                "invite_accepted_at": m.invite_accepted_at, "created_at": m.created_at,
            }
            for m, u in rows
        ]

    async def invite_member(
        self, business_id: str, actor_role: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        target_role = Role(data.get("role", "viewer"))
        if target_role not in assignable_roles(actor_role):
            raise PermissionError_(f"Your role cannot assign the '{target_role}' role.")

        email = (data.get("email") or "").lower() or None
        phone = normalise_phone(data.get("phone")) if data.get("phone") else None
        if not email and not phone:
            raise BusinessRuleError("Provide an email address or a phone number to invite someone.")

        user = (
            await self.db.execute(
                select(User).where(
                    (func.lower(User.email) == email) if email else (User.phone == phone)
                ).limit(1)
            )
        ).scalar_one_or_none()

        if user is None:
            # placeholder account; they set a password when they accept via OTP
            user = User(
                name=(data.get("name") or "").strip() or (email or phone or "Team member"),
                email=email, phone=phone,
            )
            self.db.add(user)
            await self.db.flush()

        existing = (
            await self.db.execute(
                select(BusinessMember).where(
                    BusinessMember.business_id == business_id, BusinessMember.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError("This person is already a member of the business.")

        member = BusinessMember(business_id=business_id, user_id=user.id, role=target_role)
        self.db.add(member)
        await self.db.flush()
        return {
            "id": member.id, "user_id": user.id, "business_id": business_id,
            "role": member.role, "is_active": member.is_active, "name": user.name,
            "email": user.email, "phone": user.phone, "avatar_url": user.avatar_url,
            "invite_accepted_at": None, "created_at": member.created_at,
        }

    async def update_member(
        self, business_id: str, member_id: str, actor_role: str, data: dict[str, Any]
    ) -> BusinessMember:
        member = (
            await self.db.execute(
                select(BusinessMember).where(
                    BusinessMember.id == member_id, BusinessMember.business_id == business_id
                )
            )
        ).scalar_one_or_none()
        if member is None:
            raise NotFoundError("Member not found.")

        if new_role := data.get("role"):
            if Role(new_role) not in assignable_roles(actor_role):
                raise PermissionError_(f"Your role cannot assign the '{new_role}' role.")
            if member.role == Role.OWNER and await self._owner_count(business_id) <= 1:
                raise BusinessRuleError("A business must always have at least one owner.")
            member.role = new_role

        if "is_active" in data and data["is_active"] is not None:
            if not data["is_active"] and member.role == Role.OWNER and await self._owner_count(business_id) <= 1:
                raise BusinessRuleError("The last owner cannot be deactivated.")
            member.is_active = data["is_active"]
        return member

    async def remove_member(self, business_id: str, member_id: str) -> None:
        member = (
            await self.db.execute(
                select(BusinessMember).where(
                    BusinessMember.id == member_id, BusinessMember.business_id == business_id
                )
            )
        ).scalar_one_or_none()
        if member is None:
            raise NotFoundError("Member not found.")
        if member.role == Role.OWNER and await self._owner_count(business_id) <= 1:
            raise BusinessRuleError("The last owner cannot be removed.")
        await self.db.delete(member)

    async def _owner_count(self, business_id: str) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count()).select_from(BusinessMember).where(
                        BusinessMember.business_id == business_id,
                        BusinessMember.role == Role.OWNER,
                        BusinessMember.is_active.is_(True),
                    )
                )
            ).scalar_one()
        )
