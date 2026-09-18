"""
CyberDrishti AI — Cognitive Forensic Intelligence Engine Package

Self-contained, dependency-light (pure Python stdlib) cognitive
subsystem comprising 11 autonomous analytical engines for advanced
cyber crime investigation.

Each engine is a standalone module with zero database coupling —
they accept dicts/lists and return structured results.  Integration
with the FastAPI request layer lives in routes/cognitive.py.
"""
from __future__ import annotations

import os
from pathlib import Path

# Resolve data directory once at import time
DATA_DIR = Path(os.path.dirname(__file__)) / "data"


def data_path(filename: str) -> str:
    """Return the absolute path to a bundled data file."""
    p = DATA_DIR / filename
    if not p.exists():
        raise FileNotFoundError(f"cognitive data file not found: {p}")
    return str(p)


# ── Lazy-loaded engine accessors ─────────────────────────────────────────────
# Imports are deferred to keep startup fast and avoid circular deps.

def get_fingerprint_engine():
    """Feature 01: Resilient Document Fingerprinting."""
    from . import fingerprint as mod
    return mod


def get_contradiction_engine():
    """Feature 02: Contradiction Engine (ledger audit + impossible travel)."""
    from . import contradiction as mod
    return mod


def get_crosscase_engine():
    """Feature 03: Cross-Case Blind Index (HMAC-SHA256 zero-knowledge)."""
    from . import crosscase as mod
    return mod


def get_hypothesis_engine():
    """Feature 04: Heuer's ACH Hypothesis Engine."""
    from . import hypothesis as mod
    return mod


def get_uncertainty_engine():
    """Feature 05: Split-Conformal Prediction Sets."""
    from . import uncertainty as mod
    return mod


def get_nextbest_engine():
    """Feature 06: Next-Best Investigation (Golden-Hours VoI)."""
    from . import nextbest as mod
    return mod


def get_mo_engine():
    """Feature 07: MO Fingerprinting (Crime Script Mining)."""
    from . import mo as mod
    return mod


def get_counterfactual_engine():
    """Feature 08: Counterfactual What-If Freeze Simulation."""
    from . import counterfactual as mod
    return mod


def get_verifier_engine():
    """Feature 09: Deterministic Output Verifier (Semantic CRAG Firewall)."""
    from . import verifier as mod
    return mod


def get_replay_engine():
    """Feature 10: Network Replay (CTDG Frame Slicer)."""
    from . import replay as mod
    return mod


def get_benchmark_engine():
    """Feature 11: Synthetic Benchmark Generator."""
    from . import benchmark as mod
    return mod


def get_training_engine():
    """Feature 11: Training Simulator & Evaluation Layer."""
    from . import training as mod
    return mod

