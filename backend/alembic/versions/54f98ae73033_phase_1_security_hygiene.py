"""phase_1_security_hygiene

Revision ID: 54f98ae73033
Revises: b2c3d4e5f6a7
Create Date: 2026-09-19 11:04:43.061345

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '54f98ae73033'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID_TYPE = sa.UUID().with_variant(sa.Uuid(), 'sqlite')


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # 1. users table security hygiene columns
    if "users" in existing_tables:
        user_cols = {c["name"] for c in insp.get_columns("users")}
        if "totp_secret" not in user_cols:
            op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
        if "totp_enabled" not in user_cols:
            op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "failed_login_attempts" not in user_cols:
            op.add_column("users", sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))
        if "locked_until" not in user_cols:
            op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))

    # 2. case_collaborators table
    if "case_collaborators" not in existing_tables:
        op.create_table(
            "case_collaborators",
            sa.Column("id", UUID_TYPE, nullable=False),
            sa.Column("case_id", UUID_TYPE, nullable=False),
            sa.Column("user_id", UUID_TYPE, nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="io"),
            sa.Column("assigned_by", UUID_TYPE, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assigned_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("case_id", "user_id", name="uq_case_collaborators_case_user"),
        )
        op.create_index("idx_case_collaborators_case_id", "case_collaborators", ["case_id"], unique=False)
        op.create_index("idx_case_collaborators_user_id", "case_collaborators", ["user_id"], unique=False)

    # 3. dossier_export_approvals table
    if "dossier_export_approvals" not in existing_tables:
        op.create_table(
            "dossier_export_approvals",
            sa.Column("id", UUID_TYPE, nullable=False),
            sa.Column("case_id", UUID_TYPE, nullable=False),
            sa.Column("report_type", sa.String(length=64), nullable=False),
            sa.Column("requested_by", UUID_TYPE, nullable=False),
            sa.Column("approved_by", UUID_TYPE, nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_dossier_export_status"),
            sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_dossier_export_case_status", "dossier_export_approvals", ["case_id", "status"], unique=False)

    # 4. evidence_files table: source device hash, acquisition metadata & encryption at rest
    if "evidence_files" in existing_tables:
        ev_cols = {c["name"] for c in insp.get_columns("evidence_files")}
        if "source_device_hash" not in ev_cols:
            op.add_column("evidence_files", sa.Column("source_device_hash", sa.String(length=64), nullable=True))
        if "acquisition_tool" not in ev_cols:
            op.add_column("evidence_files", sa.Column("acquisition_tool", sa.String(length=128), nullable=True))
        if "acquisition_timestamp" not in ev_cols:
            op.add_column("evidence_files", sa.Column("acquisition_timestamp", sa.DateTime(timezone=True), nullable=True))
        if "officer_notes" not in ev_cols:
            op.add_column("evidence_files", sa.Column("officer_notes", sa.Text(), nullable=True))
        if "is_encrypted" not in ev_cols:
            op.add_column("evidence_files", sa.Column("is_encrypted", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "encrypted_dek" not in ev_cols:
            op.add_column("evidence_files", sa.Column("encrypted_dek", sa.Text(), nullable=True))
        if "encryption_iv" not in ev_cols:
            op.add_column("evidence_files", sa.Column("encryption_iv", sa.String(length=64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "dossier_export_approvals" in existing_tables:
        op.drop_table("dossier_export_approvals")

    if "case_collaborators" in existing_tables:
        op.drop_table("case_collaborators")

    if "evidence_files" in existing_tables:
        for col in ["encryption_iv", "encrypted_dek", "is_encrypted", "officer_notes", "acquisition_timestamp", "acquisition_tool", "source_device_hash"]:
            op.drop_column("evidence_files", col)

    if "users" in existing_tables:
        for col in ["locked_until", "failed_login_attempts", "totp_enabled", "totp_secret"]:
            op.drop_column("users", col)
