"""Pakistani sales tax: the monthly return and the register behind it."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Query, Response

from app.api.deps import DbSession, Tenant
from app.core.pakistan_tax import PROVINCIAL_AUTHORITIES, STANDARD_RATE
from app.core.permissions import Perm
from app.schemas.common import ORMModel
from app.services.fbr_service import FbrService
from app.utils.dates import month_bounds

router = APIRouter(prefix="/fbr", tags=["tax"])


class MonthlyReturn(ORMModel):
    enabled: bool
    period_start: date
    period_end: date
    ntn: str | None = None
    strn: str | None = None

    registered_sales: Decimal
    unregistered_sales: Decimal
    total_sales: Decimal

    output_tax: Decimal
    further_tax: Decimal
    input_tax: Decimal
    unclaimable_input_tax: Decimal

    net_payable: Decimal
    carried_forward: Decimal

    sale_count: int
    purchase_count: int
    provincial_authority: str | None = None


class TaxRates(ORMModel):
    """What the app suggests, not what it insists on."""

    standard_rate: Decimal
    further_tax_rate: Decimal
    provinces: dict[str, str]


@router.get("/rates", response_model=TaxRates, summary="Suggested rates")
async def rates(tenant: Tenant) -> TaxRates:
    """Defaults for a shop setting this up, not values it is held to.

    The standard rate has moved between 16, 17 and 18 percent inside a decade,
    so the shop's own setting is what bills — this is only what the form starts
    with.
    """
    tenant.require(Perm.SETTINGS_MANAGE)
    return TaxRates(
        standard_rate=STANDARD_RATE,
        further_tax_rate=Decimal("3"),
        provinces={key: value[1] for key, value in PROVINCIAL_AUTHORITIES.items()},
    )


@router.get("/return", response_model=MonthlyReturn, summary="The month's figures")
async def monthly_return(
    tenant: Tenant,
    db: DbSession,
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None, ge=2000, le=2100),
) -> MonthlyReturn:
    """What the return is filled in from. This app does not file it.

    Filing means an authenticated session on IRIS, and no app can honestly do
    that on a shop's behalf without holding their credentials.
    """
    tenant.require(Perm.REPORT_READ)
    today = date.today()
    start, end = month_bounds(date(year or today.year, month or today.month, 1))
    return MonthlyReturn(**await FbrService(db, tenant.actor).monthly_return(start, end))


@router.get("/annexure-c", response_class=Response, summary="Sales register as CSV")
async def annexure_c(
    tenant: Tenant,
    db: DbSession,
    month: int = Query(None, ge=1, le=12),
    year: int = Query(None, ge=2000, le=2100),
) -> Response:
    """Annexure C in the portal's own column order, so it can be pasted in
    rather than re-typed."""
    tenant.require(Perm.REPORT_EXPORT)
    today = date.today()
    start, end = month_bounds(date(year or today.year, month or today.month, 1))
    csv_text = await FbrService(db, tenant.actor).annexure_c_csv(start, end)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="annexure-c-{start:%Y-%m}.csv"'
            )
        },
    )
