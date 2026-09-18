"""relationships_unified_case_graph

Revision ID: a1f2c3d4e5f6
Revises: 6a71b5ece32b
Create Date: 2026-09-16 20:05:00.000000

Adds the unified case-graph edge table. Each row is a semantically typed
relationship carrying an epistemic status (OBSERVED evidence-backed edges vs
INFERRED cognitive edges) and full evidence/event provenance.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1f2c3d4e5f6'
down_revision: Union[str, None] = '6a71b5ece32b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Cross-dialect type wrappers (mirror db/models.py)
JSON_TYPE = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
UUID_TYPE = sa.UUID().with_variant(sa.Uuid(), 'sqlite')


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())
    if "relationships" in existing_tables:
        # Pre-existing database already provisioned (e.g. via Base.metadata.create_all).
        return

    op.create_table(
        'relationships',
        sa.Column('id', UUID_TYPE, nullable=False),
        sa.Column('case_id', UUID_TYPE, nullable=False),
        sa.Column('source_entity_id', UUID_TYPE, nullable=False),
        sa.Column('target_entity_id', UUID_TYPE, nullable=False),
        sa.Column('relationship_type', sa.String(length=32), nullable=False),
        sa.Column('direction', sa.String(length=16), nullable=False),
        sa.Column('epistemic_status', sa.String(length=16), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('event_timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('observation_count', sa.Integer(), nullable=False),
        sa.Column('attributes', JSON_TYPE, nullable=True),
        sa.Column('evidence_refs', JSON_TYPE, nullable=True),
        sa.Column('event_refs', JSON_TYPE, nullable=True),
        sa.Column('source_engine', sa.String(length=64), nullable=True),
        sa.Column('engine_version', sa.String(length=32), nullable=True),
        sa.Column('component_scores', JSON_TYPE, nullable=True),
        sa.Column('reason_codes', JSON_TYPE, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.CheckConstraint("direction IN ('OUTBOUND','INBOUND','BIDIRECTIONAL')", name='ck_relationships_direction'),
        sa.CheckConstraint("epistemic_status IN ('OBSERVED','INFERRED')", name='ck_relationships_epistemic_status'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_entity_id'], ['entities.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_entity_id'], ['entities.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'case_id', 'source_entity_id', 'target_entity_id',
            'relationship_type', 'epistemic_status',
            name='uq_relationships_edge',
        ),
    )
    op.create_index('idx_relationships_case_id', 'relationships', ['case_id'], unique=False)
    op.create_index('idx_relationships_epistemic_status', 'relationships', ['epistemic_status'], unique=False)
    op.create_index('idx_relationships_source', 'relationships', ['source_entity_id'], unique=False)
    op.create_index('idx_relationships_target', 'relationships', ['target_entity_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_relationships_target', table_name='relationships')
    op.drop_index('idx_relationships_source', table_name='relationships')
    op.drop_index('idx_relationships_epistemic_status', table_name='relationships')
    op.drop_index('idx_relationships_case_id', table_name='relationships')
    op.drop_table('relationships')
