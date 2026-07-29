"""Role-based access control. Roles are per-business, not global."""

from __future__ import annotations

from enum import StrEnum

from app.core.errors import PermissionError_


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ACCOUNTANT = "accountant"
    SALESMAN = "salesman"
    STOREKEEPER = "storekeeper"
    VIEWER = "viewer"


class Perm(StrEnum):
    # business
    BUSINESS_UPDATE = "business:update"
    BUSINESS_DELETE = "business:delete"
    MEMBER_MANAGE = "member:manage"
    SETTINGS_MANAGE = "settings:manage"
    # masters
    PARTY_READ = "party:read"
    PARTY_WRITE = "party:write"
    PARTY_DELETE = "party:delete"
    ITEM_READ = "item:read"
    ITEM_WRITE = "item:write"
    ITEM_DELETE = "item:delete"
    # transactions
    SALE_READ = "sale:read"
    SALE_WRITE = "sale:write"
    SALE_DELETE = "sale:delete"
    PURCHASE_READ = "purchase:read"
    PURCHASE_WRITE = "purchase:write"
    PURCHASE_DELETE = "purchase:delete"
    PAYMENT_READ = "payment:read"
    PAYMENT_WRITE = "payment:write"
    EXPENSE_READ = "expense:read"
    EXPENSE_WRITE = "expense:write"
    STOCK_ADJUST = "stock:adjust"
    # insight
    REPORT_READ = "report:read"
    REPORT_EXPORT = "report:export"
    AI_USE = "ai:use"
    INTEGRATION_MANAGE = "integration:manage"


_ALL = set(Perm)

_READ_ONLY = {
    Perm.PARTY_READ, Perm.ITEM_READ, Perm.SALE_READ, Perm.PURCHASE_READ,
    Perm.PAYMENT_READ, Perm.EXPENSE_READ, Perm.REPORT_READ,
}

ROLE_PERMISSIONS: dict[Role, set[Perm]] = {
    Role.OWNER: _ALL,
    Role.ADMIN: _ALL - {Perm.BUSINESS_DELETE},
    Role.ACCOUNTANT: _READ_ONLY | {
        Perm.PARTY_WRITE, Perm.ITEM_WRITE, Perm.SALE_WRITE, Perm.PURCHASE_WRITE,
        Perm.PAYMENT_WRITE, Perm.EXPENSE_WRITE, Perm.REPORT_EXPORT, Perm.AI_USE,
    },
    Role.SALESMAN: _READ_ONLY - {Perm.PURCHASE_READ, Perm.EXPENSE_READ, Perm.REPORT_READ} | {
        Perm.PARTY_WRITE, Perm.SALE_WRITE, Perm.PAYMENT_WRITE, Perm.AI_USE,
    },
    Role.STOREKEEPER: {
        Perm.ITEM_READ, Perm.ITEM_WRITE, Perm.STOCK_ADJUST, Perm.PARTY_READ,
        Perm.PURCHASE_READ, Perm.PURCHASE_WRITE, Perm.AI_USE,
    },
    Role.VIEWER: set(_READ_ONLY),
}


def permissions_for(role: str | Role) -> set[Perm]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return set()


def has_permission(role: str | Role, perm: Perm) -> bool:
    return perm in permissions_for(role)


def require_permission(role: str | Role, perm: Perm) -> None:
    if not has_permission(role, perm):
        raise PermissionError_(
            f"Your role ({role}) cannot perform this action.",
            details={"required_permission": str(perm), "role": str(role)},
        )


def assignable_roles(actor_role: str | Role) -> list[Role]:
    """Owners may assign anything; admins may not mint another owner."""
    if Role(actor_role) is Role.OWNER:
        return list(Role)
    if Role(actor_role) is Role.ADMIN:
        return [r for r in Role if r is not Role.OWNER]
    return []
