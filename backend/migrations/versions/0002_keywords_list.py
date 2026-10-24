"""keywords as list

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23 09:00:00.000000
"""
import json

from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def _raw_keywords() -> list[tuple[int, str | None]]:
    # Read as raw text: the column is String before upgrade and JSON-typed text after.
    rows = op.get_bind().execute(sa.text("SELECT id, keywords FROM search_profile"))
    return [(r[0], r[1]) for r in rows]


def upgrade() -> None:
    # Convert the data first (as JSON text in the still-String column) so that no NULL
    # survives into the NOT NULL column when batch mode copies the table.
    bind = op.get_bind()
    for pid, raw in _raw_keywords():
        words = [w.strip() for w in (raw or "").split(",")]
        bind.execute(
            sa.text("UPDATE search_profile SET keywords = :kw WHERE id = :id"),
            {"kw": json.dumps([w for w in words if w]), "id": pid},
        )
    with op.batch_alter_table('search_profile', schema=None) as batch_op:
        batch_op.alter_column(
            'keywords', existing_type=sa.String(), type_=sa.JSON(), existing_nullable=True, nullable=False
        )


def downgrade() -> None:
    converted = []
    for pid, raw in _raw_keywords():
        converted.append((pid, ", ".join(json.loads(raw) if raw else [])))

    with op.batch_alter_table('search_profile', schema=None) as batch_op:
        batch_op.alter_column(
            'keywords', existing_type=sa.JSON(), type_=sa.String(), existing_nullable=False, nullable=True
        )
    for pid, text in converted:
        op.get_bind().execute(
            sa.text("UPDATE search_profile SET keywords = :kw WHERE id = :id"), {"kw": text, "id": pid}
        )
