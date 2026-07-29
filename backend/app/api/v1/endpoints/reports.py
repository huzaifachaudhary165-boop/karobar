"""Dashboard and financial reports."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.api.deps import DbSession, Tenant
from app.core.permissions import Perm
from app.schemas.report import (
    AgeingReport, BalanceSheet, CashFlow, Daybook, DashboardSummary, ProfitAndLoss,
    SalesReport, TaxReport,
)
from app.services.party_service import PartyService
from app.services.report_service import ReportService
from app.services.summary_service import SummaryService
from app.utils.dates import resolve_period

router = APIRouter(prefix="/reports", tags=["reports"])


def _range(
    period: str, start: date | None, end: date | None, fy_start_month: int = 7
) -> tuple[date, date]:
    if start and end:
        return start, end
    return resolve_period(period, fy_start_month=fy_start_month)


@router.get("/dashboard", response_model=DashboardSummary, summary="Home dashboard")
async def dashboard(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("this_month"),
    compare: bool = True,
) -> DashboardSummary:
    tenant.require(Perm.REPORT_READ)
    return DashboardSummary.model_validate(
        await ReportService(db, tenant.actor).dashboard(period, compare=compare)
    )


@router.get("/profit-loss", response_model=ProfitAndLoss, summary="Profit & loss")
async def profit_loss(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("this_month"),
    start_date: date | None = None,
    end_date: date | None = None,
) -> ProfitAndLoss:
    tenant.require(Perm.REPORT_READ)
    start, end = _range(period, start_date, end_date, tenant.business.financial_year_start_month)
    return ProfitAndLoss.model_validate(
        await ReportService(db, tenant.actor).profit_and_loss(start, end)
    )


@router.get("/balance-sheet", response_model=BalanceSheet, summary="Balance sheet")
async def balance_sheet(
    tenant: Tenant, db: DbSession, as_of: date | None = None
) -> BalanceSheet:
    tenant.require(Perm.REPORT_READ)
    return BalanceSheet.model_validate(await ReportService(db, tenant.actor).balance_sheet(as_of))


@router.get("/sales", response_model=SalesReport, summary="Sales report")
async def sales_report(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("this_month"),
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: str = Query("day", pattern="^(day|week|month|quarter|year|party|status)$"),
    voucher_type: str = Query("sale", pattern="^(sale|purchase)$"),
) -> SalesReport:
    tenant.require(Perm.REPORT_READ)
    start, end = _range(period, start_date, end_date, tenant.business.financial_year_start_month)
    return SalesReport.model_validate(
        await ReportService(db, tenant.actor).sales_report(
            start, end, group_by=group_by, voucher_type=voucher_type
        )
    )


@router.get("/tax", response_model=TaxReport, summary="Tax summary (GSTR-style)")
async def tax_report(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("this_month"),
    start_date: date | None = None,
    end_date: date | None = None,
) -> TaxReport:
    tenant.require(Perm.REPORT_READ)
    start, end = _range(period, start_date, end_date, tenant.business.financial_year_start_month)
    return TaxReport.model_validate(await ReportService(db, tenant.actor).tax_report(start, end))


@router.get("/daybook", response_model=Daybook, summary="Daybook / cash book")
async def daybook(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("today"),
    start_date: date | None = None,
    end_date: date | None = None,
) -> Daybook:
    tenant.require(Perm.REPORT_READ)
    start, end = _range(period, start_date, end_date, tenant.business.financial_year_start_month)
    return Daybook.model_validate(await ReportService(db, tenant.actor).daybook(start, end))


@router.get("/cash-flow", response_model=CashFlow, summary="Cash flow")
async def cash_flow(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("this_month"),
    start_date: date | None = None,
    end_date: date | None = None,
) -> CashFlow:
    tenant.require(Perm.REPORT_READ)
    start, end = _range(period, start_date, end_date, tenant.business.financial_year_start_month)
    return CashFlow.model_validate(await ReportService(db, tenant.actor).cash_flow(start, end))


@router.get("/ageing", response_model=AgeingReport, summary="Receivable / payable ageing")
async def ageing(
    tenant: Tenant,
    db: DbSession,
    direction: str = Query("receivable", pattern="^(receivable|payable)$"),
    as_of: date | None = None,
) -> AgeingReport:
    tenant.require(Perm.REPORT_READ)
    data = await PartyService(db, tenant.actor).ageing(
        as_of=as_of, receivable=direction == "receivable"
    )
    return AgeingReport.model_validate(data)


@router.get("/top-items", summary="Best-selling items")
async def top_items(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("this_month"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict]:
    tenant.require(Perm.REPORT_READ)
    start, end = resolve_period(period, fy_start_month=tenant.business.financial_year_start_month)
    return await ReportService(db, tenant.actor).top_items(start, end, limit=limit)


@router.get("/top-parties", summary="Top customers")
async def top_parties(
    tenant: Tenant,
    db: DbSession,
    period: str = Query("this_month"),
    limit: int = Query(10, ge=1, le=50),
) -> list[dict]:
    tenant.require(Perm.REPORT_READ)
    start, end = resolve_period(period, fy_start_month=tenant.business.financial_year_start_month)
    return await ReportService(db, tenant.actor).top_parties(start, end, limit=limit)

@router.get("/daily-summary", summary="The end-of-day message")
async def daily_summary(
    tenant: Tenant,
    db: DbSession,
    day: date | None = Query(None, description="Defaults to today."),
) -> dict:
    """What the shop did today, in one readable message.

    Figures only — no model is involved. A daily number that is occasionally
    invented is worse than none, and this one has to be safe to act on.
    """
    tenant.require(Perm.REPORT_READ)
    return await SummaryService(db, tenant.actor).for_day(day)


@router.post("/daily-summary/send", summary="Send today's summary now")
async def send_daily_summary(
    tenant: Tenant,
    db: DbSession,
    day: date | None = Query(None),
) -> dict:
    """Delivers on WhatsApp and/or email, whichever is configured.

    Also the endpoint a nightly scheduler calls per business.
    """
    tenant.require(Perm.REPORT_READ)
    return await SummaryService(db, tenant.actor).send(day)
