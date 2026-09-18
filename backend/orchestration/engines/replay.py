from __future__ import annotations

"""
Network Replay Adapter (CTDG)

Runs the temporal frame slicer over the case and raises a REPLAY_ANOMALY finding
for dense burst windows — the temporal signature of coordinated activity. The
frame sequence itself is served by the network-replay endpoint; here we surface
only the analytical finding.
"""
from cognitive.replay import build_frames
from orchestration.contracts import (
    REPLAY_ANOMALY,
    SEVERITY_MEDIUM,
    CaseContext,
    CognitiveResult,
    EngineSpec,
)

ENGINE_NAME = "ReplayEngine"
ENGINE_VERSION = "1.0"


def _timed_events(context: CaseContext) -> list[dict]:
    events = []
    for event in context.events:
        if not event.get("event_timestamp"):
            continue
        meta = event.get("event_metadata") or {}
        et = event.get("event_type")
        u = meta.get("caller") or meta.get("sender") or meta.get("subscriber")
        v = meta.get("callee") or meta.get("recipient")
        if et == "bank_txn":
            u = u or meta.get("from_account") or meta.get("debit_account")
            v = v or meta.get("to_account") or meta.get("credit_account")
            if not u and not v:
                u = meta.get("account")
        if not u and not v:
            continue
        events.append({
            "event_type": et,
            "timestamp": event.get("event_timestamp"),
            "u": u,
            "v": v,
        })
    return events


def applies(context: CaseContext) -> bool:
    return len(_timed_events(context)) >= 3


def run(context: CaseContext) -> list[CognitiveResult]:
    events = _timed_events(context)
    frames = build_frames(events, {"step_seconds": 300, "tau_seconds": 1800.0, "max_frames": 1000})
    burst_frames = [f for f in frames if f.get("burst")]
    if not burst_frames:
        return []

    event_refs = list(dict.fromkeys(
        str(e["id"]) for e in context.events if e.get("event_timestamp")
    ))[:50]
    return [CognitiveResult(
        finding_type=REPLAY_ANOMALY,
        title="Communication/transaction burst detected",
        description=(
            f"{len(burst_frames)} frame(s) show a dense burst of activity, the "
            f"temporal signature of coordination."
        ),
        confidence=None,
        severity=SEVERITY_MEDIUM,
        source_engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        event_refs=event_refs,
        component_scores={
            "burst_frames": len(burst_frames),
            "total_frames": len(frames),
            "window_start": burst_frames[0].get("t"),
            "window_end": burst_frames[-1].get("t"),
        },
        reason_codes=["ACTIVITY_BURST"],
        reasoning="Continuous-time dynamic graph frames with event density above threshold.",
        dedup_key="replay:burst",
    )]


SPEC = EngineSpec(
    name=ENGINE_NAME,
    version=ENGINE_VERSION,
    runner=run,
    description="Temporal burst detection over the CTDG frame slicer.",
    applicability=applies,
    skip_reason="insufficient_timed_events",
)
