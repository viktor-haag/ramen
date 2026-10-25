"""llm_config daily limit

Revision ID: 0005_llm_config_limit
Revises: 0004_posting_fit
Create Date: 2026-10-25 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_llm_config_limit'
down_revision = '0004_posting_fit'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('llm_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('daily_limit_kind', sa.String(), server_default='none', nullable=False))
        batch_op.add_column(sa.Column('daily_limit_value', sa.Double(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('llm_config', schema=None) as batch_op:
        batch_op.drop_column('daily_limit_value')
        batch_op.drop_column('daily_limit_kind')
