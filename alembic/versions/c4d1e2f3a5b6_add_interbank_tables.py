"""add interbank tables (ClearingHub 타행 이체)

Revision ID: c4d1e2f3a5b6
Revises: b107ad9d2c56
Create Date: 2026-11-05 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d1e2f3a5b6'
down_revision: Union[str, Sequence[str], None] = 'b107ad9d2c56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('interbank_transfers',
    sa.Column('transfer_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('checking_account_id', sa.Integer(), nullable=False),
    sa.Column('to_bank', sa.String(length=3), nullable=False),
    sa.Column('to_account', sa.String(length=50), nullable=False),
    sa.Column('to_holder_name', sa.String(length=50), nullable=True),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('memo', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('fail_code', sa.String(length=40), nullable=True),
    sa.Column('fail_message', sa.String(length=200), nullable=True),
    sa.Column('check_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['checking_account_id'], ['checking_accounts.checking_account_id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
    sa.PrimaryKeyConstraint('transfer_id')
    )
    op.create_index(op.f('ix_interbank_transfers_status'), 'interbank_transfers', ['status'], unique=False)
    op.create_index(op.f('ix_interbank_transfers_user_id'), 'interbank_transfers', ['user_id'], unique=False)
    op.create_table('interbank_receipts',
    sa.Column('transfer_id', sa.String(length=36), nullable=False),
    sa.Column('checking_account_id', sa.Integer(), nullable=False),
    sa.Column('from_bank', sa.String(length=3), nullable=False),
    sa.Column('from_bank_name', sa.String(length=50), nullable=False),
    sa.Column('from_account', sa.String(length=50), nullable=False),
    sa.Column('sender_name', sa.String(length=50), nullable=False),
    sa.Column('amount', sa.BigInteger(), nullable=False),
    sa.Column('memo', sa.String(length=100), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['checking_account_id'], ['checking_accounts.checking_account_id'], ),
    sa.PrimaryKeyConstraint('transfer_id')
    )
    op.create_index(op.f('ix_interbank_receipts_checking_account_id'), 'interbank_receipts', ['checking_account_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_interbank_receipts_checking_account_id'), table_name='interbank_receipts')
    op.drop_table('interbank_receipts')
    op.drop_index(op.f('ix_interbank_transfers_user_id'), table_name='interbank_transfers')
    op.drop_index(op.f('ix_interbank_transfers_status'), table_name='interbank_transfers')
    op.drop_table('interbank_transfers')
