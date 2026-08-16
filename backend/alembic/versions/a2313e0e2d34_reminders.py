"""reminders

Revision ID: a2313e0e2d34
Revises: a1c7f4e28b90
Create Date: 2026-08-16 18:31:25.372142
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Autogenerate renders the project's portable column types (GUID, Money, JSONType,
# TZDateTime) fully qualified, so this import has to be present.
import app.core.types


revision: str = 'a2313e0e2d34'
down_revision: Union[str, None] = 'a1c7f4e28b90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('reminders',
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('due_at', app.core.types.TZDateTime(timezone=True), nullable=False),
    sa.Column('party_id', app.core.types.GUID(), nullable=True),
    sa.Column('party_name', sa.String(length=160), nullable=True),
    sa.Column('amount', sa.Numeric(precision=18, scale=4), nullable=True),
    # NOT NULL on a table that will have rows the moment anybody uses it, so a
    # server default rather than the model's Python-side one. Autogenerate does
    # not write these, and a migration missing one passes on an empty test
    # database and fails on the live one.
    sa.Column('is_done', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    sa.Column('done_at', app.core.types.TZDateTime(timezone=True), nullable=True),
    sa.Column('created_by', app.core.types.GUID(), nullable=True),
    sa.Column('id', app.core.types.GUID(), nullable=False),
    sa.Column('business_id', app.core.types.GUID(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    sa.Column('created_at', app.core.types.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', app.core.types.TZDateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_reminders_biz_due', 'reminders', ['business_id', 'is_done', 'due_at'], unique=False)
    op.create_index(op.f('ix_reminders_business_id'), 'reminders', ['business_id'], unique=False)
    op.create_index(op.f('ix_reminders_created_at'), 'reminders', ['created_at'], unique=False)
    op.create_index(op.f('ix_reminders_due_at'), 'reminders', ['due_at'], unique=False)
    op.create_index(op.f('ix_reminders_party_id'), 'reminders', ['party_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reminders_party_id'), table_name='reminders')
    op.drop_index(op.f('ix_reminders_due_at'), table_name='reminders')
    op.drop_index(op.f('ix_reminders_created_at'), table_name='reminders')
    op.drop_index(op.f('ix_reminders_business_id'), table_name='reminders')
    op.drop_index('ix_reminders_biz_due', table_name='reminders')
    op.drop_table('reminders')
