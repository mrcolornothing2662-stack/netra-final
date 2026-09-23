from __future__ import annotations

"""
NETRA V5 / Milestone 9 — Capability-based Authorization Policy
The canonical role model:
  - INVESTIGATOR
  - MANAGER
  - ADMIN

Capabilities:
  - CASE_READ
  - CASE_WRITE
  - ENTITY_READ
  - ENTITY_WRITE
  - RELATIONSHIP_REVIEW
  - FINDING_REVIEW
  - EVIDENCE_READ
  - EVIDENCE_EXPORT
  - REPORT_GENERATE
  - REPORT_APPROVE
  - REPORT_EXPORT
  - AUDIT_READ
  - CASE_CLOSE
  - ADMIN_SECURITY

Legacy roles (constable, io, fiu_analyst, supervisor, admin) are mapped seamlessly
to their corresponding capability profiles.
"""

from typing import Set

# Canonical Milestone 9 capabilities
CASE_READ            = "CASE_READ"
CASE_WRITE           = "CASE_WRITE"
ENTITY_READ          = "ENTITY_READ"
ENTITY_WRITE         = "ENTITY_WRITE"
RELATIONSHIP_REVIEW  = "RELATIONSHIP_REVIEW"
FINDING_REVIEW       = "FINDING_REVIEW"
EVIDENCE_READ        = "EVIDENCE_READ"
EVIDENCE_EXPORT      = "EVIDENCE_EXPORT"
REPORT_GENERATE      = "REPORT_GENERATE"
REPORT_APPROVE       = "REPORT_APPROVE"
REPORT_EXPORT        = "REPORT_EXPORT"
AUDIT_READ           = "AUDIT_READ"
CASE_CLOSE           = "CASE_CLOSE"
ADMIN_SECURITY       = "ADMIN_SECURITY"

# Backward-compatibility aliases (both uppercase and dotted legacy forms)
CAP_CASE_READ              = CASE_READ
CAP_CASE_WRITE             = CASE_WRITE
CAP_CASE_CLOSE             = CASE_CLOSE
CAP_ENTITY_READ            = ENTITY_READ
CAP_ENTITY_WRITE           = ENTITY_WRITE
CAP_RELATIONSHIP_WRITE     = RELATIONSHIP_REVIEW
CAP_RELATIONSHIP_CONFIRM   = RELATIONSHIP_REVIEW
CAP_RELATIONSHIP_REJECT    = RELATIONSHIP_REVIEW
CAP_FINDING_REVIEW         = FINDING_REVIEW
CAP_HYPOTHESIS_WRITE       = CASE_WRITE
CAP_ACTION_SUGGEST         = CASE_WRITE
CAP_ACTION_AUTHORIZE       = CASE_WRITE
CAP_EVIDENCE_READ          = EVIDENCE_READ
CAP_EVIDENCE_ORIGINAL_READ = EVIDENCE_READ
CAP_EVIDENCE_DELETE        = ADMIN_SECURITY
CAP_EVIDENCE_EXPORT        = EVIDENCE_EXPORT
CAP_REPORT_GENERATE        = REPORT_GENERATE
CAP_REPORT_APPROVE         = REPORT_APPROVE
CAP_REPORT_EXPORT          = REPORT_EXPORT
CAP_AUDIT_READ             = AUDIT_READ
CAP_ADMIN_MANAGE           = ADMIN_SECURITY
CAP_ADMIN_SECURITY         = ADMIN_SECURITY

_LEGACY_CAP_MAP: dict[str, str] = {
    "case.read": CASE_READ,
    "case.write": CASE_WRITE,
    "case.close": CASE_CLOSE,
    "evidence.read": EVIDENCE_READ,
    "evidence.original.read": EVIDENCE_READ,
    "evidence.delete": ADMIN_SECURITY,
    "evidence.export": EVIDENCE_EXPORT,
    "entity.read": ENTITY_READ,
    "entity.write": ENTITY_WRITE,
    "relationship.write": RELATIONSHIP_REVIEW,
    "relationship.confirm": RELATIONSHIP_REVIEW,
    "relationship.reject": RELATIONSHIP_REVIEW,
    "relationship.review": RELATIONSHIP_REVIEW,
    "finding.review": FINDING_REVIEW,
    "hypothesis.write": CASE_WRITE,
    "action.suggest": CASE_WRITE,
    "action.authorize": CASE_WRITE,
    "report.generate": REPORT_GENERATE,
    "report.approve": REPORT_APPROVE,
    "report.export": REPORT_EXPORT,
    "audit.read": AUDIT_READ,
    "admin.manage": ADMIN_SECURITY,
    "admin.security": ADMIN_SECURITY,
}

