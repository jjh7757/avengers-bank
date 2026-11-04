"""add chat message screen

Revision ID: eb4ae6c87077
Revises: faa91c27af1f
Create Date: 2026-11-04 14:23:23.539163

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb4ae6c87077'
down_revision: Union[str, Sequence[str], None] = 'faa91c27af1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chat_messages', sa.Column('screen', sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_messages', 'screen')
