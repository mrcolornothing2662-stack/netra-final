from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Migration Chain Validation (Milestone 10)
Verifies:
  1. Alembic environment and script directory load successfully.
  2. Single unbroken linear head exists: f6a7b8c9d0e1.
  3. Single base migration exists: 45cc32c7caff.
  4. Migration chain continuity: exactly 9 revisions forming a strictly linear DAG with zero forks.
  5. Every migration defines upgrade callable and valid metadata.
"""

from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def _get_script_directory() -> ScriptDirectory:
    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return ScriptDirectory.from_config(cfg)


def test_alembic_heads_and_bases():
    script_dir = _get_script_directory()
    heads = script_dir.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 migration head, found: {heads}"
    assert heads[0] == "f6a7b8c9d0e1", f"Expected head f6a7b8c9d0e1, got {heads[0]}"

    bases = script_dir.get_bases()
    assert len(bases) == 1, f"Expected exactly 1 migration base, found: {bases}"
    assert bases[0] == "45cc32c7caff", f"Expected base 45cc32c7caff, got {bases[0]}"


def test_linear_migration_chain_continuity():
    script_dir = _get_script_directory()
    
    expected_chain = [
        "45cc32c7caff",  # baseline_12_tables
        "6a71b5ece32b",  # existing_db_bridge
        "a1f2c3d4e5f6",  # relationships_unified_case_graph
        "b2c3d4e5f6a7",  # findings_analysis_runs_intelligence_state
        "54f98ae73033",  # phase_1_security_hygiene
        "c3d4e5f6a7b8",  # v5_investigation_workspace
        "d4e5f6a7b8c9",  # v5_offline_sync
        "e5f6a7b8c9d0",  # v5_report_snapshots
        "f6a7b8c9d0e1",  # v6_security_hardening
    ]
    
    current_rev = script_dir.get_revision("f6a7b8c9d0e1")
    reconstructed_chain = []
    
    while current_rev is not None:
        reconstructed_chain.append(current_rev.revision)
        if current_rev.down_revision:
            current_rev = script_dir.get_revision(current_rev.down_revision)
        else:
            current_rev = None
            
    reconstructed_chain.reverse()
    
    assert reconstructed_chain == expected_chain, (
        f"Chain mismatch.\nExpected: {expected_chain}\nActual:   {reconstructed_chain}"
    )
    assert len(reconstructed_chain) == 9


def test_every_migration_defines_upgrade():
    script_dir = _get_script_directory()
    all_revisions = list(script_dir.walk_revisions())
    assert len(all_revisions) == 9
    
    for rev in all_revisions:
        module = rev.module
        assert hasattr(module, "upgrade"), f"Revision {rev.revision} is missing upgrade() function"
        assert callable(module.upgrade), f"Revision {rev.revision} upgrade is not callable"
        assert hasattr(module, "revision"), f"Revision {rev.revision} is missing revision identifier"
