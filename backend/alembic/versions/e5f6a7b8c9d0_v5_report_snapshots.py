"""v5_report_snapshots

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-22 23:10:00.000000

NETRA V5: Milestone 8 - Report Snapshots and Evidence-Linked Dossier.
Adds report_snapshots table storing immutable, reproducible report state,
hash-sealed claims, provenance metrics, and Four-Eyes approval references.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
UUID_TYPE = sa.UUID().with_variant(sa.Uuid(), 'sqlite')


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "report_snapshots" not in existing_tables:
        op.create_table(
            "report_snapshots",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("report_type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
            sa.Column("case_state_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("template_version", sa.String(32), nullable=False, server_default="v1.0"),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("claims_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("linked_claims_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("review_required_claims_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("payload", JSON_TYPE, nullable=False),
            sa.Column("generated_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("approved_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("export_approval_id", UUID_TYPE, sa.ForeignKey("dossier_export_approvals.id", ondelete="SET NULL"), nullable=True),
        )
        op.create_index("idx_report_snapshots_case", "report_snapshots", ["case_id"])
        op.create_index("idx_report_snapshots_status", "report_snapshots", ["status"])
        op.create_index("idx_report_snapshots_case_version", "report_snapshots", ["case_id", "case_state_version"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "report_snapshots" in existing_tables:
        op.drop_index("idx_report_snapshots_case_version", table_name="report_snapshots")
        op.drop_index("idx_report_snapshots_status", table_name="report_snapshots")
        op.drop_index("idx_report_snapshots_case", table_name="report_snapshots")
        op.drop_table("report_snapshots")
