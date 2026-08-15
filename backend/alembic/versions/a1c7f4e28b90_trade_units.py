"""Give every existing shop the units its trade actually uses.

A new shop is seeded with the full list, but the shops that already exist were
seeded with the old twelve — all of them metric or retail. A wholesaler on one
of those accounts still cannot enter a real line: cloth is sold by the thaan,
grain by the maund, timber by the cubic foot, and none of them can be typed.

Adds only what a business is missing, matched on the short form and
case-insensitively, so a shop that has already added its own "Maund" keeps the
one it made. Nothing is renamed, nothing is removed, and no item is touched —
an item stores its unit as text, so this cannot change what anything is
measured in.

Revision ID: a1c7f4e28b90
Revises: 65a055b2caf6
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7f4e28b90"
down_revision: Union[str, None] = "65a055b2caf6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept here rather than imported from the service: a migration has to keep
# working after the application code moves on, and this is the list as it was
# on the day it ran.
UNITS: list[tuple[str, str]] = [
    ("Pieces", "Pcs"), ("Dozen", "Dzn"), ("Pair", "Pair"), ("Set", "Set"),
    ("Kilogram", "Kg"), ("Gram", "g"), ("Maund", "Maund"), ("Seer", "Seer"),
    ("Ton", "Ton"), ("Quintal", "Qtl"), ("Tola", "Tola"),
    ("Litre", "L"), ("Millilitre", "ml"), ("Drum", "Drum"),
    ("Metre", "m"), ("Gaz / Yard", "Gaz"), ("Foot", "Ft"),
    ("Thaan", "Thaan"), ("Roll", "Roll"),
    ("Square Foot", "Sqft"), ("Square Metre", "Sqm"),
    ("Cubic Foot", "Cft"), ("Running Foot", "Rft"),
    ("Box", "Box"), ("Carton", "Ctn"), ("Peti", "Peti"), ("Packet", "Pkt"),
    ("Bag", "Bag"), ("Bori", "Bori"), ("Bottle", "Btl"), ("Tin", "Tin"),
    ("Ream", "Ream"), ("Bundle", "Bnd"),
    ("Hour", "Hr"), ("Day", "Day"),
]


def upgrade() -> None:
    conn = op.get_bind()

    businesses = conn.execute(sa.text("SELECT id FROM businesses")).fetchall()
    if not businesses:
        return

    # `revision` is not nullable and the model default is Python-side only, so
    # a raw INSERT has to supply it. The offline client reads it to work out
    # what has changed since it last synced; a row without one would be
    # invisible to every phone.
    insert = sa.text(
        """
        INSERT INTO units (id, business_id, name, short_name, conversion_factor,
                           allow_decimal, is_deleted, revision, created_at, updated_at)
        VALUES (:id, :business_id, :name, :short_name, 1, true, false, 1, NOW(), NOW())
        """
    )

    for (business_id,) in businesses:
        existing = {
            row[0].strip().lower()
            for row in conn.execute(
                sa.text("SELECT short_name FROM units WHERE business_id = :b"),
                {"b": business_id},
            ).fetchall()
            if row[0]
        }

        for name, short in UNITS:
            if short.lower() in existing:
                continue
            conn.execute(
                insert,
                {
                    "id": str(uuid.uuid4()),
                    "business_id": business_id,
                    "name": name,
                    "short_name": short,
                },
            )


def downgrade() -> None:
    # Deliberately empty. Removing them would take a shop's own units with them
    # if any share a short form, and would break every item measured in one.
    # An unwanted unit is a row in a dropdown; a lost one is stock nobody can
    # count.
    pass