# Base capability sets for normalized roles
INVESTIGATOR_CAPABILITIES: Set[str] = {
    CASE_READ,
    CASE_WRITE,
    ENTITY_READ,
    ENTITY_WRITE,
    RELATIONSHIP_REVIEW,
    FINDING_REVIEW,
    EVIDENCE_READ,
    REPORT_GENERATE,
    AUDIT_READ,
    # Include dotted aliases so direct string check succeeds
    "case.read",
    "case.write",
    "entity.read",
    "entity.write",
    "relationship.write",
    "relationship.confirm",
    "relationship.reject",
    "relationship.review",
    "finding.review",
    "hypothesis.write",
    "action.suggest",
    "evidence.read",
    "evidence.original.read",
    "report.generate",
    "audit.read",
}

MANAGER_CAPABILITIES: Set[str] = INVESTIGATOR_CAPABILITIES | {
    REPORT_APPROVE,
    REPORT_EXPORT,
    EVIDENCE_EXPORT,
    CASE_CLOSE,
    # Include dotted aliases
    "report.approve",
    "report.export",
    "evidence.export",
    "case.close",
    "action.authorize",
}

ADMIN_CAPABILITIES: Set[str] = MANAGER_CAPABILITIES | {
    ADMIN_SECURITY,
    "admin.manage",
    "admin.security",
    "evidence.delete",
}

CONSTABLE_CAPABILITIES: Set[str] = {
    CASE_READ,
    ENTITY_READ,
    EVIDENCE_READ,
    REPORT_GENERATE,
    "case.read",
    "entity.read",
    "evidence.read",
    "report.generate",
}

ROLE_CAPABILITIES: dict[str, Set[str]] = {
    # Canonical roles
    "INVESTIGATOR": INVESTIGATOR_CAPABILITIES,
    "MANAGER": MANAGER_CAPABILITIES,
    "ADMIN": ADMIN_CAPABILITIES,
    # Case-insensitive aliases
    "investigator": INVESTIGATOR_CAPABILITIES,
    "manager": MANAGER_CAPABILITIES,
    "admin": ADMIN_CAPABILITIES,
    # Legacy roles
    "io": INVESTIGATOR_CAPABILITIES,
    "fiu_analyst": INVESTIGATOR_CAPABILITIES,
    "supervisor": MANAGER_CAPABILITIES,
    "constable": CONSTABLE_CAPABILITIES,
    "observer": {CASE_READ, ENTITY_READ, EVIDENCE_READ, "case.read", "entity.read", "evidence.read"},
}


def normalize_role(role: str | None) -> str:
    """Normalize input role string to canonical INVESTIGATOR, MANAGER, or ADMIN."""
    if not role:
        return "INVESTIGATOR"
    r = role.strip().upper()
    if r in ("ADMIN",):
        return "ADMIN"
    if r in ("MANAGER", "SUPERVISOR", "LEAD_IO"):
        return "MANAGER"
    if r in ("INVESTIGATOR", "IO", "FIU_ANALYST"):
        return "INVESTIGATOR"
    if r in ("CONSTABLE", "OBSERVER"):
        return "INVESTIGATOR"  # Treated as restricted investigator
    return r


def get_role_capabilities(role: str | None) -> Set[str]:
    """Retrieve full capability set for a given role."""
    if not role:
        return set()
    r_raw = role.strip()
    return ROLE_CAPABILITIES.get(r_raw) or ROLE_CAPABILITIES.get(r_raw.lower()) or ROLE_CAPABILITIES.get(r_raw.upper(), set())


def user_has_capability(user_role: str | None, capability: str) -> bool:
    """Check if the given user role possesses the requested capability."""
    if not user_role or not capability:
        return False
    caps = get_role_capabilities(user_role)
    if capability in caps:
        return True
    # Try normalized capability lookup
    mapped = _LEGACY_CAP_MAP.get(capability.lower())
    if mapped and mapped in caps:
        return True
    cap_upper = capability.strip().upper()
    return cap_upper in caps

