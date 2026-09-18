/**
 * CyberDrishti AI — Case Intelligence (findings-first cognitive view)
 *
 * This is the primary Cognitive experience: what NETRA found, why, how
 * confident it is, which evidence supports it, and where it appears in the
 * graph. Engine detail panels live below this as a drill-down.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../../components/primitives/Button";
import {
  findingsApi,
  type Finding,
  type FindingSeverity,
  type IntelligenceState,
} from "../../../api/findings";

const SEVERITY_COLOR: Record<FindingSeverity, string> = {
  CRITICAL: "var(--critical)",
  HIGH: "var(--warning)",
  MEDIUM: "var(--intel)",
  LOW: "var(--text-muted)",
};

const SEVERITY_RANK: Record<FindingSeverity, number> = {
  CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3,
};

const TYPE_LABEL: Record<string, string> = {
  CONTRADICTION: "CONTRADICTION",
  HIDDEN_LINK: "HIDDEN LINK",
  HYPOTHESIS: "HYPOTHESIS",
  UNCERTAINTY: "UNCERTAINTY",
  NEXT_BEST_ACTION: "NEXT BEST ACTION",
  MO_MATCH: "MO MATCH",
  FINGERPRINT_VARIANT: "EVIDENCE VARIANT",
  REPLAY_ANOMALY: "REPLAY ANOMALY",
  CROSS_CASE_SIGNAL: "CROSS-CASE SIGNAL",
  COUNTERFACTUAL: "COUNTERFACTUAL",
  VERIFICATION: "VERIFICATION FLAG",
};

const FILTERS: Array<{ id: "ALL" | FindingSeverity; label: string }> = [
  { id: "ALL", label: "All" },
  { id: "CRITICAL", label: "Critical" },
  { id: "HIGH", label: "High" },
  { id: "MEDIUM", label: "Medium" },
  { id: "LOW", label: "Low" },
];

function pct(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

/** Never present a rule score / similarity as a calibrated probability. */
function confidenceLabel(status?: string): string {
  switch (status) {
    case "CALIBRATED": return "Calibrated confidence";
    case "DIRECT_OBSERVATION": return "Direct observation";
    case "INFERRED": return "Inferred confidence";
    case "RULE_BASED": return "Rule score";
    case "SCREENING": return "Screening similarity";
    case "SIMULATION": return "Hypothetical simulation";
    case "UNRESOLVED": return "Confidence unresolved";
    default: return "Not calibrated";
  }
}

/** Map an API failure to an honest, investigator-facing state label. */
function classifyErrorStatus(status: number | null | undefined): { label: string; detail: string } {
  switch (status) {
    case 404:
      return { label: "CASE NOT FOUND", detail: "This case could not be found or you do not have access to it." };
    case 403:
      return { label: "ACCESS DENIED", detail: "You do not have access to this case." };
    case 401:
      return { label: "AUTHENTICATION REQUIRED", detail: "Your session has expired. Please sign in again." };
    default:
      if (typeof status === "number" && status >= 500) {
        return { label: "SERVICE ERROR", detail: "The case intelligence service could not complete the request." };
      }
      return { label: "CASE INTELLIGENCE UNAVAILABLE", detail: "The case state could not be loaded." };
  }
}

