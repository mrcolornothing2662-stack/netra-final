"""
CyberDrishti AI / NETRA V5 — Forensic Lenses Package
Consolidated read-only projections over Investigation Brain state:
- Money Trail Lens (Financial flow, ledger, rapid transfer & round-number signals)
- Communications Lens (CDR/WhatsApp call graph, bursts, 24h heatmap)
- Travel / Geographic Lens (Cell-site timeline, tower movement hops, non-GPS disclaimer)
"""

from forensic.contracts import (
    ForensicLensType,
    ForensicLensResponse,
    LensOverviewResponse,
    LensEntity,
    LensEvent,
    LensRelationship,
    LensSignal,
    LensFinding,
    EvidenceRef,
    LensTimelineEvent,
    CrossLensSignal,
)
from forensic.service import ForensicLensService

__all__ = [
    "ForensicLensType",
    "ForensicLensResponse",
    "LensOverviewResponse",
    "LensEntity",
    "LensEvent",
    "LensRelationship",
    "LensSignal",
    "LensFinding",
    "EvidenceRef",
    "LensTimelineEvent",
    "CrossLensSignal",
    "ForensicLensService",
]
