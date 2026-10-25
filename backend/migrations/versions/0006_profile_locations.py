"""search profile: several cities

Revision ID: 0006_profile_locations
Revises: 0005_llm_config_limit
Create Date: 2026-10-25 12:00:00.000000
"""
import json

from alembic import op
import sqlalchemy as sa

revision = '0006_profile_locations'
down_revision = '0005_llm_config_limit'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, location FROM search_profile")).all()
    with op.batch_alter_table('search_profile', schema=None) as batch_op:
        batch_op.add_column(sa.Column('locations', sa.JSON(), server_default='[]', nullable=False))
    for pid, location in rows:
        city = (location or "").strip()
        bind.execute(
            sa.text("UPDATE search_profile SET locations = :v WHERE id = :id"),
            {"v": json.dumps([city] if city else []), "id": pid},
        )
    with op.batch_alter_table('search_profile', schema=None) as batch_op:
        batch_op.alter_column('locations', server_default=None, existing_type=sa.JSON(), existing_nullable=False)
        batch_op.drop_column('location')


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table('search_profile', schema=None) as batch_op:
        batch_op.add_column(sa.Column('location', sa.String(), nullable=True))
    for pid, raw in bind.execute(sa.text("SELECT id, locations FROM search_profile")).all():
        cities = json.loads(raw) if raw else []
        bind.execute(
            sa.text("UPDATE search_profile SET location = :v WHERE id = :id"),
            {"v": cities[0] if cities else None, "id": pid},
        )
    with op.batch_alter_table('search_profile', schema=None) as batch_op:
        batch_op.drop_column('locations')
