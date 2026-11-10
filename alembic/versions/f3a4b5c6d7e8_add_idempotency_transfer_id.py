"""add idempotency_keys.transfer_id: 출금이 커밋된 타행 이체를 Idempotency-Key에 묶는다

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-11-10

타행 이체는 출금을 커밋한 뒤 허브를 부른다. 그 사이에 요청이 취소되거나 오류가 나면 키를 풀었는데,
그러면 같은 키 재시도가 새 이체가 되어 두 번 출금됐다. 출금과 같은 트랜잭션에서 transfer_id를 적고,
transfer_id가 있는 키는 풀지 않는다. 기존 행은 NULL로 시작한다 (예전처럼 동작).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('idempotency_keys', sa.Column('transfer_id', sa.String(length=36), nullable=True))


def downgrade() -> None:
    op.drop_column('idempotency_keys', 'transfer_id')
