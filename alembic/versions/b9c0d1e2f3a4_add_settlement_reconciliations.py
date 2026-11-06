"""add settlement_reconciliations, interbank_ledger.hub_run_id: 허브 정산 run 대사와 장부 정리 (SPEC 10.6)

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-11-06

기존 분개는 모두 hub_run_id가 NULL(아직 어느 run에서도 맞춰지지 않음)로 시작한다.
배포 뒤 첫 대사가 허브의 run을 처음부터 맞춰 본다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('interbank_ledger', sa.Column('hub_run_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_interbank_ledger_hub_run_id'), 'interbank_ledger', ['hub_run_id'], unique=False)
    op.create_table(
        'settlement_reconciliations',
        sa.Column('hub_run_id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('settle_date', sa.Date(), nullable=False),
        sa.Column('hub_status', sa.String(length=20), nullable=False),
        sa.Column('hub_net_amount', sa.BigInteger(), nullable=False),
        sa.Column('our_net_amount', sa.BigInteger(), nullable=False),
        sa.Column('result', sa.String(length=20), nullable=False),
        sa.Column('diff_json', sa.Text(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('hub_run_id'),
    )


def downgrade() -> None:
    op.drop_table('settlement_reconciliations')
    op.drop_index(op.f('ix_interbank_ledger_hub_run_id'), table_name='interbank_ledger')
    op.drop_column('interbank_ledger', 'hub_run_id')
