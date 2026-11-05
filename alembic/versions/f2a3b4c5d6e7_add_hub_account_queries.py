"""add hub_account_queries: SPEC 9.4 lookup records from ClearingHub

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hub_account_queries',
        sa.Column('query_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ci', sa.String(length=64), nullable=False),
        sa.Column('account_count', sa.Integer(), nullable=False),
        sa.Column('queried_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('query_id'),
    )
    op.create_index(op.f('ix_hub_account_queries_ci'), 'hub_account_queries', ['ci'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hub_account_queries_ci'), table_name='hub_account_queries')
    op.drop_table('hub_account_queries')
