"""posting_fit

Revision ID: 0004_posting_fit
Revises: 0003
Create Date: 2026-10-24 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
import app.db

revision = '0004_posting_fit'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('posting_fit',
    sa.Column('posting_id', sa.Integer(), nullable=False),
    sa.Column('rating', sa.Enum('good', 'moderate', 'poor', name='fit_rating', native_enum=False, create_constraint=False, length=32), nullable=True),
    sa.Column('explanation', sa.String(), nullable=True),
    sa.Column('status', sa.Enum('queued', 'running', 'done', 'error', name='fit_status', native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('error', sa.String(), nullable=True),
    sa.Column('profile_version', sa.Integer(), nullable=True),
    sa.Column('evaluated_at', app.db.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['posting_id'], ['job_posting.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('posting_id')
    )


def downgrade() -> None:
    op.drop_table('posting_fit')
