"""add interbank_ledger: 타행 송금 중간 계정·은행별 정산 계정 분개

Revision ID: a8b9c0d1e2f3
Revises: f2a3b4c5d6e7
Create Date: 2026-11-06

이미 있는 타행 거래(interbank_transfers, interbank_receipts)도 분개로 채워 넣어,
배포 직후부터 대사(내부 계정 잔액 = 거래 기록)가 맞게 한다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = "(transfer_id, account, bank_code, event, amount, created_at)"


def upgrade() -> None:
    op.create_table(
        'interbank_ledger',
        sa.Column('entry_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('transfer_id', sa.String(length=36), nullable=False),
        sa.Column('account', sa.String(length=30), nullable=False),
        sa.Column('bank_code', sa.String(length=3), nullable=False),
        sa.Column('event', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('entry_id'),
        sa.UniqueConstraint('transfer_id', 'event', 'account', name='uq_interbank_ledger_event'),
    )
    op.create_index(op.f('ix_interbank_ledger_transfer_id'), 'interbank_ledger', ['transfer_id'], unique=False)

    # 기존 거래 백필. 보낸 이체는 모두 출금됐으므로 DEBIT, 확정된 것은 COMPLETE 또는 REFUND를 더한다
    op.execute(f"""
        INSERT INTO interbank_ledger {COLUMNS}
        SELECT transfer_id, 'INTERBANK_SUSPENSE', to_bank, 'DEBIT', amount, created_at FROM interbank_transfers
    """)
    op.execute(f"""
        INSERT INTO interbank_ledger {COLUMNS}
        SELECT transfer_id, 'INTERBANK_SUSPENSE', to_bank, 'COMPLETE', -amount, COALESCE(finished_at, created_at)
        FROM interbank_transfers WHERE status = 'COMPLETED'
    """)
    op.execute(f"""
        INSERT INTO interbank_ledger {COLUMNS}
        SELECT transfer_id, 'INTERBANK_SETTLEMENT', to_bank, 'COMPLETE', amount, COALESCE(finished_at, created_at)
        FROM interbank_transfers WHERE status = 'COMPLETED'
    """)
    op.execute(f"""
        INSERT INTO interbank_ledger {COLUMNS}
        SELECT transfer_id, 'INTERBANK_SUSPENSE', to_bank, 'REFUND', -amount, COALESCE(finished_at, created_at)
        FROM interbank_transfers WHERE status = 'FAILED'
    """)
    op.execute(f"""
        INSERT INTO interbank_ledger {COLUMNS}
        SELECT transfer_id, 'INTERBANK_SETTLEMENT', from_bank, 'RECEIVE', -amount, received_at FROM interbank_receipts
    """)


def downgrade() -> None:
    op.drop_index(op.f('ix_interbank_ledger_transfer_id'), table_name='interbank_ledger')
    op.drop_table('interbank_ledger')