export function CaseIntelligence({ caseId }: { caseId: string }) {
  const navigate = useNavigate();
  const [state, setState] = useState<IntelligenceState | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorInfo, setErrorInfo] = useState<{ label: string; detail: string } | null>(null);
  const [severityFilter, setSeverityFilter] = useState<"ALL" | FindingSeverity>("ALL");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setErrorInfo(null);
    try {
      const [stateRes, findingsRes] = await Promise.all([
        findingsApi.state(caseId),
        findingsApi.list(caseId, { limit: 500 }),
      ]);
      setState(stateRes);
      setFindings(findingsRes.findings || []);
    } catch (err) {
      const status = (err as { status?: number })?.status ?? null;
      setError((err as Error)?.message || "Unable to load case intelligence.");
      setErrorInfo(classifyErrorStatus(status));
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    load();
    setExpanded(new Set());
  }, [load]);

  const runAnalysis = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      await findingsApi.analyze(caseId);
      await load();
    } catch (err) {
      setError((err as Error)?.message || "Cognitive analysis failed.");
    } finally {
      setRunning(false);
    }
  }, [caseId, load]);

  const sorted = useMemo(() => {
    const filtered = severityFilter === "ALL"
      ? findings
      : findings.filter(f => f.severity === severityFilter);
    return [...filtered].sort((a, b) => {
      const rank = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
      if (rank !== 0) return rank;
      return (b.confidence ?? -1) - (a.confidence ?? -1);
    });
  }, [findings, severityFilter]);

  const toggle = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const openEvidence = () => navigate(`/investigations/${caseId}/evidence`);
  const openGraph = (entityRef?: string) => {
    const q = entityRef ? `?select=${encodeURIComponent(entityRef)}` : "";
    navigate(`/investigations/${caseId}/network${q}`);
  };

  const findingByType = state?.findings_by_type || {};

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      {/* Header */}
      <div style={{
        background: "var(--surface-1)",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-card)",
        padding: "var(--space-6)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--space-4)", flexWrap: "wrap" }}>
          <div>
            <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", letterSpacing: "0.08em", textTransform: "uppercase" }}>
              Case Intelligence
            </div>
            <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", margin: "4px 0 0", maxWidth: 620 }}>
              What NETRA found in this case, why, and exactly which evidence supports it.
            </p>
          </div>
          <Button variant="primary" onClick={runAnalysis} disabled={running}>
            {running ? "Analysing…" : "Run analysis"}
          </Button>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", marginTop: "var(--space-6)", flexWrap: "wrap" }}>
          {running ? (
            <StateChip label="ANALYZING" color="var(--warning)" />
          ) : loading ? (
            <StateChip label="LOADING" color="var(--text-muted)" />
          ) : !state ? (
            <StateChip label={errorInfo?.label || "CASE INTELLIGENCE UNAVAILABLE"} color="var(--critical)" />
          ) : state.evidence_count === 0 ? (
            <StateChip label="EMPTY CASE" color="var(--text-muted)" />
          ) : state.last_run_at ? (
            <StateChip label="ANALYZED" color="var(--verified)" />
          ) : (
            <StateChip label="NOT ANALYZED" color="var(--warning)" />
          )}
        </div>

        {loading ? (
          <div style={{ marginTop: "var(--space-4)", color: "var(--text-muted)", font: "var(--type-mono-xs)" }}>
            Loading case intelligence…
          </div>
        ) : !state ? (
          // Never render counts when the case state could not be loaded — zeros
          // would falsely imply the case is empty.
          <div style={{
            marginTop: "var(--space-4)",
            padding: "var(--space-4)",
            background: "var(--critical-tint)",
            border: "1px solid rgba(255,92,92,0.3)",
            borderRadius: "var(--radius-input)",
            color: "var(--text-secondary)",
            font: "var(--type-body-sm)",
          }}>
            <strong style={{ color: "var(--critical)" }}>
              {errorInfo?.label || "CASE INTELLIGENCE UNAVAILABLE"}
            </strong>
            <div style={{ marginTop: 4 }}>{errorInfo?.detail || error}</div>
            <div style={{ marginTop: 4, color: "var(--text-muted)" }}>
              Counts are not shown because the case state could not be loaded.
            </div>
          </div>
        ) : (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
            gap: "var(--space-4)",
            marginTop: "var(--space-6)",
          }}>
            <Metric label="Evidence" value={state.evidence_count} />
            <Metric label="Entities" value={state.entity_count} />
            <Metric label="Relationships" value={state.relationship_count}
                    sub={`${state.observed_relationship_count} observed · ${state.inferred_relationship_count} inferred`} />
            <Metric label="Findings" value={state.finding_count} />
            <Metric label="High priority" value={state.high_priority_count}
                    color={state.high_priority_count > 0 ? "var(--critical)" : undefined} />
          </div>
        )}

        {state?.last_run_at && (
          <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: "var(--space-4)" }}>
            Last analysis · {new Date(state.last_run_at).toLocaleString()}
          </div>
        )}

        {state?.engine_status && Object.keys(state.engine_status).length > 0 && (
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "var(--space-4)" }}>
            {Object.entries(state.engine_status).map(([name, status]) => (
              <span
                key={name}
                title={status.reason || status.error || status.status}
                style={{
                  padding: "2px 8px",
                  borderRadius: 999,
                  font: "var(--type-mono-xs)",
                  border: "1px solid var(--line)",
                  color: status.status === "ok" ? "var(--verified)"
                    : status.status === "error" ? "var(--critical)"
                    : "var(--text-muted)",
                }}
              >
                {name.replace("Engine", "")} · {status.status}
              </span>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div style={{ padding: "var(--space-4)", background: "var(--critical-tint)", border: "1px solid rgba(255,92,92,0.3)", borderRadius: "var(--radius-input)", color: "var(--critical)", font: "var(--type-body-sm)" }}>
          {error}
        </div>
      )}

      {/* Findings */}
      <div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--space-4)", flexWrap: "wrap", marginBottom: "var(--space-3)" }}>
          <div className="t-label">
            Findings <span style={{ color: "var(--text-muted)" }}>· {sorted.length}</span>
          </div>
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {FILTERS.map(f => (
              <button
                key={f.id}
                onClick={() => setSeverityFilter(f.id)}
                style={{
                  padding: "4px 12px",
                  borderRadius: 999,
                  border: `1px solid ${severityFilter === f.id ? "var(--accent)" : "var(--line)"}`,
                  background: severityFilter === f.id ? "rgba(var(--accent-rgb, 88, 166, 255), 0.08)" : "transparent",
                  color: severityFilter === f.id ? "var(--accent)" : "var(--text-secondary)",
                  font: "var(--type-mono-xs)",
                  cursor: "pointer",
                }}
              >
                {f.label}
                {f.id !== "ALL" && findingByType && (
                  <span style={{ opacity: 0.6 }}> {findings.filter(x => x.severity === f.id).length}</span>
                )}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div style={{ padding: "var(--space-10)", textAlign: "center", color: "var(--text-muted)", font: "var(--type-mono-xs)" }}>
            Loading case intelligence…
          </div>
        ) : !state ? (
          <div style={{
            padding: "var(--space-8) var(--space-6)",
            textAlign: "center",
            border: "1px dashed var(--line-strong)",
            borderRadius: "var(--radius-card)",
            color: "var(--text-secondary)",
            font: "var(--type-body-sm)",
          }}>
            Findings are not shown because the case state could not be loaded.
          </div>
        ) : sorted.length === 0 ? (
          <div style={{
            padding: "var(--space-10) var(--space-6)",
            textAlign: "center",
            border: "1px dashed var(--line-strong)",
            borderRadius: "var(--radius-card)",
            color: "var(--text-secondary)",
          }}>
            <div style={{ font: "var(--type-body)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
              No findings yet
            </div>
            <p style={{ font: "var(--type-body-sm)", maxWidth: 520, margin: "0 auto var(--space-4)" }}>
              {state?.evidence_count
                ? "Run analysis to let NETRA evaluate the ingested evidence."
                : "Ingest evidence, then run analysis. Findings appear here with their supporting evidence."}
            </p>
            <Button variant={state?.evidence_count ? "primary" : "secondary"} onClick={state?.evidence_count ? runAnalysis : openEvidence} disabled={running}>
              {state?.evidence_count ? "Run analysis" : "Go to evidence"}
            </Button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
            {sorted.map(finding => (
              <FindingCard
                key={finding.id}
                finding={finding}
                expanded={expanded.has(finding.id)}
                onToggle={() => toggle(finding.id)}
                onOpenEvidence={openEvidence}
                onOpenGraph={openGraph}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function StateChip({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      padding: "2px 10px",
      borderRadius: 999,
      border: `1px solid ${color}`,
      color,
      font: "var(--type-mono-xs)",
      letterSpacing: "0.06em",
    }}>
      {label}
    </span>
  );
}

function Metric({ label, value, sub, color }: { label: string; value: number; sub?: string; color?: string }) {  return (
    <div>
      <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ font: "var(--type-title-2)", color: color || "var(--text-primary)" }}>{value}</div>
      {sub && <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>{sub}</div>}
    </div>
  );
}

function FindingCard({
  finding,
  expanded,
  onToggle,
  onOpenEvidence,
  onOpenGraph,
}: {
  finding: Finding;
  expanded: boolean;
  onToggle: () => void;
  onOpenEvidence: () => void;
  onOpenGraph: (entityRef?: string) => void;
}) {
  const severityColor = SEVERITY_COLOR[finding.severity];
  const entityRef = finding.entity_refs[0];

  return (
    <article style={{
      display: "flex",
      gap: "var(--space-4)",
      padding: "var(--space-4) var(--space-5)",
      background: "var(--surface-2)",
      border: "1px solid var(--line)",
      borderRadius: "var(--radius-input)",
    }}>
      <div style={{ width: 3, borderRadius: 999, background: severityColor, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", flexWrap: "wrap" }}>
          <span style={{
            padding: "2px 8px",
            borderRadius: 999,
            font: "var(--type-mono-xs)",
            letterSpacing: "0.06em",
            color: severityColor,
            border: `1px solid ${severityColor}`,
          }}>
            {TYPE_LABEL[finding.finding_type] || finding.finding_type}
          </span>
          <span style={{ font: "var(--type-mono-xs)", color: severityColor }}>{finding.severity}</span>
          {finding.confidence_details ? (
            <>
              <span style={{
                padding: "2px 6px",
                borderRadius: 4,
                font: "var(--type-mono-xs)",
                fontWeight: 600,
                background: finding.confidence_details.epistemic_tier === "DIRECT_OBSERVATION" ? "rgba(6, 182, 212, 0.12)" :
                            finding.confidence_details.epistemic_tier === "RULE_BASED" ? "rgba(245, 158, 11, 0.12)" :
                            finding.confidence_details.epistemic_tier === "INFERRED" ? "rgba(168, 85, 247, 0.12)" :
                            finding.confidence_details.epistemic_tier === "SCREENING" ? "rgba(59, 130, 246, 0.12)" :
                            "rgba(148, 163, 184, 0.12)",
                color: finding.confidence_details.epistemic_tier === "DIRECT_OBSERVATION" ? "#06b6d4" :
                       finding.confidence_details.epistemic_tier === "RULE_BASED" ? "#f59e0b" :
                       finding.confidence_details.epistemic_tier === "INFERRED" ? "#c084fc" :
                       finding.confidence_details.epistemic_tier === "SCREENING" ? "#60a5fa" :
                       "var(--text-muted)",
                border: "1px solid currentColor",
              }}>
                {finding.confidence_details.epistemic_tier}
              </span>
              <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                {finding.confidence_details.score_type}: {finding.confidence !== null ? finding.confidence : "—"}
              </span>
            </>
          ) : (
            <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
              {finding.confidence !== null
                ? `${confidenceLabel(finding.confidence_status)} ${pct(finding.confidence)}`
                : confidenceLabel(finding.confidence_status)}
            </span>
          )}
          {finding.status !== "OPEN" && (
            <span style={{ font: "var(--type-mono-xs)", color: "var(--intel)" }}>{finding.status}</span>
          )}
        </div>

        <h4 style={{ font: "var(--type-body)", color: "var(--text-primary)", margin: "var(--space-2) 0 4px", fontWeight: 600 }}>
          {finding.title}
        </h4>
        {finding.description && (
          <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", margin: 0, lineHeight: 1.5 }}>
            {finding.description}
          </p>
        )}

        <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap", marginTop: "var(--space-3)", font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
          {finding.source_engine && <span>Engine · {finding.source_engine}{finding.engine_version ? ` v${finding.engine_version}` : ""}</span>}
          {finding.evidence_refs.length > 0 && <span>Evidence · {finding.evidence_refs.length}</span>}
          {finding.event_refs.length > 0 && <span>Events · {finding.event_refs.length}</span>}
          {finding.entity_refs.length > 0 && <span>Entities · {finding.entity_refs.length}</span>}
        </div>

        {finding.reason_codes.length > 0 && (
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", marginTop: "var(--space-2)" }}>
            {finding.reason_codes.map(code => (
              <span key={code} style={{
                padding: "2px 8px",
                borderRadius: 999,
                background: "rgba(255,255,255,0.04)",
                color: "var(--text-muted)",
                font: "var(--type-mono-xs)",
              }}>
                {code}
              </span>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: "var(--space-3)", marginTop: "var(--space-4)", flexWrap: "wrap" }}>
          <Button variant="secondary" onClick={onToggle}>{expanded ? "Hide why" : "Why?"}</Button>
          {finding.evidence_refs.length > 0 && (
            <Button variant="secondary" onClick={onOpenEvidence}>View evidence</Button>
          )}
          <Button variant="secondary" onClick={() => onOpenGraph(entityRef)}>View graph</Button>
        </div>

        {expanded && (
          <div style={{ marginTop: "var(--space-4)", borderTop: "1px solid var(--line)", paddingTop: "var(--space-4)" }}>
            {finding.reasoning && (
              <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginTop: 0, lineHeight: 1.5 }}>
                {finding.reasoning}
              </p>
            )}

            {Object.keys(finding.component_scores).length > 0 && (
              <div style={{ marginTop: "var(--space-3)" }}>
                <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                  Component scores
                </div>
                <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap", font: "var(--type-mono-xs)", color: "var(--text-secondary)" }}>
                  {Object.entries(finding.component_scores).map(([key, value]) => (
                    <span key={key}>{key}: <b style={{ color: "var(--text-primary)" }}>{formatScore(value)}</b></span>
                  ))}
                </div>
              </div>
            )}

            <ProvenanceList title="Evidence references" items={finding.evidence_refs} />
            <ProvenanceList title="Event references" items={finding.event_refs} />
            <ProvenanceList title="Entity references" items={finding.entity_refs} />

            {finding.citations.length > 0 && (
              <div style={{ marginTop: "var(--space-3)" }}>
                <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                  Citations
                </div>
                <pre style={{
                  margin: 0,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  font: "var(--type-mono-xs)",
                  color: "var(--text-secondary)",
                  maxHeight: 200,
                  overflow: "auto",
                }}>
                  {JSON.stringify(finding.citations, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

function ProvenanceList({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div style={{ marginTop: "var(--space-3)" }}>
      <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
        {title}
      </div>
      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
        {items.map(item => (
          <span key={item} style={{ padding: "2px 8px", borderRadius: 999, background: "rgba(255,255,255,0.04)", color: "var(--text-secondary)", font: "var(--type-mono-xs)" }}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function formatScore(value: unknown): string {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return Array.isArray(value) ? `[${value.length}]` : "{…}";
  return String(value);
}
