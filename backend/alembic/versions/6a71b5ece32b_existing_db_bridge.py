"""existing_db_bridge

Revision ID: 6a71b5ece32b
Revises: 45cc32c7caff
Create Date: 2026-09-15 23:19:20.000000

Bridge migration:
- Drops the 6 legacy orphan tables created by init_db.sql that have zero
  references in application code.
- Ensures users.must_change_password exists.
- Ensures evidence_events.metadata column exists (guards against legacy event_metadata).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a71b5ece32b'
down_revision: Union[str, None] = '45cc32c7caff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. Drop legacy orphan tables in dependency order
    orphan_tables = [
        "relationship_explanations",
        "investigator_relationships",
        "investigator_entities",
        "investigation_questions",
        "intelligence_signals",
        "intelligence_assessments",
    ]
    for table in orphan_tables:
        if table in existing_tables:
            op.drop_table(table)

    # 2. Ensure must_change_password exists on users
    if "users" in existing_tables:
        columns = {col["name"] for col in insp.get_columns("users")}
        if "must_change_password" not in columns:
            op.add_column(
                "users",
                sa.Column(
                    "must_change_password",
                    sa.Boolean(),
                    server_default=sa.text("false"),
                    nullable=False,
                ),
            )

    # 3. Ensure metadata column exists on evidence_events
    if "evidence_events" in existing_tables:
        columns = {col["name"] for col in insp.get_columns("evidence_events")}
        if "metadata" not in columns and "event_metadata" in columns:
            op.alter_column(
                "evidence_events",
                "event_metadata",
                new_column_name="metadata",
            )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "users" in existing_tables:
        columns = {col["name"] for col in insp.get_columns("users")}
        if "must_change_password" in columns:
            op.drop_column("users", "must_change_password")
