"""llm configs, purposes, usage, profile documents and user profile

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-23 12:49:47.991699
"""
from alembic import op
import sqlalchemy as sa
import app.db

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('app_setting',
    sa.Column('key', sa.String(), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('llm_config',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('provider', sa.Enum('anthropic', 'openai', 'openai_compatible', name='llm_provider', native_enum=False, length=32), nullable=False),
    sa.Column('base_url', sa.String(), nullable=True),
    sa.Column('api_key', sa.String(), nullable=True),
    sa.Column('model', sa.String(), nullable=False),
    sa.Column('thinking', sa.Enum('off', 'low', 'medium', 'high', 'max', name='thinking_level', native_enum=False, length=32), nullable=False),
    sa.Column('supports_images', sa.Boolean(), nullable=False),
    sa.Column('extra_body', sa.JSON(), nullable=False),
    sa.Column('extra_headers', sa.JSON(), nullable=False),
    sa.Column('price_in', sa.Double(), nullable=True),
    sa.Column('price_out', sa.Double(), nullable=True),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', app.db.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('profile_document',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.String(), nullable=False),
    sa.Column('display_name', sa.String(), nullable=False),
    sa.Column('stored_path', sa.String(), nullable=False),
    sa.Column('mime', sa.String(), nullable=False),
    sa.Column('kind', sa.Enum('text', 'pdf_text', 'pdf_scan', 'image', name='document_kind', native_enum=False, length=32), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('text', sa.String(), nullable=True),
    sa.Column('text_source', sa.Enum('extracted', 'llm', 'manual', name='text_source', native_enum=False, length=32), nullable=True),
    sa.Column('created_at', app.db.UTCDateTime(), nullable=False),
    sa.Column('updated_at', app.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_profile',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('free_text', sa.String(), nullable=True),
    sa.Column('profile_markdown', sa.String(), nullable=True),
    sa.Column('generated_at', app.db.UTCDateTime(), nullable=True),
    sa.Column('edited_since_generation', sa.Boolean(), nullable=False),
    sa.Column('inputs_changed_since_generation', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', app.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('llm_purpose',
    sa.Column('purpose', sa.Enum('profile', 'fit', 'extraction', name='llm_purpose_kind', native_enum=False, length=32), nullable=False),
    sa.Column('config_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['config_id'], ['llm_config.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('purpose')
    )
    op.create_table('llm_usage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('at', app.db.UTCDateTime(), nullable=False),
    sa.Column('config_id', sa.Integer(), nullable=True),
    sa.Column('purpose', sa.String(), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('estimated', sa.Boolean(), nullable=False),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['config_id'], ['llm_config.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('llm_usage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_llm_usage_at'), ['at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('llm_usage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_llm_usage_at'))

    op.drop_table('llm_usage')
    op.drop_table('llm_purpose')
    op.drop_table('user_profile')
    op.drop_table('profile_document')
    op.drop_table('llm_config')
    op.drop_table('app_setting')
