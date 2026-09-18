from __future__ import annotations

"""
CyberDrishti AI — Cognitive Contracts

The shapes every cognitive engine and the orchestrator agree on:

  • CognitiveResult — the common output of any engine (mapped to a Finding)
  • CaseContext     — the read-only case snapshot engines are given
  • EngineSpec      — how an engine is registered, when it applies, how it runs

Keeping these independent of the database and FastAPI means engines stay
testable in isolation and the orchestrator stays the only integration point.
"""
import hashlib
import inspect
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, Sequence, Union


# ── Finding vocabulary ────────────────────────────────────────────────────────

CONTRADICTION       = "CONTRADICTION"
HIDDEN_LINK         = "HIDDEN_LINK"
HYPOTHESIS          = "HYPOTHESIS"
UNCERTAINTY         = "UNCERTAINTY"
NEXT_BEST_ACTION    = "NEXT_BEST_ACTION"
MO_MATCH            = "MO_MATCH"
FINGERPRINT_VARIANT = "FINGERPRINT_VARIANT"
REPLAY_ANOMALY      = "REPLAY_ANOMALY"
CROSS_CASE_SIGNAL   = "CROSS_CASE_SIGNAL"
COUNTERFACTUAL      = "COUNTERFACTUAL"
VERIFICATION        = "VERIFICATION"
BEHAVIORAL_ANOMALY  = "BEHAVIORAL_ANOMALY"
DEFENCE_CHALLENGE   = "DEFENCE_CHALLENGE"

FINDING_TYPES = frozenset({
    CONTRADICTION, HIDDEN_LINK, HYPOTHESIS, UNCERTAINTY, NEXT_BEST_ACTION,
    MO_MATCH, FINGERPRINT_VARIANT, REPLAY_ANOMALY, CROSS_CASE_SIGNAL,
    COUNTERFACTUAL, VERIFICATION, BEHAVIORAL_ANOMALY, DEFENCE_CHALLENGE,
})

SEVERITY_LOW      = "LOW"
SEVERITY_MEDIUM   = "MEDIUM"
SEVERITY_HIGH     = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"

SEVERITIES = (SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH, SEVERITY_CRITICAL)
HIGH_PRIORITY_SEVERITIES = frozenset({SEVERITY_HIGH, SEVERITY_CRITICAL})

STATUS_OPEN       = "OPEN"
STATUS_CONFIRMED  = "CONFIRMED"
STATUS_DISMISSED  = "DISMISSED"
STATUS_SUPERSEDED = "SUPERSEDED"

STATUSES = (STATUS_OPEN, STATUS_CONFIRMED, STATUS_DISMISSED, STATUS_SUPERSEDED)

# Human-review states that automated re-analysis must never clobber.
HUMAN_REVIEW_STATUSES = frozenset({STATUS_CONFIRMED, STATUS_DISMISSED})


# ── CognitiveResult ───────────────────────────────────────────────────────────

@dataclass
class CognitiveResult:
    """
    A single intelligence output from a cognitive engine.

    Engines never touch the database — they return these and the orchestrator
    persists them as InvestigationFinding rows.
    """
    finding_type: str
    title: str
    description: str = ""
    confidence: float | None = None
    severity: str = SEVERITY_MEDIUM
    status: str = STATUS_OPEN
    source_engine: str = ""
    engine_version: str = ""
    entity_refs: list[str] = field(default_factory=list)
    event_refs: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    component_scores: dict[str, Any] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    reasoning: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    observed_at: datetime | None = None
    # Optional stable identity override; otherwise derived from type/engine/refs.
    dedup_key: str | None = None

    def __post_init__(self) -> None:
        if self.finding_type not in FINDING_TYPES:
            raise ValueError(f"unknown finding_type: {self.finding_type!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity!r}")
        if self.status not in STATUSES:
            raise ValueError(f"invalid status: {self.status!r}")
        if self.confidence is not None:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def fingerprint(self) -> str:
        """Stable identity so repeated analysis updates instead of duplicating."""
        if self.dedup_key:
            seed = f"dedup:{self.dedup_key}"
        else:
            seed = "|".join([
                self.finding_type,
                self.source_engine,
                self.title.strip().lower(),
                ",".join(sorted(self.entity_refs)),
                ",".join(sorted(self.event_refs)),
                ",".join(sorted(self.evidence_refs)),
            ])
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fingerprint"] = self.fingerprint()
        return data


# ── CaseContext ───────────────────────────────────────────────────────────────

@dataclass
class CaseContext:
    """
    Read-only snapshot of everything an engine may reason over. Populated once
    per orchestration run so every engine sees the same case state.
    """
    case_id: str
    case_number: str = ""
    case_fir_number: str | None = None
    case_created_at: str | None = None
    evidence_files: list[dict[str, Any]] = field(default_factory=list)
    evidence_types: set[str] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    # Populated by the orchestrator only when authorised cross-case analysis is
    # enabled; the cross-case engine never reaches across case boundaries itself.
    cross_case_collisions: list[dict[str, Any]] = field(default_factory=list)

    def events_of_type(self, *event_types: str) -> list[dict[str, Any]]:
        wanted = set(event_types)
        return [e for e in self.events if e.get("event_type") in wanted]

    def has_evidence_type(self, *types: str) -> bool:
        return bool(self.evidence_types & {t.lower() for t in types})

    def has_event_type(self, *event_types: str) -> bool:
        wanted = set(event_types)
        return any(e.get("event_type") in wanted for e in self.events)


# ── EngineSpec ────────────────────────────────────────────────────────────────

EngineRunner = Union[
    Callable[[CaseContext], Sequence[CognitiveResult]],
    Callable[[CaseContext], Awaitable[Sequence[CognitiveResult]]],
]


@dataclass
class EngineSpec:
    """
    Registration record for one cognitive engine.

    applicability() decides whether the orchestrator runs the engine for a given
    case state — engines are never run blindly against evidence they cannot use.
    """
    name: str
    version: str
    runner: EngineRunner
    description: str = ""
    applicability: Callable[[CaseContext], bool] | None = None
    requires_evidence_types: frozenset[str] = frozenset()
    requires_event_types: frozenset[str] = frozenset()
    skip_reason: str = "not_applicable"

    def applies(self, context: CaseContext) -> bool:
        if self.applicability is not None:
            return bool(self.applicability(context))
        if self.requires_event_types and not context.has_event_type(*self.requires_event_types):
            return False
        if self.requires_evidence_types and not context.has_evidence_type(*self.requires_evidence_types):
            return False
        return True


async def resolve_results(spec: EngineSpec, context: CaseContext) -> list[CognitiveResult]:
    """Run an engine (sync or async) and normalise its output to a list."""
    output = spec.runner(context)
    if inspect.isawaitable(output):
        output = await output
    results = list(output or [])
    for result in results:
        if not isinstance(result, CognitiveResult):
            raise TypeError(
                f"engine {spec.name!r} returned {type(result).__name__}, expected CognitiveResult"
            )
    return results
