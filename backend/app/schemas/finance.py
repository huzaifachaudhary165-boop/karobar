"""Account transfers, cheques and loans."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, model_validator

from app.models.enums import ChequeStatus, InterestType, LoanStatus, LoanType
from app.schemas.common import InputModel, MoneyField, ORMModel, SyncFields


# ── moving money between your own accounts ─────────────────────────
class TransferCreate(InputModel, SyncFields):
    from_account_id: str
    to_account_id: str
    amount: MoneyField = Field(gt=0)
    transfer_date: date | None = None
    charges: MoneyField = Field(Decimal("0"), ge=0)
    reference_number: str | None = Field(None, max_length=80)
    notes: str | None = None

    @model_validator(mode="after")
    def _different_accounts(self):
        if self.from_account_id == self.to_account_id:
            raise ValueError("Pick two different accounts to transfer between.")
        return self


class TransferOut(ORMModel):
    id: str
    from_account_id: str
    from_account_name: str | None = None
    to_account_id: str
    to_account_name: str | None = None
    amount: Decimal
    charges: Decimal
    total_debited: Decimal
    transfer_date: date
    reference_number: str | None = None
    notes: str | None = None
    created_at: datetime


# ── cheques ────────────────────────────────────────────────────────
class ChequeOut(ORMModel):
    id: str
    number: str
    direction: str
    party_id: str | None = None
    party_name: str | None = None
    amount: Decimal
    payment_date: date
    cheque_date: date | None = None
    cheque_status: str | None = None
    reference_number: str | None = None
    account_id: str | None = None
    notes: str | None = None
    is_overdue: bool = False
    days_until_due: int | None = None


class ChequeStatusUpdate(InputModel):
    status: ChequeStatus
    note: str | None = Field(None, max_length=300)


class ChequeSummary(ORMModel):
    to_deposit_count: int
    to_deposit_amount: Decimal
    to_clear_count: int
    to_clear_amount: Decimal
    overdue_count: int


# ── loans ──────────────────────────────────────────────────────────
class LoanCreate(InputModel, SyncFields):
    lender_name: str = Field(min_length=1, max_length=200)
    loan_type: LoanType = LoanType.BANK
    account_number: str | None = Field(None, max_length=64)

    principal: MoneyField = Field(gt=0)
    interest_rate: MoneyField = Field(Decimal("0"), ge=0, le=100)
    interest_type: InterestType = InterestType.REDUCING
    tenure_months: int = Field(0, ge=0, le=600)
    emi_amount: MoneyField = Field(Decimal("0"), ge=0)

    start_date: date | None = None
    first_due_date: date | None = None
    account_id: str | None = None
    notes: str | None = None


class LoanUpdate(InputModel):
    lender_name: str | None = Field(None, min_length=1, max_length=200)
    loan_type: LoanType | None = None
    account_number: str | None = None
    interest_rate: MoneyField | None = Field(None, ge=0, le=100)
    interest_type: InterestType | None = None
    tenure_months: int | None = Field(None, ge=0, le=600)
    emi_amount: MoneyField | None = Field(None, ge=0)
    first_due_date: date | None = None
    notes: str | None = None


class LoanOut(ORMModel):
    id: str
    lender_name: str
    loan_type: str
    account_number: str | None = None

    principal: Decimal
    interest_rate: Decimal
    interest_type: str
    tenure_months: int
    emi_amount: Decimal

    start_date: date
    first_due_date: date | None = None
    account_id: str | None = None

    outstanding_principal: Decimal
    principal_paid: Decimal
    interest_paid: Decimal
    total_paid: Decimal = Decimal("0")

    status: str
    closed_on: date | None = None
    instalments_paid: int = 0
    instalments_left: int = 0
    next_due_date: date | None = None
    notes: str | None = None
    created_at: datetime


class LoanPaymentCreate(InputModel):
    amount: MoneyField = Field(gt=0)
    payment_date: date | None = None
    account_id: str | None = None
    reference_number: str | None = Field(None, max_length=80)
    notes: str | None = None


class LoanPaymentOut(ORMModel):
    id: str
    loan_id: str
    payment_date: date
    amount: Decimal
    principal_component: Decimal
    interest_component: Decimal
    balance_after: Decimal
    instalment_number: int | None = None
    account_id: str | None = None
    reference_number: str | None = None
    notes: str | None = None


class InstalmentOut(ORMModel):
    number: int
    due_date: date
    amount: Decimal
    principal: Decimal
    interest: Decimal
    balance_after: Decimal


class LoanSummary(ORMModel):
    active_count: int
    total_borrowed: Decimal
    total_outstanding: Decimal
    monthly_commitment: Decimal
    interest_paid: Decimal


class LoanStatusFilter(InputModel):
    status: LoanStatus | None = None
