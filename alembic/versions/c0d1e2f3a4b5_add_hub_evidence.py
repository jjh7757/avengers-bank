"""add hub_evidence: 허브와 주고받은 이체 요청·응답 원문 보관 (ClearingHub SPEC v1.0 2.5, 부인방지)

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-11-06

추가만 하는 표다 (고치거나 지우지 않는다). 배포 전 거래의 원문은 없으므로 백필하지 않는다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c0d1e2f3a4b5'
down_revision: Union[str, Sequence[str], None] = 'b9c0d1e2f3a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hub_evidence',
        sa.Column('evidence_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('transfer_id', sa.String(length=36), nullable=False),
        sa.Column('direction', sa.String(length=20), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=True),
        sa.Column('path', sa.String(length=200), nullable=True),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('headers_json', sa.JSON(), nullable=False),
        sa.Column('body', sa.LargeBinary(), nullable=False),
        sa.Column('signature_alg', sa.String(length=10), nullable=True),
        sa.Column('signature_valid', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('evidence_id'),
    )
    op.create_index(op.f('ix_hub_evidence_transfer_id'), 'hub_evidence', ['transfer_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hub_evidence_transfer_id'), table_name='hub_evidence')
    op.drop_table('hub_evidence')
