"""The two columns soft deletion needs on reminders.

`SoftDeleteMixin` was added to the model after the table was written, and it
brings three columns rather than one: `is_deleted`, `deleted_at` and
`deleted_by`. Only the first was in the migration, so every query against
reminders selected two columns that did not exist and the whole feature
answered 500 — on Postgres only. SQLite never saw it, because the tests build
their schema from the model rather than from the migrations.

That is the same trap as the FBR columns: a migration that passes on a fresh
database and fails on the real one. Worth naming again, because both times the
failure looked like a database outage rather than a missing column.

Revision ID: b3f1a90c7d55
Revises: a2313e0e2d34
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.core.types

revision: str = "b3f1a90c7d55"
down_revision: Union[str, None] = "a2313e0e2d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column("deleted_at", app.core.types.TZDateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "reminders",
        sa.Column("deleted_by", app.core.types.GUID(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reminders", "deleted_by")
    op.drop_column("reminders", "deleted_at")
