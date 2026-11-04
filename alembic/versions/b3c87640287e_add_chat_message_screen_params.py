"""add chat message screen params

Revision ID: b3c87640287e
Revises: eb4ae6c87077
Create Date: 2026-11-04 15:06:54.644167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c87640287e'
down_revision: Union[str, Sequence[str], None] = 'eb4ae6c87077'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chat_messages', sa.Column('screen_params', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_messages', 'screen_params')
