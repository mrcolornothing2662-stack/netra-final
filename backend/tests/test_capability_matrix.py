from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Milestone 9
Test Suite 2: Capability Matrix & Role Semantics
Verifies:
- Explicit capabilities for INVESTIGATOR, MANAGER, ADMIN
- Negative permission guarantees across role boundaries
- Legacy role backward compatibility
"""

import pytest
from investigation.policies import (
    CASE_CLOSE,
    CASE_READ,
    CASE_WRITE,
    ENTITY_READ,
    ENTITY_WRITE,
    EVIDENCE_EXPORT,
    EVIDENCE_READ,
    FINDING_REVIEW,
    RELATIONSHIP_REVIEW,
    REPORT_APPROVE,
    REPORT_EXPORT,
    REPORT_GENERATE,
    AUDIT_READ,
    ADMIN_SECURITY,
    get_role_capabilities,
    user_has_capability,
)


def test_investigator_capability_boundary():
    # Positive permissions
    assert user_has_capability("INVESTIGATOR", CASE_READ)
    assert user_has_capability("INVESTIGATOR", CASE_WRITE)
    assert user_has_capability("INVESTIGATOR", ENTITY_READ)
    assert user_has_capability("INVESTIGATOR", ENTITY_WRITE)
    assert user_has_capability("INVESTIGATOR", RELATIONSHIP_REVIEW)
    assert user_has_capability("INVESTIGATOR", FINDING_REVIEW)
    assert user_has_capability("INVESTIGATOR", EVIDENCE_READ)
    assert user_has_capability("INVESTIGATOR", REPORT_GENERATE)
    assert user_has_capability("INVESTIGATOR", AUDIT_READ)

    # Negative guarantees: Investigator CANNOT approve reports, export reports, close case, or administer security
    assert not user_has_capability("INVESTIGATOR", REPORT_APPROVE)
    assert not user_has_capability("INVESTIGATOR", REPORT_EXPORT)
    assert not user_has_capability("INVESTIGATOR", EVIDENCE_EXPORT)
    assert not user_has_capability("INVESTIGATOR", CASE_CLOSE)
    assert not user_has_capability("INVESTIGATOR", ADMIN_SECURITY)


def test_manager_capability_boundary():
    # Positive supervisor permissions
    assert user_has_capability("MANAGER", CASE_READ)
    assert user_has_capability("MANAGER", CASE_WRITE)
    assert user_has_capability("MANAGER", REPORT_APPROVE)
    assert user_has_capability("MANAGER", REPORT_EXPORT)
    assert user_has_capability("MANAGER", EVIDENCE_EXPORT)
    assert user_has_capability("MANAGER", CASE_CLOSE)

    # Negative guarantees: Manager CANNOT perform admin security management
    assert not user_has_capability("MANAGER", ADMIN_SECURITY)


def test_admin_capability_boundary():
    # Admin possesses full capability set including security management
    assert user_has_capability("ADMIN", CASE_READ)
    assert user_has_capability("ADMIN", CASE_WRITE)
    assert user_has_capability("ADMIN", REPORT_APPROVE)
    assert user_has_capability("ADMIN", REPORT_EXPORT)
    assert user_has_capability("ADMIN", CASE_CLOSE)
    assert user_has_capability("ADMIN", ADMIN_SECURITY)


def test_legacy_role_mappings():
    # io / fiu_analyst maps to investigator capability set
    assert user_has_capability("io", CASE_READ)
    assert user_has_capability("io", CASE_WRITE)
    assert user_has_capability("fiu_analyst", RELATIONSHIP_REVIEW)

    # supervisor maps to manager capability set
    assert user_has_capability("supervisor", REPORT_APPROVE)
    assert user_has_capability("supervisor", CASE_CLOSE)

    # constable has restricted read-only permissions
    assert user_has_capability("constable", CASE_READ)
    assert user_has_capability("constable", EVIDENCE_READ)
    assert not user_has_capability("constable", CASE_WRITE)
    assert not user_has_capability("constable", REPORT_APPROVE)
    assert not user_has_capability("constable", CASE_CLOSE)
