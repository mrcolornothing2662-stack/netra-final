"""v5_offline_sync

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-22 21:15:00.000000

NETRA V5: Offline SQLite synchronization and conflict resolution tables
(sync_processed_mutations, sync_conflicts) ensuring server-authoritative reconciliation,
mutation idempotency, and explicit conflict adjudication.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
UUID_TYPE = sa.UUID().with_variant(sa.Uuid(), 'sqlite')


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. Create sync_processed_mutations
    if "sync_processed_mutations" not in existing_tables:
        op.create_table(
            "sync_processed_mutations",
            sa.Column("mutation_id", sa.String(64), primary_key=True),
            sa.Column("device_id", sa.String(64), nullable=False),
            sa.Column("actor_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("command_type", sa.String(64), nullable=False),
            sa.Column("base_state_version", sa.Integer(), nullable=False),
            sa.Column("server_state_version", sa.Integer(), nullable=False),
            sa.Column("outcome", sa.String(32), nullable=False),
            sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("activity_id", UUID_TYPE, sa.ForeignKey("investigation_activity.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("idx_sync_mutations_case", "sync_processed_mutations", ["case_id"])
        op.create_index("idx_sync_mutations_device", "sync_processed_mutations", ["device_id"])

    # 2. Create sync_conflicts
    if "sync_conflicts" not in existing_tables:
        op.create_table(
            "sync_conflicts",
            sa.Column("id", UUID_TYPE, primary_key=True, default=sa.func.gen_random_uuid()),
            sa.Column("mutation_id", sa.String(64), nullable=False, unique=True),
            sa.Column("device_id", sa.String(64), nullable=False),
            sa.Column("actor_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("command_type", sa.String(64), nullable=False),
            sa.Column("client_payload", JSON_TYPE, server_default="{}"),
            sa.Column("base_state_version", sa.Integer(), nullable=False),
            sa.Column("server_state_version", sa.Integer(), nullable=False),
            sa.Column("conflict_type", sa.String(64), nullable=False),
            sa.Column("server_current_state", JSON_TYPE, server_default="{}"),
            sa.Column("status", sa.String(32), nullable=False, server_default="PENDING_REVIEW"),
            sa.Column("resolution_rationale", sa.Text(), nullable=True),
            sa.Column("resolved_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_sync_conflicts_case", "sync_conflicts", ["case_id"])
        op.create_index("idx_sync_conflicts_status", "sync_conflicts", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "sync_conflicts" in existing_tables:
        op.drop_table("sync_conflicts")
    if "sync_processed_mutations" in existing_tables:
        op.drop_table("sync_processed_mutations")
