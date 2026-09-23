import { useState, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import type { CaseEvent } from "../../../data/types";
import { eventsForCase, evidenceLabel, entityById } from "../../../data/corpus";
import { TraceChip } from "../../../components/primitives/TraceChip";
import { useLiveStore } from "../../../state/useLiveStore";
import { Button } from "../../../components/primitives/Button";
import { getUnifiedTimeline } from "../../../api/timeline";
import { getReplayIndex, getHistoricalState } from "../../../api/replay";
import type {
  TimelineEventItem,
  ReplayIndexResponse,
  HistoricalStateProjection,
  TimelineMode,
} from "../../../types/timeline";
import { ReplayDeck } from "./ReplayDeck";
import { ReplayStatePanel } from "./ReplayStatePanel";
import s from "./TimelineTab.module.css";
import cs from "../../../components/case/case.module.css";

const EVENT_KINDS = ["ALL", "COMMUNICATION", "TRANSACTION", "LOCATION", "DEVICE"] as const;

type TimelineItem =
  | { routine: false; event: CaseEvent }
  | { routine: true; key: string; events: CaseEvent[] };

export function TimelineTab({ caseId, onOpenEvidence }: { caseId: string; onOpenEvidence: () => void }) {
  const navigate = useNavigate();
  const { activeTimeline, activeCase } = useLiveStore();
  const [searchParams, setSearchParams] = useSearchParams();

  // Mode: incident | investigation | all
  const [activeMode, setActiveMode] = useState<TimelineMode>("incident");
  const [kindFilter, setKindFilter] = useState<typeof EVENT_KINDS[number]>("ALL");
  const [expandedRoutine, setExpandedRoutine] = useState<Record<string, boolean>>({});

  // Unified timeline from backend
  const [unifiedEvents, setUnifiedEvents] = useState<TimelineEventItem[]>([]);
  const [timeWarning, setTimeWarning] = useState<boolean>(false);
  const [loadingTimeline, setLoadingTimeline] = useState<boolean>(false);

  // Replay state
  const [replayIndex, setReplayIndex] = useState<ReplayIndexResponse | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<number>(1);
  const [historicalState, setHistoricalState] = useState<HistoricalStateProjection | null>(null);
  const [loadingState, setLoadingState] = useState<boolean>(false);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [playSpeed, setPlaySpeed] = useState<number>(1);
  const playTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const entityParam = searchParams.get("entity");

  // Fallback demo data
  const isDemo = caseId === "CYB-2026-042" || caseId === "demo-shadowlink" || activeCase?.id === "CYB-2026-042";
  const evts = activeTimeline && activeTimeline.length > 0
    ? activeTimeline
    : isDemo
    ? eventsForCase(caseId)
    : [];

  // 1. Fetch unified timeline events when mode or category changes
  useEffect(() => {
    let cancelled = false;
    async function loadTimeline() {
      setLoadingTimeline(true);
      try {
        const resp = await getUnifiedTimeline(caseId, {
          mode: activeMode,
          category: kindFilter,
        });
        if (!cancelled && resp && resp.events) {
          setUnifiedEvents(resp.events);
          setTimeWarning(resp.summary.unresolved_time_count > 0);
        }
      } catch (err) {
        // Fall back to local mock data silently if backend is unavailable
      } finally {
        if (!cancelled) setLoadingTimeline(false);
      }
    }
    loadTimeline();
    return () => {
      cancelled = true;
    };
  }, [caseId, activeMode, kindFilter]);

  // 2. Fetch Replay Index when switching to investigation replay mode
  useEffect(() => {
    let cancelled = false;
    if (activeMode === "investigation") {
      async function loadReplayIndex() {
        try {
          const index = await getReplayIndex(caseId);
          if (!cancelled && index) {
            setReplayIndex(index);
            setSelectedVersion(index.current_version || 1);
          }
        } catch {
          // Replay index not available
        }
      }
      loadReplayIndex();
    }
    return () => {
      cancelled = true;
    };
  }, [caseId, activeMode]);

  // 3. Fetch Historical State when selectedVersion changes
  useEffect(() => {
    let cancelled = false;
    if (activeMode === "investigation" && selectedVersion > 0) {
      async function loadState() {
        setLoadingState(true);
        try {
          const state = await getHistoricalState(caseId, selectedVersion);
          if (!cancelled) {
            setHistoricalState(state);
          }
        } catch {
          // Historical state load failed
        } finally {
          if (!cancelled) setLoadingState(false);
        }
      }
      loadState();
    }
    return () => {
      cancelled = true;
    };
  }, [caseId, activeMode, selectedVersion]);

  // 4. Playback timer loop
  useEffect(() => {
    if (isPlaying && replayIndex) {
      const intervalMs = 2000 / playSpeed;
      playTimerRef.current = setTimeout(() => {
        setSelectedVersion((prev) => {
          if (prev >= replayIndex.total_versions) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, intervalMs);
    } else {
      if (playTimerRef.current) {
        clearTimeout(playTimerRef.current);
        playTimerRef.current = null;
      }
    }
    return () => {
      if (playTimerRef.current) clearTimeout(playTimerRef.current);
    };
  }, [isPlaying, selectedVersion, playSpeed, replayIndex]);

  // Filter legacy demo events
  const filteredLegacy = evts.filter((e) => {
    if (kindFilter !== "ALL" && e.kind !== kindFilter) return false;
    if (entityParam && !e.entityIds.includes(entityParam)) return false;
    return true;
  });

  // Collapse consecutive routine/low-signal events
  const items: TimelineItem[] = [];
  for (const ev of filteredLegacy) {
    if (ev.isRoutine) {
      const last = items[items.length - 1];
      if (last && last.routine) last.events.push(ev);
      else items.push({ routine: true, key: `routine-${ev.id}`, events: [ev] });
    } else {
      items.push({ routine: false, event: ev });
    }
  }

  const renderLegacyEvent = (ev: CaseEvent) => (
    <div key={ev.id} className={cs.tlNode}>
      <span className={cs.tlDot} />
      <div className={cs.tlTime}>
        {ev.date} · {ev.ts} · {ev.kind}
      </div>
      <div className={cs.tlTitle}>{ev.label}</div>
      {ev.entityIds.length > 0 && (
        <div className={cs.tlMeta}>
          Entities: {ev.entityIds.map((eid) => entityById.get(eid)?.name ?? eid).join(", ")}
        </div>
      )}
      {ev.evidenceIds.length > 0 && (
        <div style={{ display: "flex", gap: "var(--space-2)", marginTop: "var(--space-2)" }}>
          {ev.evidenceIds.map((eid) => (
            <TraceChip key={eid} label={evidenceLabel(eid)} onClick={onOpenEvidence} />
          ))}
        </div>
      )}
    </div>
  );

  const renderUnifiedEventItem = (item: TimelineEventItem) => {
    const isIncident = item.stream === "INCIDENT";
    return (
      <div key={item.id} className={cs.tlNode}>
        <span
          className={cs.tlDot}
          style={{
            borderColor: isIncident ? "#00F0FF" : "#F59E0B",
            background: isIncident ? "rgba(0,240,255,0.3)" : "rgba(245,158,11,0.3)",
          }}
        />
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
          <span className={`${s.streamPill} ${isIncident ? s.streamIncident : s.streamInvestigation}`}>
            {item.stream}
          </span>
          <span style={{ fontSize: "0.75rem", color: "var(--text-secondary)", fontFamily: "var(--type-mono)" }}>
            {item.event_time
              ? new Date(item.event_time).toLocaleString()
              : "Source time unknown (normalization required)"}
          </span>
          <span
            className={`${s.timeConfidenceBadge} ${
              item.time_confidence === "CONFIRMED"
                ? s.confidenceConfirmed
                : item.time_confidence === "RECORDED_ONLY"
                ? s.confidenceRecordedOnly
                : s.confidenceApprox
            }`}
          >
            {item.time_confidence}
          </span>
          {item.state_version && (
            <span style={{ fontSize: "0.7rem", color: "var(--text-muted)", fontFamily: "var(--type-mono)" }}>
              v{item.state_version}
            </span>
          )}
        </div>

        <div className={cs.tlTitle} style={{ fontSize: "0.9rem" }}>
          {item.summary}
        </div>

        {item.actor && item.actor !== "system" && (
          <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", marginTop: "2px" }}>
            Investigator: <strong>{item.actor}</strong> · Category: {item.category}
          </div>
        )}

        {item.time_warning && (
          <div style={{ fontSize: "0.72rem", color: "#F59E0B", marginTop: "4px" }}>
            ⚠️ {item.time_warning}
          </div>
        )}

        {item.provenance && (item.provenance.file_name || item.provenance.evidence_file_id) && (
          <div className={s.provenanceBox}>
            Source: {item.provenance.file_name || item.provenance.evidence_file_id}
            {item.provenance.page_num ? ` (p. ${item.provenance.page_num})` : ""}
            {item.provenance.line_num ? ` : L${item.provenance.line_num}` : ""}
            {item.provenance.confidence ? ` · conf: ${(item.provenance.confidence * 100).toFixed(0)}%` : ""}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={s.container}>
      {/* Top Header & Mode Switcher */}
      <div className={s.headerBar}>
        <div className={s.titleArea}>
          <div className={s.title}>
            <span>Investigation Chronology & Time-Travel</span>
          </div>
          <p className={s.subtitle}>
            Dual-track temporal reconciliation: inspect the underlying crime events in incident order, or replay the
            investigation&rsquo;s state mutations and human adjudications without altering database rows.
          </p>
        </div>

        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <div className={s.modeToggleGroup}>
            <button
              className={`${s.modeBtn} ${activeMode === "incident" ? s.modeBtnActive : ""}`}
              onClick={() => {
                setActiveMode("incident");
                setIsPlaying(false);
              }}
            >
              Incident Timeline
            </button>
            <button
              className={`${s.modeBtn} ${activeMode === "investigation" ? s.modeBtnActiveReplay : ""}`}
              onClick={() => setActiveMode("investigation")}
            >
              Investigation Replay
            </button>
            <button
              className={`${s.modeBtn} ${activeMode === "all" ? s.modeBtnActive : ""}`}
              onClick={() => {
                setActiveMode("all");
                setIsPlaying(false);
              }}
            >
              Unified Stream
            </button>
          </div>

          <Button
            variant="secondary"
            onClick={() => navigate(`/investigations/${caseId}/network?replay=true`)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              borderColor: "rgba(0, 240, 255, 0.4)",
              color: "#00F0FF",
              background: "rgba(0, 240, 255, 0.08)",
              font: "var(--type-mono-xs)",
              letterSpacing: "0.05em",
              fontWeight: 700,
            }}
          >
            NETWORK REPLAY
          </Button>
        </div>
      </div>

      {/* Warning when unnormalized source times exist */}
      {(timeWarning || filteredLegacy.some((e) => e.timeStatus && e.timeStatus !== "OK")) && (
        <div className={s.warningBanner}>
          <strong style={{ whiteSpace: "nowrap" }}>TIME NORMALIZATION REQUIRED</strong>
          <span>
            Some events lack verified source timestamps and are isolated as &ldquo;Time unknown&rdquo; rather than
            fabricating an event time from ingestion timestamps.
          </span>
        </div>
      )}

      {/* Mode A & Mode C: Incident / Unified Timeline Stream */}
      {activeMode !== "investigation" && (
        <>
          {/* Category Filter Pills */}
          <div className={s.filterPills}>
            {EVENT_KINDS.map((k) => (
              <button
                key={k}
                className={`${cs.evPill} ${kindFilter === k ? cs.evPillOn : ""}`}
                onClick={() => setKindFilter(k)}
              >
                {k}
              </button>
            ))}
            {entityParam && (
              <button
                className={`${cs.evPill} ${cs.evPillOn}`}
                style={{ color: "var(--intel)", borderColor: "var(--intel)" }}
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  next.delete("entity");
                  setSearchParams(next, { replace: true });
                }}
              >
                ENTITY: {entityById.get(entityParam)?.name || entityParam} ✕
              </button>
            )}
          </div>

          {loadingTimeline ? (
            <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>
              Loading temporal stream...
            </div>
          ) : unifiedEvents.length > 0 ? (
            <div className={cs.timelineTrack}>
              <div className={cs.timelineLine} />
              {unifiedEvents.map(renderUnifiedEventItem)}
            </div>
          ) : evts.length === 0 ? (
            <div
              style={{
                padding: "var(--space-12) var(--space-6)",
                textAlign: "center",
                background: "var(--surface-1)",
                border: "1px dashed var(--line-strong)",
                borderRadius: "var(--radius-card)",
              }}
            >
              <div
                style={{
                  font: "var(--type-mono-xs)",
                  color: "var(--intel)",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  marginBottom: "var(--space-2)",
                }}
              >
                Chronological Forensics
              </div>
              <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
                Timeline Sequence Not Yet Established
              </h3>
              <p
                className="measure"
                style={{
                  color: "var(--text-secondary)",
                  font: "var(--type-body-sm)",
                  margin: "0 auto var(--space-6) auto",
                }}
              >
                Reconstructed timelines across call logs, messaging timestamps, bank transactions, and cell tower
                telemetry will appear automatically once evidence is ingested.
              </p>
              <Button variant="primary" icon="plus" onClick={onOpenEvidence}>
                Ingest Evidence to Build Timeline
              </Button>
            </div>
          ) : (
            <div className={cs.timelineTrack}>
              <div className={cs.timelineLine} />
              {items.map((item) =>
                item.routine ? (
                  <div key={item.key} className={cs.tlNode}>
                    <span className={cs.tlDot} style={{ opacity: 0.5 }} />
                    <div className={cs.tlTime}>{item.events[0]?.date} · ROUTINE ACTIVITY</div>
                    <div className={cs.tlTitle} style={{ color: "var(--text-secondary)" }}>
                      {item.events.length} routine events
                    </div>
                    <div style={{ marginTop: "var(--space-2)" }}>
                      <Button
                        variant="ghost"
                        onClick={() =>
                          setExpandedRoutine((p) => ({ ...p, [item.key]: !p[item.key] }))
                        }
                      >
                        {expandedRoutine[item.key] ? "Collapse" : "Expand"}
                      </Button>
                    </div>
                    {expandedRoutine[item.key] && (
                      <div style={{ marginTop: "var(--space-3)", opacity: 0.9 }}>
                        {item.events.map(renderLegacyEvent)}
                      </div>
                    )}
                  </div>
                ) : (
                  renderLegacyEvent(item.event)
                )
              )}
            </div>
          )}
        </>
      )}

      {/* Mode B: Investigation Replay (Time Travel & Historical Projection) */}
      {activeMode === "investigation" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {replayIndex ? (
            <>
              <ReplayDeck
                currentVersion={selectedVersion}
                totalVersions={replayIndex.total_versions}
                currentCaseVersion={replayIndex.current_version}
                versions={replayIndex.versions}
                isPlaying={isPlaying}
                playSpeed={playSpeed}
                onSelectVersion={(v) => setSelectedVersion(v)}
                onTogglePlay={() => setIsPlaying(!isPlaying)}
                onChangeSpeed={(s) => setPlaySpeed(s)}
              />

              <ReplayStatePanel projection={historicalState} loading={loadingState} />
            </>
          ) : (
            <div style={{ padding: "32px", textAlign: "center", color: "var(--text-secondary)" }}>
              Loading investigation state checkpoints...
            </div>
          )}
        </div>
      )}
    </div>
  );
}
