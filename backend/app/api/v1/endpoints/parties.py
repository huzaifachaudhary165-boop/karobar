"""Customers and suppliers."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, Tenant
from app.core.pagination import PageParams, page_params
from app.core.permissions import Perm
from app.schemas.common import Message, Paginated
from app.schemas.party import (
    PartyCreate, PartyGroupCreate, PartyGroupOut, PartyLedger, PartyListItem, PartyOut,
    PartyUpdate,
)
from app.services.party_service import PartyGroupService, PartyService

router = APIRouter(prefix="/parties", tags=["parties"])


def _out(party) -> PartyOut:
    data = PartyOut.model_validate(party)
    data.receivable = party.receivable
    data.payable = party.payable
    data.is_over_credit_limit = party.is_over_credit_limit
    data.group_name = party.group.name if party.group else None
    return data


@router.get("", response_model=Paginated[PartyListItem], summary="List parties")
async def list_parties(
    tenant: Tenant,
    db: DbSession,
    params: Annotated[PageParams, Depends(page_params)],
    search: str | None = Query(None, max_length=120),
    party_type: str | None = Query(None, pattern="^(customer|supplier|both|all)$"),
    group_id: str | None = None,
    only_with_balance: bool = False,
    only_receivable: bool = False,
    only_payable: bool = False,
    is_active: bool | None = None,
) -> Paginated[PartyListItem]:
    tenant.require(Perm.PARTY_READ)
    rows, total = await PartyService(db, tenant.actor).list(
        params,
        search=search,
        party_type=party_type,
        group_id=group_id,
        only_with_balance=only_with_balance,
        only_receivable=only_receivable,
        only_payable=only_payable,
        is_active=is_active,
    )
    items = []
    for party in rows:
        item = PartyListItem.model_validate(party)
        item.is_over_credit_limit = party.is_over_credit_limit
        items.append(item)
    return Paginated[PartyListItem](
        items=items, total=total, page=params.page, size=params.size,
        pages=max(1, -(-total // params.size)),
        has_next=params.page * params.size < total, has_prev=params.page > 1,
    )


@router.post("", response_model=PartyOut, status_code=status.HTTP_201_CREATED,
             summary="Add a customer or supplier")
async def create_party(payload: PartyCreate, tenant: Tenant, db: DbSession) -> PartyOut:
    tenant.require(Perm.PARTY_WRITE)
    return _out(await PartyService(db, tenant.actor).create(payload))


@router.get("/search", response_model=list[PartyListItem], summary="Fuzzy name search")
async def search_parties(
    tenant: Tenant, db: DbSession, q: str = Query(min_length=1, max_length=120), limit: int = 10
) -> list[PartyListItem]:
    tenant.require(Perm.PARTY_READ)
    matches = await PartyService(db, tenant.actor).search_by_name(q, limit=limit)
    return [PartyListItem.model_validate(p) for p, _score in matches]


@router.get("/ageing", summary="Receivable / payable ageing buckets")
async def ageing(
    tenant: Tenant,
    db: DbSession,
    direction: str = Query("receivable", pattern="^(receivable|payable)$"),
    as_of: date | None = None,
) -> dict:
    tenant.require(Perm.REPORT_READ)
    return await PartyService(db, tenant.actor).ageing(
        as_of=as_of, receivable=direction == "receivable"
    )


@router.get("/groups", response_model=list[PartyGroupOut], summary="Party groups")
async def list_groups(tenant: Tenant, db: DbSession) -> list[PartyGroupOut]:
    tenant.require(Perm.PARTY_READ)
    rows = await PartyGroupService(db, tenant.actor).list_with_counts()
    out = []
    for row in rows:
        item = PartyGroupOut.model_validate(row["group"])
        item.party_count = row["party_count"]
        out.append(item)
    return out


@router.post("/groups", response_model=PartyGroupOut, status_code=status.HTTP_201_CREATED,
             summary="Create a party group")
async def create_group(
    payload: PartyGroupCreate, tenant: Tenant, db: DbSession
) -> PartyGroupOut:
    tenant.require(Perm.PARTY_WRITE)
    group = await PartyGroupService(db, tenant.actor).create(payload.model_dump(exclude_unset=True))
    return PartyGroupOut.model_validate(group)


@router.get("/{party_id}", response_model=PartyOut, summary="Get one party")
async def get_party(party_id: str, tenant: Tenant, db: DbSession) -> PartyOut:
    tenant.require(Perm.PARTY_READ)
    return _out(await PartyService(db, tenant.actor).get_or_404(party_id))


@router.patch("/{party_id}", response_model=PartyOut, summary="Update a party")
async def update_party(
    party_id: str, payload: PartyUpdate, tenant: Tenant, db: DbSession
) -> PartyOut:
    tenant.require(Perm.PARTY_WRITE)
    return _out(await PartyService(db, tenant.actor).update(party_id, payload))


@router.delete("/{party_id}", response_model=Message, summary="Delete a party")
async def delete_party(party_id: str, tenant: Tenant, db: DbSession) -> Message:
    tenant.require(Perm.PARTY_DELETE)
    await PartyService(db, tenant.actor).delete(party_id)
    return Message(message="Party deleted.")


@router.get("/{party_id}/ledger", response_model=PartyLedger, summary="Statement of account")
async def party_ledger(
    party_id: str,
    tenant: Tenant,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PartyLedger:
    tenant.require(Perm.PARTY_READ)
    data = await PartyService(db, tenant.actor).ledger(party_id, start=start_date, end=end_date)
    return PartyLedger(
        party=PartyListItem.model_validate(data["party"]),
        opening_balance=data["opening_balance"],
        closing_balance=data["closing_balance"],
        total_debit=data["total_debit"],
        total_credit=data["total_credit"],
        entries=data["entries"],
        start_date=data["start_date"],
        end_date=data["end_date"],
    )


@router.post("/{party_id}/recalculate", response_model=PartyOut,
             summary="Rebuild the balance from source records")
async def recalculate(party_id: str, tenant: Tenant, db: DbSession) -> PartyOut:
    tenant.require(Perm.PARTY_WRITE)
    service = PartyService(db, tenant.actor)
    await service.recalculate_balance(party_id)
    return _out(await service.get_or_404(party_id))
