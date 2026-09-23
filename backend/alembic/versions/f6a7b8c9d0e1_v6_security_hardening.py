"""v6_security_hardening

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-22 23:35:00.000000

NETRA V5: Milestone 9 - Security, Access Control & Audit Hardening.
Adds user_sessions table storing active session tokens, device bindings,
authentication trust levels, and revocation tracking.
Updates users ck_users_role check constraint to support INVESTIGATOR, MANAGER, ADMIN.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID_TYPE = sa.UUID().with_variant(sa.Uuid(), 'sqlite')


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "user_sessions" not in existing_tables:
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", UUID_TYPE, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("device_id", sa.String(64), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("authentication_level", sa.String(32), server_default="standard", nullable=False),
            sa.Column("revoked", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("revoked_reason", sa.String(256), nullable=True),
            sa.Column("ip_address", sa.String(64), nullable=True),
            sa.Column("user_agent", sa.String(256), nullable=True),
        )
        op.create_index("idx_user_sessions_user_id", "user_sessions", ["user_id"])
        op.create_index("idx_user_sessions_device_id", "user_sessions", ["device_id"])
        op.create_index("idx_user_sessions_revoked", "user_sessions", ["revoked"])

    # Update check constraint on PostgreSQL if applicable
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role;")
        op.execute(
            "ALTER TABLE users ADD CONSTRAINT ck_users_role "
            "CHECK (role IN ('constable','io','fiu_analyst','admin','supervisor','INVESTIGATOR','MANAGER','ADMIN','investigator','manager'));"
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "user_sessions" in existing_tables:
        op.drop_index("idx_user_sessions_revoked", table_name="user_sessions")
        op.drop_index("idx_user_sessions_device_id", table_name="user_sessions")
        op.drop_index("idx_user_sessions_user_id", table_name="user_sessions")
        op.drop_table("user_sessions")

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role;")
        op.execute(
            "ALTER TABLE users ADD CONSTRAINT ck_users_role "
            "CHECK (role IN ('constable','io','fiu_analyst','admin'));"
        )
