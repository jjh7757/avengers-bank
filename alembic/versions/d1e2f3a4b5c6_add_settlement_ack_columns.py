"""add settlement_reconciliations.acked_at·disputed_at: 대사 결과를 허브에 ack/dispute로 보낸 시각 (ClearingHub SPEC v1.1 10.8)

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-11-06

지금 허브에 걸려 있는 결과의 시각만 남는다 (ack를 보내면 disputed_at을 비우고, 그 반대도 같다).
기존 행은 둘 다 NULL로 시작한다. 그 run이 아직 DRAFT면 다음 대사 주기에 결과를 보낸다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c0d1e2f3a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('settlement_reconciliations', sa.Column('acked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('settlement_reconciliations', sa.Column('disputed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('settlement_reconciliations', 'disputed_at')
    op.drop_column('settlement_reconciliations', 'acked_at')
