"""add own account lookup (ClearingHub SPEC 9절: 가상 CI, 다른 은행 내 계좌)

Revision ID: d7e8f9a0b1c2
Revises: c4d1e2f3a5b6
Create Date: 2026-11-05 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c4d1e2f3a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('birth_date', sa.String(length=8), nullable=True))
    op.add_column('users', sa.Column('ci', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_users_ci'), 'users', ['ci'], unique=False)
    op.add_column('interbank_transfers', sa.Column('to_account_ref', sa.String(length=64), nullable=True))
    op.create_table('own_account_lookups',
    sa.Column('consent_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('hub_lookup_id', sa.String(length=36), nullable=True),
    sa.Column('account_count', sa.Integer(), nullable=False),
    sa.Column('consented_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
    sa.PrimaryKeyConstraint('consent_id')
    )
    op.create_index(op.f('ix_own_account_lookups_user_id'), 'own_account_lookups', ['user_id'], unique=False)
    op.create_table('own_account_refs',
    sa.Column('ref', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('consent_id', sa.String(length=64), nullable=False),
    sa.Column('bank_code', sa.String(length=3), nullable=False),
    sa.Column('bank_name', sa.String(length=50), nullable=False),
    sa.Column('account_masked', sa.String(length=50), nullable=False),
    sa.Column('product_name', sa.String(length=50), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['consent_id'], ['own_account_lookups.consent_id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
    sa.PrimaryKeyConstraint('ref')
    )
    op.create_index(op.f('ix_own_account_refs_user_id'), 'own_account_refs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_own_account_refs_user_id'), table_name='own_account_refs')
    op.drop_table('own_account_refs')
    op.drop_index(op.f('ix_own_account_lookups_user_id'), table_name='own_account_lookups')
    op.drop_table('own_account_lookups')
    op.drop_column('interbank_transfers', 'to_account_ref')
    op.drop_index(op.f('ix_users_ci'), table_name='users')
    op.drop_column('users', 'ci')
    op.drop_column('users', 'birth_date')
