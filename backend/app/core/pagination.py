"""Offset pagination helper used by every list endpoint."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = Field(1, ge=1, le=100_000)
    size: int = Field(25, ge=1, le=200)
    sort: str | None = None
    order: str = Field("desc", pattern="^(asc|desc)$")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def page_params(
    page: int = Query(1, ge=1, description="1-based page number"),
    size: int = Query(25, ge=1, le=200, description="Items per page (max 200)"),
    sort: str | None = Query(None, description="Column to sort by"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> PageParams:
    return PageParams(page=page, size=size, sort=sort, order=order)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int
    has_next: bool
    has_prev: bool

    @classmethod
    def build(cls, items: list[Any], total: int, params: PageParams) -> "Page[T]":
        pages = max(1, -(-total // params.size))  # ceil
        return cls(
            items=items,
            total=total,
            page=params.page,
            size=params.size,
            pages=pages,
            has_next=params.page < pages,
            has_prev=params.page > 1,
        )


async def paginate(
    db: AsyncSession,
    stmt: Select,
    params: PageParams,
    *,
    model: type | None = None,
    default_sort: str = "created_at",
) -> tuple[list[Any], int]:
    """Applies ORDER BY + LIMIT/OFFSET and returns (rows, total_count)."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    column_name = params.sort or default_sort
    if model is not None:
        column = getattr(model, column_name, None) or getattr(model, default_sort, None)
        if column is not None:
            stmt = stmt.order_by(column.asc() if params.order == "asc" else column.desc())

    rows = (await db.execute(stmt.offset(params.offset).limit(params.size))).scalars().unique().all()
    return list(rows), int(total)
