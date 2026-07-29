"""Dashboard and report response schemas."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.schemas.common import InputModel, ORMModel, SeriesPoint, Trend


class ReportQuery(InputModel):
    period: str = "this_month"
    start_date: date | None = None
    end_date: date | None = None
    granularity: str | None = Field(None, pattern="^(day|week|month|quarter|year)$")
    party_id: str | None = None
    item_id: str | None = None
    category_id: str | None = None
    compare_previous: bool = True


class DashboardSummary(ORMModel):
    period_label: str
    start_date: date
    end_date: date
    currency_symbol: str = "Rs"

    sales: Trend
    purchases: Trend
    expenses: Trend
    profit: Trend
    collections: Trend

    receivable: Decimal = Decimal("0")
    payable: Decimal = Decimal("0")
    cash_in_hand: Decimal = Decimal("0")
    bank_balance: Decimal = Decimal("0")
    stock_value: Decimal = Decimal("0")

    invoice_count: int = 0
    unpaid_invoice_count: int = 0
    overdue_invoice_count: int = 0
    overdue_amount: Decimal = Decimal("0")
    new_party_count: int = 0
    low_stock_count: int = 0

    sales_series: list[SeriesPoint] = []
    top_items: list[dict[str, Any]] = []
    top_parties: list[dict[str, Any]] = []
    recent_activity: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []


class ProfitAndLoss(ORMModel):
    start_date: date
    end_date: date

    sales: Decimal = Decimal("0")
    sales_returns: Decimal = Decimal("0")
    net_sales: Decimal = Decimal("0")

    opening_stock: Decimal = Decimal("0")
    purchases: Decimal = Decimal("0")
    purchase_returns: Decimal = Decimal("0")
    closing_stock: Decimal = Decimal("0")
    cost_of_goods_sold: Decimal = Decimal("0")

    gross_profit: Decimal = Decimal("0")
    gross_margin_percent: Decimal = Decimal("0")

    direct_expenses: Decimal = Decimal("0")
    indirect_expenses: Decimal = Decimal("0")
    total_expenses: Decimal = Decimal("0")
    expense_breakdown: list[dict[str, Any]] = []

    other_income: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")
    net_margin_percent: Decimal = Decimal("0")


class BalanceSheet(ORMModel):
    as_of: date

    cash_and_bank: Decimal = Decimal("0")
    accounts_receivable: Decimal = Decimal("0")
    inventory: Decimal = Decimal("0")
    other_assets: Decimal = Decimal("0")
    total_assets: Decimal = Decimal("0")

    accounts_payable: Decimal = Decimal("0")
    tax_payable: Decimal = Decimal("0")
    other_liabilities: Decimal = Decimal("0")
    total_liabilities: Decimal = Decimal("0")

    capital: Decimal = Decimal("0")
    retained_earnings: Decimal = Decimal("0")
    total_equity: Decimal = Decimal("0")
    is_balanced: bool = True
    difference: Decimal = Decimal("0")


class SalesReportRow(ORMModel):
    label: str
    invoice_count: int = 0
    quantity: Decimal = Decimal("0")
    taxable: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    profit: Decimal = Decimal("0")
    margin_percent: Decimal | None = None


class SalesReport(ORMModel):
    start_date: date
    end_date: date
    group_by: str
    rows: list[SalesReportRow] = []
    totals: SalesReportRow
    series: list[SeriesPoint] = []


class AgeingBucket(ORMModel):
    label: str
    amount: Decimal = Decimal("0")
    count: int = 0


class AgeingReport(ORMModel):
    as_of: date
    direction: str = "receivable"
    total: Decimal = Decimal("0")
    buckets: list[AgeingBucket] = []
    parties: list[dict[str, Any]] = []


class TaxSummaryRow(ORMModel):
    rate: Decimal
    taxable: Decimal = Decimal("0")
    cgst: Decimal = Decimal("0")
    sgst: Decimal = Decimal("0")
    igst: Decimal = Decimal("0")
    cess: Decimal = Decimal("0")
    total_tax: Decimal = Decimal("0")
    invoice_count: int = 0


class TaxReport(ORMModel):
    start_date: date
    end_date: date
    output_tax: list[TaxSummaryRow] = []
    input_tax: list[TaxSummaryRow] = []
    total_output_tax: Decimal = Decimal("0")
    total_input_tax: Decimal = Decimal("0")
    net_payable: Decimal = Decimal("0")
    hsn_summary: list[dict[str, Any]] = []


class DaybookEntry(ORMModel):
    date: date
    entry_type: str
    reference_number: str | None = None
    party_name: str | None = None
    description: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    mode: str | None = None
    entity_id: str | None = None


class Daybook(ORMModel):
    start_date: date
    end_date: date
    opening_cash: Decimal = Decimal("0")
    closing_cash: Decimal = Decimal("0")
    total_in: Decimal = Decimal("0")
    total_out: Decimal = Decimal("0")
    entries: list[DaybookEntry] = []


class CashFlow(ORMModel):
    start_date: date
    end_date: date
    opening_balance: Decimal = Decimal("0")
    inflows: list[dict[str, Any]] = []
    outflows: list[dict[str, Any]] = []
    total_inflow: Decimal = Decimal("0")
    total_outflow: Decimal = Decimal("0")
    net_flow: Decimal = Decimal("0")
    closing_balance: Decimal = Decimal("0")
    series: list[SeriesPoint] = []


class ExportRequest(InputModel):
    report: str = Field(pattern="^(sales|purchases|parties|items|stock|expenses|pl|ledger|tax|daybook)$")
    format: str = Field("xlsx", pattern="^(xlsx|csv|pdf|json)$")
    period: str = "this_month"
    start_date: date | None = None
    end_date: date | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
