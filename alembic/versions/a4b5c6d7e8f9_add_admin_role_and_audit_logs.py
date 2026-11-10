"""add users.role, admin_audit_logs: 관리자 계정과 관리자 행동 기록

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-11-10

users.role은 CUSTOMER/ADMIN. 기존 회원은 server_default로 모두 CUSTOMER가 된다. ADMIN은 서버 CLI로만 준다
(python -m avengers_bank.domains.admin.cli create-admin). admin_audit_logs는 관리자의 예치금 신청·취소·동기화를
성공·실패 모두 남긴다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, Sequence[str], None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('role', sa.String(length=10), server_default='CUSTOMER', nullable=False))
    op.create_table('admin_audit_logs',
    sa.Column('log_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('admin_user_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('target', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('result', sa.String(length=10), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('client_ip', sa.String(length=45), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['admin_user_id'], ['users.user_id'], ),
    sa.PrimaryKeyConstraint('log_id')
    )
    op.create_index(op.f('ix_admin_audit_logs_admin_user_id'), 'admin_audit_logs', ['admin_user_id'], unique=False)
    op.create_index(op.f('ix_admin_audit_logs_created_at'), 'admin_audit_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_admin_audit_logs_created_at'), table_name='admin_audit_logs')
    op.drop_index(op.f('ix_admin_audit_logs_admin_user_id'), table_name='admin_audit_logs')
    op.drop_table('admin_audit_logs')
    with op.batch_alter_table('users') as batch_op:  # SQLite에서도 컬럼을 지울 수 있게
        batch_op.drop_column('role')
