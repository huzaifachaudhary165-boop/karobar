"""Account transfers, cheque tracking and loans."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, Tenant
from app.core.loan_maths import add_months
from app.core.permissions import Perm
from app.models.enums import PaymentDirection
from app.schemas.common import Message
from app.schemas.finance import (
    ChequeOut, ChequeStatusUpdate, ChequeSummary, InstalmentOut, LoanCreate, LoanOut,
    LoanPaymentCreate, LoanPaymentOut, LoanSummary, LoanUpdate, TransferCreate, TransferOut,
)
from app.services.finance_service import ChequeService, LoanService, TransferService

router = APIRouter(prefix="/finance", tags=["finance"])


def _transfer(row, source_name: str | None = None, target_name: str | None = None) -> TransferOut:
    out = TransferOut.model_validate(row)
    out.total_debited = row.total_debited
    out.from_account_name = source_name
    out.to_account_name = target_name
    return out


def _cheque(payment) -> ChequeOut:
    out = ChequeOut.model_validate(payment)
    if payment.cheque_date:
        out.days_until_due = (payment.cheque_date - date.today()).days
        out.is_overdue = payment.cheque_date < date.today()
    return out


def _loan(loan) -> LoanOut:
    out = LoanOut.model_validate(loan)
    out.total_paid = loan.total_paid
    out.instalments_left = loan.instalments_left
    if loan.first_due_date and loan.tenure_months and not loan.is_settled:
        out.next_due_date = add_months(loan.first_due_date, loan.instalments_paid)
    return out


# ── transfers ──────────────────────────────────────────────────────
@router.get("/transfers", response_model=list[TransferOut], summary="Money moved between accounts")
async def list_transfers(
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    account_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[TransferOut]:
    tenant.require(Perm.PAYMENT_READ)
    rows = await TransferService(db, tenant.actor).list(
        start=start_date, end=end_date, account_id=account_id, limit=limit
    )
    return [_transfer(row, source.name, target.name) for row, source, target in rows]


@router.post("/transfers", response_model=TransferOut, status_code=status.HTTP_201_CREATED,
             summary="Move money between your own accounts")
async def create_transfer(payload: TransferCreate, tenant: Tenant, db: DbSession) -> TransferOut:
    tenant.require(Perm.PAYMENT_WRITE)
    row = await TransferService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return _transfer(row)


@router.delete("/transfers/{transfer_id}", response_model=Message, summary="Undo a transfer")
async def delete_transfer(transfer_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.PAYMENT_WRITE)
    await TransferService(db, tenant.actor).delete(transfer_id)
    return Message(message="Transfer removed and both balances put back.")


# ── cheques ────────────────────────────────────────────────────────
@router.get("/cheques", response_model=list[ChequeOut], summary="Cheques in hand")
async def list_cheques(
    tenant: Tenant,
    db: DbSession,
    cheque_status: str | None = Query(
        None, pattern="^(pending|deposited|cleared|bounced|cancelled)$"
    ),
    direction: PaymentDirection | None = None,
    due_before: date | None = None,
    limit: int = Query(200, ge=1, le=500),
) -> list[ChequeOut]:
    """Open cheques by default — the ones a shop still has to act on."""
    tenant.require(Perm.PAYMENT_READ)
    rows = await ChequeService(db, tenant.actor).list(
        status=cheque_status, direction=direction, due_before=due_before, limit=limit
    )
    return [_cheque(p) for p in rows]


@router.get("/cheques/summary", response_model=ChequeSummary, summary="Cheque position")
async def cheque_summary(tenant: Tenant, db: DbSession) -> ChequeSummary:
    tenant.require(Perm.PAYMENT_READ)
    return ChequeSummary(**await ChequeService(db, tenant.actor).summary())


@router.patch("/cheques/{payment_id}", response_model=ChequeOut, summary="Deposit, clear or bounce")
async def update_cheque(
    payment_id: str, payload: ChequeStatusUpdate, tenant: Tenant, db: DbSession
) -> ChequeOut:
    """The account balance only moves when the bank settles it either way."""
    tenant.require(Perm.PAYMENT_WRITE)
    row = await ChequeService(db, tenant.actor).set_status(
        payment_id, payload.status, note=payload.note
    )
    return _cheque(row)


# ── loans ──────────────────────────────────────────────────────────
@router.get("/loans", response_model=list[LoanOut], summary="Loans")
async def list_loans(
    tenant: Tenant,
    db: DbSession,
    loan_status: str | None = Query(None, pattern="^(active|closed|defaulted)$"),
) -> list[LoanOut]:
    tenant.require(Perm.PAYMENT_READ)
    return [_loan(loan) for loan in await LoanService(db, tenant.actor).list(status=loan_status)]


@router.post("/loans", response_model=LoanOut, status_code=status.HTTP_201_CREATED,
             summary="Record a loan")
async def create_loan(payload: LoanCreate, tenant: Tenant, db: DbSession) -> LoanOut:
    tenant.require(Perm.PAYMENT_WRITE)
    return _loan(await LoanService(db, tenant.actor).create(payload.model_dump(exclude_unset=True)))


@router.get("/loans/summary", response_model=LoanSummary, summary="What is owed overall")
async def loan_summary(tenant: Tenant, db: DbSession) -> LoanSummary:
    tenant.require(Perm.PAYMENT_READ)
    return LoanSummary(**await LoanService(db, tenant.actor).summary())


@router.get("/loans/due", response_model=list[LoanOut], summary="Instalments coming up")
async def loans_due(
    tenant: Tenant, db: DbSession, within_days: int = Query(7, ge=0, le=90)
) -> list[LoanOut]:
    tenant.require(Perm.PAYMENT_READ)
    return [_loan(loan) for loan in await LoanService(db, tenant.actor).due_soon(within_days=within_days)]


@router.get("/loans/{loan_id}", response_model=LoanOut, summary="Get one loan")
async def get_loan(loan_id: str, tenant: Tenant, db: DbSession) -> LoanOut:
    tenant.require(Perm.PAYMENT_READ)
    return _loan(await LoanService(db, tenant.actor).get_or_404(loan_id))


@router.patch("/loans/{loan_id}", response_model=LoanOut, summary="Update a loan")
async def update_loan(
    loan_id: str, payload: LoanUpdate, tenant: Tenant, db: DbSession
) -> LoanOut:
    tenant.require(Perm.PAYMENT_WRITE)
    row = await LoanService(db, tenant.actor).update(loan_id, payload.model_dump(exclude_unset=True))
    return _loan(row)


@router.delete("/loans/{loan_id}", response_model=Message, summary="Delete a loan")
async def delete_loan(loan_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.PAYMENT_WRITE)
    await LoanService(db, tenant.actor).delete(loan_id)
    return Message(message="Loan deleted.")


@router.get("/loans/{loan_id}/schedule", response_model=list[InstalmentOut],
            summary="The full repayment plan")
async def loan_schedule(loan_id: str, tenant: Tenant, db: DbSession) -> list[InstalmentOut]:
    tenant.require(Perm.PAYMENT_READ)
    rows = await LoanService(db, tenant.actor).schedule_for(loan_id)
    return [
        InstalmentOut(
            number=r.number, due_date=r.due_date, amount=r.amount,
            principal=r.principal, interest=r.interest, balance_after=r.balance_after,
        )
        for r in rows
    ]


@router.get("/loans/{loan_id}/payments", response_model=list[LoanPaymentOut],
            summary="Repayments made")
async def loan_payments(loan_id: str, tenant: Tenant, db: DbSession) -> list[LoanPaymentOut]:
    tenant.require(Perm.PAYMENT_READ)
    rows = await LoanService(db, tenant.actor).payments_for(loan_id)
    return [LoanPaymentOut.model_validate(r) for r in rows]


@router.post("/loans/{loan_id}/payments", response_model=LoanPaymentOut,
             status_code=status.HTTP_201_CREATED, summary="Record a repayment")
async def record_loan_payment(
    loan_id: str, payload: LoanPaymentCreate, tenant: Tenant, db: DbSession
) -> LoanPaymentOut:
    """Split into principal and interest — only the interest is an expense."""
    tenant.require(Perm.PAYMENT_WRITE)
    row = await LoanService(db, tenant.actor).record_payment(
        loan_id, payload.model_dump(exclude_unset=True)
    )
    return LoanPaymentOut.model_validate(row)


@router.delete("/loans/{loan_id}/payments/{payment_id}", response_model=Message,
               summary="Undo a repayment")
async def delete_loan_payment(
    loan_id: str, payment_id: str, tenant: Tenant, db: DbSession
) -> Message:
    tenant.require(Perm.PAYMENT_WRITE)
    await LoanService(db, tenant.actor).delete_payment(loan_id, payment_id)
    return Message(message="Repayment removed and the balance put back.")
