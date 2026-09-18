"""findings_analysis_runs_intelligence_state

Revision ID: b2c3d4e5f6a7
Revises: a1f2c3d4e5f6
Create Date: 2026-09-16 21:10:00.000000

Phase 2 intelligence foundation: unified InvestigationFinding rows, the
AnalysisRun execution log of the orchestrator, and the materialised per-case
intelligence snapshot.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1f2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
UUID_TYPE = sa.UUID().with_variant(sa.Uuid(), 'sqlite')


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    if "findings" not in existing_tables:
        op.create_table(
            'findings',
            sa.Column('id', UUID_TYPE, nullable=False),
            sa.Column('case_id', UUID_TYPE, nullable=False),
            sa.Column('fingerprint', sa.String(length=64), nullable=False),
            sa.Column('finding_type', sa.String(length=48), nullable=False),
            sa.Column('title', sa.String(length=512), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('confidence', sa.Float(), nullable=True),
            sa.Column('severity', sa.String(length=16), nullable=False),
            sa.Column('status', sa.String(length=24), nullable=False),
            sa.Column('source_engine', sa.String(length=64), nullable=True),
            sa.Column('engine_version', sa.String(length=32), nullable=True),
            sa.Column('entity_refs', JSON_TYPE, nullable=True),
            sa.Column('event_refs', JSON_TYPE, nullable=True),
            sa.Column('evidence_refs', JSON_TYPE, nullable=True),
            sa.Column('component_scores', JSON_TYPE, nullable=True),
            sa.Column('reason_codes', JSON_TYPE, nullable=True),
            sa.Column('reasoning', sa.Text(), nullable=True),
            sa.Column('citations', JSON_TYPE, nullable=True),
            sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name='ck_findings_severity'),
            sa.CheckConstraint("status IN ('OPEN','CONFIRMED','DISMISSED','SUPERSEDED')", name='ck_findings_status'),
            sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('case_id', 'fingerprint', name='uq_findings_case_fingerprint'),
        )
        op.create_index('idx_findings_case_id', 'findings', ['case_id'], unique=False)
        op.create_index('idx_findings_type', 'findings', ['finding_type'], unique=False)
        op.create_index('idx_findings_severity', 'findings', ['severity'], unique=False)
        op.create_index('idx_findings_status', 'findings', ['status'], unique=False)

    if "analysis_runs" not in existing_tables:
        op.create_table(
            'analysis_runs',
            sa.Column('id', UUID_TYPE, nullable=False),
            sa.Column('case_id', UUID_TYPE, nullable=False),
            sa.Column('trigger', sa.String(length=32), nullable=False),
            sa.Column('status', sa.String(length=16), nullable=False),
            sa.Column('engines_requested', JSON_TYPE, nullable=True),
            sa.Column('engines_run', JSON_TYPE, nullable=True),
            sa.Column('engines_skipped', JSON_TYPE, nullable=True),
            sa.Column('findings_created', sa.Integer(), nullable=False),
            sa.Column('findings_updated', sa.Integer(), nullable=False),
            sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('duration_ms', sa.Integer(), nullable=True),
            sa.Column('error', sa.Text(), nullable=True),
            sa.Column('summary', JSON_TYPE, nullable=True),
            sa.CheckConstraint("status IN ('running','completed','failed')", name='ck_analysis_runs_status'),
            sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('idx_analysis_runs_case_id', 'analysis_runs', ['case_id'], unique=False)
        op.create_index('idx_analysis_runs_status', 'analysis_runs', ['status'], unique=False)

    if "case_intelligence_state" not in existing_tables:
        op.create_table(
            'case_intelligence_state',
            sa.Column('id', UUID_TYPE, nullable=False),
            sa.Column('case_id', UUID_TYPE, nullable=False),
            sa.Column('evidence_count', sa.Integer(), nullable=False),
            sa.Column('processed_evidence_count', sa.Integer(), nullable=False),
            sa.Column('entity_count', sa.Integer(), nullable=False),
            sa.Column('event_count', sa.Integer(), nullable=False),
            sa.Column('relationship_count', sa.Integer(), nullable=False),
            sa.Column('observed_relationship_count', sa.Integer(), nullable=False),
            sa.Column('inferred_relationship_count', sa.Integer(), nullable=False),
            sa.Column('finding_count', sa.Integer(), nullable=False),
            sa.Column('high_priority_count', sa.Integer(), nullable=False),
            sa.Column('findings_by_type', JSON_TYPE, nullable=True),
            sa.Column('engine_status', JSON_TYPE, nullable=True),
            sa.Column('last_run_id', UUID_TYPE, nullable=True),
            sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
            sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['last_run_id'], ['analysis_runs.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('case_id', name='uq_case_intelligence_state_case'),
        )


def downgrade() -> None:
    op.drop_table('case_intelligence_state')
    op.drop_index('idx_analysis_runs_status', table_name='analysis_runs')
    op.drop_index('idx_analysis_runs_case_id', table_name='analysis_runs')
    op.drop_table('analysis_runs')
    op.drop_index('idx_findings_status', table_name='findings')
    op.drop_index('idx_findings_severity', table_name='findings')
    op.drop_index('idx_findings_type', table_name='findings')
    op.drop_index('idx_findings_case_id', table_name='findings')
    op.drop_table('findings')
