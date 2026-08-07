"""Making one thing out of others: recipes and the runs that use them."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID, Money, Quantity
from app.models.base import (
    AuditedMixin, Base, SoftDeleteMixin, SyncMixin, TenantMixin, TimestampMixin, UUIDMixin,
)


class BillOfMaterials(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin,
                      SyncMixin, AuditedMixin):
    """What goes into one batch of a finished item.

    Held per *batch size* rather than per unit. A tailor cuts twelve shirts
    from a roll, a baker gets forty rusks from one tray — asking for the flour
    per rusk turns a whole number into a recurring decimal that nobody can
    check against the recipe on the wall.
    """

    # Spelled out because the automatic naming would pluralise a word that is
    # already plural and land on "bill_of_materialses".
    __tablename__ = "bills_of_materials"

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_bom_name"),
        Index("ix_bom_item", "business_id", "item_id"),
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    item_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="CASCADE"), nullable=False
    )
    # How many finished units one run of this recipe produces.
    output_qty: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("1"), nullable=False)

    # Costs that are not materials but still belong in what a unit cost to make.
    labour_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    overhead_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    # What is lost to spillage, offcuts and burning, as a percentage of the
    # materials. Ignoring it prices every unit below what it really cost.
    wastage_percent: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    components: Mapped[list["BomComponent"]] = relationship(
        back_populates="bom", cascade="all, delete-orphan", lazy="selectin"
    )


class BomComponent(Base, UUIDMixin, TenantMixin, TimestampMixin, SyncMixin):
    """One raw material and how much of it a run needs."""

    __table_args__ = (
        UniqueConstraint("bom_id", "item_id", name="uq_bom_component"),
    )

    bom_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("bills_of_materials.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    qty: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    bom: Mapped["BillOfMaterials"] = relationship(back_populates="components")


class ProductionRun(Base, UUIDMixin, TenantMixin, TimestampMixin, SoftDeleteMixin,
                    SyncMixin, AuditedMixin):
    """One occasion of actually making the thing.

    Recorded rather than inferred: the recipe can change, and a run made last
    month under the old recipe must keep the cost it actually had. A finished
    unit's cost is a fact about the day it was made.
    """

    __table_args__ = (
        UniqueConstraint("business_id", "number", name="uq_production_number"),
        Index("ix_production_date", "business_id", "run_date"),
    )

    number: Mapped[str] = mapped_column(String(64), nullable=False)
    bom_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("bills_of_materials.id", ondelete="SET NULL"), nullable=True
    )
    item_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    item_name: Mapped[str] = mapped_column(String(240), nullable=False)

    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    qty: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)

    material_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    labour_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    overhead_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    wastage_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    godown_id: Mapped[str | None] = mapped_column(
        GUID(), ForeignKey("godowns.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    consumed: Mapped[list["ConsumedMaterial"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )


class ConsumedMaterial(Base, UUIDMixin, TenantMixin, TimestampMixin):
    """What one run actually used, at what it actually cost.

    The rate is copied rather than looked up later: the weighted-average cost
    of flour moves every time a sack is bought, and last month's biscuits did
    not get cheaper because this month's flour did.
    """

    __table_args__ = (Index("ix_consumed_run", "run_id"),)

    run_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("production_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item_id: Mapped[str] = mapped_column(
        GUID(), ForeignKey("items.id", ondelete="RESTRICT"), nullable=False
    )
    item_name: Mapped[str] = mapped_column(String(240), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    value: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)

    run: Mapped["ProductionRun"] = relationship(back_populates="consumed")
