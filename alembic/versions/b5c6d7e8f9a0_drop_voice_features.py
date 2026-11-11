"""drop voice_profiles, chat_messages.input_mode, fds_logs.input_mode: 음성 기능(TTS·STT·음성 승인) 제거

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-11-11

음성 입력·읽어 주기·목소리 승인(화자 인증)을 모두 뺐다. 등록된 목소리 특징(암호화 임베딩)은 더 쓸 곳이 없으므로
테이블째 지운다. 입력 방식(text/voice) 컬럼도 FDS 피처(is_voice)와 함께 없앴다.
downgrade는 빈 voice_profiles와 input_mode='text' 컬럼을 되살린다 (지운 데이터는 돌아오지 않는다).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, Sequence[str], None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('voice_profiles')
    with op.batch_alter_table('chat_messages') as batch_op:  # SQLite에서도 컬럼을 지울 수 있게
        batch_op.drop_column('input_mode')
    with op.batch_alter_table('fds_logs') as batch_op:
        batch_op.drop_column('input_mode')


def downgrade() -> None:
    op.add_column('fds_logs', sa.Column('input_mode', sa.String(length=10), server_default='text', nullable=False))
    op.add_column('chat_messages', sa.Column('input_mode', sa.String(length=10), server_default='text', nullable=False))
    op.create_table('voice_profiles',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('embedding_encrypted', sa.LargeBinary(), nullable=False),
    sa.Column('model_version', sa.String(length=100), nullable=False),
    sa.Column('consented_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
    sa.PrimaryKeyConstraint('user_id')
    )
