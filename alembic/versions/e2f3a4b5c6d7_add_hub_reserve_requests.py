"""add hub_reserve_requests: 허브 예치금 입금·인출 신청 (ClearingHub SPEC v1.3 10.9)

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-11-10

우리가 허브에 보낸 신청과 결정. 승인되면 interbank_ledger에 RESERVE_MOVE 분개(금고 현금 ↔ 예치금)를 남기고 booked_at을 찍는다.
기존 테이블은 바꾸지 않는다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('hub_reserve_requests',
    sa.Column('request_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('request_ref', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('memo', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('hub_request_id', sa.Integer(), nullable=True),
    sa.Column('reject_reason', sa.String(length=300), nullable=True),
    sa.Column('hub_balance_after', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('booked_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('request_id'),
    sa.UniqueConstraint('request_ref')
    )
    op.create_index(op.f('ix_hub_reserve_requests_status'), 'hub_reserve_requests', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hub_reserve_requests_status'), table_name='hub_reserve_requests')
    op.drop_table('hub_reserve_requests')
