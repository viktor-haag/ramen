"""cover letters: templates, drafts and chat messages

Revision ID: 0007_cover_letters
Revises: 0006_profile_locations
Create Date: 2026-10-26 12:00:00.000000
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
import app.db
from app.latex.default_template import DEFAULT_TEMPLATE, DEFAULT_TEMPLATE_NAME

revision = '0007_cover_letters'
down_revision = '0006_profile_locations'
branch_labels = None
depends_on = None


def upgrade() -> None:
    templates = op.create_table('cover_letter_template',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('content', sa.String(), nullable=False),
    sa.Column('builtin', sa.Boolean(), nullable=False),
    sa.Column('created_at', app.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('cover_letter',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('format', sa.Enum('latex', 'text', name='cover_letter_format', native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=True),
    sa.Column('template_content', sa.String(), nullable=True),
    sa.Column('language', sa.Enum('posting', 'de', 'en', name='cover_letter_language', native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('context', sa.JSON(), nullable=False),
    sa.Column('content', sa.String(), nullable=False),
    sa.Column('status', sa.Enum('idle', 'generating', 'compiling', name='cover_letter_status', native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('error', sa.JSON(), nullable=True),
    sa.Column('compile_log', sa.String(), nullable=True),
    sa.Column('pdf_path', sa.String(), nullable=True),
    sa.Column('compiled_at', app.db.UTCDateTime(), nullable=True),
    sa.Column('created_at', app.db.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['application.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['template_id'], ['cover_letter_template.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('application_id')
    )
    op.create_table('cover_letter_message',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cover_letter_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.Enum('user', 'assistant', name='cover_letter_message_role', native_enum=False, create_constraint=False, length=32), nullable=False),
    sa.Column('text', sa.String(), nullable=False),
    sa.Column('created_at', app.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cover_letter_id'], ['cover_letter.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.bulk_insert(templates, [{
        'name': DEFAULT_TEMPLATE_NAME,
        'content': DEFAULT_TEMPLATE,
        'builtin': True,
        'created_at': datetime.now(timezone.utc),
    }])


def downgrade() -> None:
    op.drop_table('cover_letter_message')
    op.drop_table('cover_letter')
    op.drop_table('cover_letter_template')
