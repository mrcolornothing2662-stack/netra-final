"""v5_investigation_workspace

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-22 17:35:00.000000

NETRA V5: Investigation Brain tables (investigation_state, investigation_activity,
identity_candidates, hypotheses, hypothesis_evidence, investigation_actions,
information_gaps) and schema extensions for state versioning and epistemic provenance.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = '54f98ae73033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
UUID_TYPE = sa.UUID().with_variant(sa.Uuid(), 'sqlite')


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. Alter cases
    if "cases" in existing_tables:
        case_cols = {c["name"] for c in insp.get_columns("cases")}
        if "state_version" not in case_cols:
            op.add_column("cases", sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"))
        if "closed_by" not in case_cols:
            op.add_column("cases", sa.Column("closed_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
        if "closure_reason" not in case_cols:
            op.add_column("cases", sa.Column("closure_reason", sa.Text(), nullable=True))
        if "last_activity_at" not in case_cols:
            op.add_column("cases", sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now()))

    # 2. Alter evidence_files
    if "evidence_files" in existing_tables:
        ev_cols = {c["name"] for c in insp.get_columns("evidence_files")}
        if "integrity_status" not in ev_cols:
            op.add_column("evidence_files", sa.Column("integrity_status", sa.String(32), nullable=False, server_default="verified"))
        if "original_immutable" not in ev_cols:
            op.add_column("evidence_files", sa.Column("original_immutable", sa.Boolean(), nullable=False, server_default=sa.true()))
        if "last_verified_at" not in ev_cols:
            op.add_column("evidence_files", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True))
        if "retention_class" not in ev_cols:
            op.add_column("evidence_files", sa.Column("retention_class", sa.String(32), nullable=True, server_default="standard"))
        if "access_policy" not in ev_cols:
            op.add_column("evidence_files", sa.Column("access_policy", sa.String(32), nullable=True, server_default="restricted"))

    # 3. Alter relationships
    if "relationships" in existing_tables:
        rel_cols = {c["name"] for c in insp.get_columns("relationships")}
        if "created_by" not in rel_cols:
            op.add_column("relationships", sa.Column("created_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
        if "verified_by" not in rel_cols:
            op.add_column("relationships", sa.Column("verified_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
        if "verification_status" not in rel_cols:
            op.add_column("relationships", sa.Column("verification_status", sa.String(32), nullable=False, server_default="UNREVIEWED"))
        if "state_version" not in rel_cols:
            op.add_column("relationships", sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"))

    # 4. Alter findings
    if "findings" in existing_tables:
        find_cols = {c["name"] for c in insp.get_columns("findings")}
        if "supporting_refs" not in find_cols:
            op.add_column("findings", sa.Column("supporting_refs", JSON_TYPE, server_default="[]"))
        if "contradicting_refs" not in find_cols:
            op.add_column("findings", sa.Column("contradicting_refs", JSON_TYPE, server_default="[]"))
        if "missing_information" not in find_cols:
            op.add_column("findings", sa.Column("missing_information", JSON_TYPE, server_default="[]"))
        if "suggested_actions" not in find_cols:
            op.add_column("findings", sa.Column("suggested_actions", JSON_TYPE, server_default="[]"))
        if "generated_at_case_version" not in find_cols:
            op.add_column("findings", sa.Column("generated_at_case_version", sa.Integer(), nullable=True, server_default="1"))
        if "freshness_status" not in find_cols:
            op.add_column("findings", sa.Column("freshness_status", sa.String(32), nullable=False, server_default="CURRENT"))

    # 5. Create investigation_state
    if "investigation_state" not in existing_tables:
        op.create_table(
            "investigation_state",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, default=1),
            sa.Column("state_hash", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("created_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.UniqueConstraint("case_id", "version", name="uq_investigation_state_case_version"),
        )
        op.create_index("idx_investigation_state_case_version", "investigation_state", ["case_id", "version"])

    # 6. Create investigation_activity
    if "investigation_activity" not in existing_tables:
        op.create_table(
            "investigation_activity",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("activity_type", sa.String(64), nullable=False),
            sa.Column("target_type", sa.String(64), nullable=True),
            sa.Column("target_id", sa.String(128), nullable=True),
            sa.Column("before_state", JSON_TYPE, server_default="{}"),
            sa.Column("after_state", JSON_TYPE, server_default="{}"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_investigation_activity_case_created", "investigation_activity", ["case_id", "created_at"])

    # 7. Create identity_candidates
    if "identity_candidates" not in existing_tables:
        op.create_table(
            "identity_candidates",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("canonical_entity_id", UUID_TYPE, sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=True),
            sa.Column("candidate_value", sa.String(512), nullable=False),
            sa.Column("candidate_type", sa.String(32), nullable=False),
            sa.Column("source_refs", JSON_TYPE, server_default="[]"),
            sa.Column("supporting_refs", JSON_TYPE, server_default="[]"),
            sa.Column("contradicting_refs", JSON_TYPE, server_default="[]"),
            sa.Column("resolution_status", sa.String(32), nullable=False, server_default="UNRESOLVED"),
            sa.Column("created_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_identity_candidates_case", "identity_candidates", ["case_id"])

    # 8. Create hypotheses
    if "hypotheses" not in existing_tables:
        op.create_table(
            "hypotheses",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("title", sa.String(512), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
            sa.Column("created_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_hypotheses_case_id", "hypotheses", ["case_id"])

    # 9. Create hypothesis_evidence
    if "hypothesis_evidence" not in existing_tables:
        op.create_table(
            "hypothesis_evidence",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("hypothesis_id", UUID_TYPE, sa.ForeignKey("hypotheses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("evidence_id", UUID_TYPE, sa.ForeignKey("evidence_files.id", ondelete="CASCADE"), nullable=True),
            sa.Column("finding_id", UUID_TYPE, sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=True),
            sa.Column("relation", sa.String(16), nullable=False, server_default="SUPPORTS"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_hypo_evidence_hypo", "hypothesis_evidence", ["hypothesis_id"])

    # 10. Create investigation_actions
    if "investigation_actions" not in existing_tables:
        op.create_table(
            "investigation_actions",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action_type", sa.String(64), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("priority", sa.String(16), nullable=False, server_default="MEDIUM"),
            sa.Column("status", sa.String(32), nullable=False, server_default="SUGGESTED"),
            sa.Column("source", sa.String(64), server_default="cognitive_engine"),
            sa.Column("created_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("approved_by", UUID_TYPE, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_investigation_actions_case", "investigation_actions", ["case_id"])

    # 11. Create information_gaps
    if "information_gaps" not in existing_tables:
        op.create_table(
            "information_gaps",
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column("case_id", UUID_TYPE, sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("importance", sa.String(16), nullable=False, server_default="MEDIUM"),
            sa.Column("related_entities", JSON_TYPE, server_default="[]"),
            sa.Column("related_findings", JSON_TYPE, server_default="[]"),
            sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_information_gaps_case", "information_gaps", ["case_id"])


def downgrade() -> None:
    # Safe drops
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    for t in (
        "information_gaps",
        "investigation_actions",
        "hypothesis_evidence",
        "hypotheses",
        "identity_candidates",
        "investigation_activity",
        "investigation_state",
    ):
        if t in existing_tables:
            op.drop_table(t)
