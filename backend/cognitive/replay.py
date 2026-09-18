"""CyberDrishti Feature 10 — Network Replay / CTDG frame slicer (isolated build).

Turns a case's timestamped events into an ordered array of graph frames for
the time-scrubber UI. A case network is a Continuous-Time Dynamic Graph:
G(t) = (V(t), E(t)) where an edge exists once its event has occurred. Frames
are the discrete sampling of that continuity:

  active_nodes(t) = {v : first_seen(v) <= t}
  active_edges(t) = {e : t_e <= t}
  edge_opacity(t) = exp(-(t - t_e) / tau)     (older edges fade, never vanish)

Burst windows (configurable density threshold over a sliding window) mark
frames as `burst: true` so the UI can pulse them — communication bursts are
the visual signature of coordination.

The engine is a pure function: events in, frames out. Rendering (React Flow,
opacity transitions, playback speed) belongs to the frontend. No case data,
no thresholds in code.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

DEFAULT_CONFIG: dict[str, Any] = {
    "step_seconds": 60,          # sampling interval between frames
    "tau_seconds": 1800.0,       # opacity decay constant (30 min half-life-ish)
    "max_frames": 2000,          # hard cap; caller should zoom t_start..t_end
    "burst_window_s": 900,       # sliding window for density
    "burst_threshold": 10,       # events within window → burst frame
}


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class Frame:
    t: str
    nodes: list[str]
    edges: list[dict[str, Any]]
    burst: bool
    t_start: str | None = None
    t_end: str | None = None
    new_events: list[dict[str, Any]] | None = None
    summary: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "t_start": self.t_start or self.t,
            "t_end": self.t_end or self.t,
            "nodes": self.nodes,
            "edges": self.edges,
            "burst": self.burst,
            "new_events": self.new_events or [],
            "summary": {
                "burst": self.burst,
                "active_nodes": len(self.nodes),
                "active_edges": len(self.edges),
                "new_events_count": len(self.new_events or []),
                **(self.summary or {}),
            },
        }


def _edge_id(u: str, v: str, te: datetime) -> str:
    return f"{u}->{v}@{te.isoformat()}"


def build_frames(
    events: Sequence[dict[str, Any]], config: dict[str, Any] | None = None
) -> list[Frame]:
    """Events need: timestamp, and either {u, v} for a relation event or
    {node} for a solo event (a solo event activates its node only)."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    if not events:
        return []

    parsed = sorted(
        ((parse_ts(e["timestamp"]), e) for e in events), key=lambda p: p[0]
    )
    t0, t_last = parsed[0][0], parsed[-1][0]
    step = max(int(cfg["step_seconds"]), 1)
    max_frames = max(int(cfg["max_frames"]), 1)
    total_span_s = (t_last - t0).total_seconds()
    if total_span_s == 0:
        n_frames = 1  # single-instant case: one frame
    else:
        # Widen the sampling interval when the requested step would exhaust the
        # frame cap before reaching the last event. Without this, a case whose
        # history spans months but whose step is a few minutes produces frames
        # that stop long before the actual incident — every early frame then
        # shows a single routine node and no edges.
        if max_frames > 1:
            min_step = math.ceil(total_span_s / (max_frames - 1))
            step = max(step, min_step)
        # ceiling: the final frame must land at/after the last event
        n_frames = min(math.ceil(total_span_s / step) + 1, max_frames)

    tau = float(cfg["tau_seconds"])
    burst_window = float(cfg["burst_window_s"])
    burst_threshold = int(cfg["burst_threshold"])

    frames: list[Frame] = []
    edge_start: dict[str, datetime] = {}
    edge_meta: dict[str, dict[str, Any]] = {}
    active_nodes: set[str] = set()
    ei = 0  # next event index to apply

    for fi in range(n_frames):
        t = t0.timestamp() + fi * step
        t_dt = datetime.fromtimestamp(t, tz=t0.tzinfo)
        t_next_dt = (
            datetime.fromtimestamp(t + step, tz=t0.tzinfo)
            if fi < n_frames - 1
            else t_dt
        )

        frame_new_events: list[dict[str, Any]] = []

        # apply all events with ts <= t
        while ei < len(parsed) and parsed[ei][0] <= t_dt:
            te, e = parsed[ei]
            u = e.get("u")
            v = e.get("v")
            node = e.get("node")

            if u and v:
                eid = _edge_id(str(u), str(v), te)
                if eid not in edge_start:
                    edge_start[eid] = te
                edge_meta[eid] = {
                    "rel_type": e.get("rel_type") or e.get("event_type"),
                    "amount": e.get("amount"),
                    "event_id": e.get("id"),
                    "evidence_file_id": e.get("evidence_file_id"),
                    "source_doc": e.get("source_doc"),
                    "source_line": e.get("source_line"),
                    "source_page": e.get("source_page"),
                    "text": e.get("text_content") or e.get("text"),
                    "metadata": e.get("metadata"),
                }
            if u:
                active_nodes.add(str(u))
            if v:
                active_nodes.add(str(v))
            if node:
                active_nodes.add(str(node))

            frame_new_events.append({
                "event_id": e.get("id"),
                "timestamp": te.isoformat(),
                "u": u,
                "v": v,
                "node": node,
                "event_type": e.get("event_type"),
                "rel_type": e.get("rel_type"),
                "amount": e.get("amount"),
                "source_doc": e.get("source_doc"),
                "source_line": e.get("source_line"),
                "text": e.get("text_content") or e.get("text"),
            })
            ei += 1

        visible_edges = []
        for eid, te in edge_start.items():
            age_s = (t_dt - te).total_seconds()
            opacity = math.exp(-age_s / tau) if age_s >= 0 else 0.0
            u, _, rest = eid.partition("->")
            v = rest.rsplit("@", 1)[0]
            em = edge_meta.get(eid, {})
            visible_edges.append({
                "id": eid,
                "u": u,
                "v": v,
                "age_s": age_s,
                "opacity": round(opacity, 4),
                "rel_type": em.get("rel_type"),
                "amount": em.get("amount"),
                "event_id": em.get("event_id"),
                "evidence_file_id": em.get("evidence_file_id"),
                "source_doc": em.get("source_doc"),
                "source_line": em.get("source_line"),
                "source_page": em.get("source_page"),
                "text": em.get("text"),
            })

        burst = _is_burst(parsed, t_dt, burst_window, burst_threshold, ei)
        frames.append(Frame(
            t=t_dt.isoformat(),
            t_start=t_dt.isoformat(),
            t_end=t_next_dt.isoformat(),
            nodes=sorted(active_nodes),
            edges=visible_edges,
            burst=burst,
            new_events=frame_new_events,
            summary={"burst": burst, "active_nodes": len(active_nodes), "active_edges": len(visible_edges)},
        ).to_dict())
    return frames


def _is_burst(
    parsed: list[tuple[datetime, dict[str, Any]]],
    t_dt: datetime,
    window_s: float,
    threshold: int,
    upto: int,
) -> bool:
    """True if >= threshold events occurred within window_s ending at t_dt."""
    lo = t_dt.timestamp() - window_s
    count = sum(1 for te, _ in parsed[:upto] if lo <= te.timestamp() <= t_dt.timestamp())
    return count >= threshold


def timeline_bounds(events: Sequence[dict[str, Any]]) -> dict[str, str | None]:
    if not events:
        return {"t_start": None, "t_end": None}
    times = [parse_ts(e["timestamp"]) for e in events]
    return {"t_start": min(times).isoformat(), "t_end": max(times).isoformat()}
