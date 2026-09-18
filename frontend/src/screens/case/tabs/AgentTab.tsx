/**
 * CyberDrishti AI — Agent / ArmorIQ Investigation Dashboard
 * Launch autonomous investigations, approve/reject holds, view audit trail.
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  agentApi,
  type AgentStatusResponse,
  type AgentActionsResponse,
  type AgentHoldInfo,
  type AgentAuditTrailResponse,
} from "../../../api/agent";
import { Button } from "../../../components/primitives/Button";

type ViewMode = "status" | "actions" | "audit";

const STATUS_COLORS: Record<string, string> = {
  idle: "var(--text-muted)",
  investigating: "var(--accent)",
  completed: "var(--positive, #4ade80)",
  error: "var(--critical)",
  failed: "var(--critical)",
  failed_case_load: "var(--critical)",
  awaiting_approval: "var(--warning, #f59e0b)",
};

const ACTION_BADGES: Record<string, { label: string; color: string }> = {
  executed: { label: "DONE", color: "var(--positive, #4ade80)" },
  blocked: { label: "BLOCKED", color: "var(--critical)" },
  approved: { label: "APPROVED", color: "var(--positive, #4ade80)" },
  rejected: { label: "REJECTED", color: "var(--critical)" },
  pending: { label: "PENDING", color: "var(--warning, #f59e0b)" },
};

export function AgentTab({ caseId }: { caseId: string }) {
  const [viewMode, setViewMode] = useState<ViewMode>("status");
  const [status, setStatus] = useState<AgentStatusResponse | null>(null);
  const [actions, setActions] = useState<AgentActionsResponse | null>(null);
  const [auditTrail, setAuditTrail] = useState<AgentAuditTrailResponse | null>(null);
  const [launching, setLaunching] = useState(false);
  const [holdReason, setHoldReason] = useState("");
  const [decidingHold, setDecidingHold] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load status on mount
  const fetchStatus = useCallback(async () => {
    try {
      const res = await agentApi.status(caseId, sessionId || undefined);
      setStatus(res);
      if (res.session_id && !sessionId) setSessionId(res.session_id);
      return res;
    } catch {
      // Agent might not have been run yet — that's fine
      return null;
    }
  }, [caseId, sessionId]);

  useEffect(() => {
    fetchStatus();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchStatus]);

  // Poll while investigating
  useEffect(() => {
    if (status?.status === "investigating" || status?.status === "awaiting_approval") {
      pollRef.current = setInterval(fetchStatus, 3000);
      return () => { if (pollRef.current) clearInterval(pollRef.current); };
    } else {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }
  }, [status?.status, fetchStatus]);

  const launchInvestigation = async () => {
    setLaunching(true);
    setError(null);
    try {
      const res = await agentApi.run(caseId);
      setSessionId(res.session_id);
      await fetchStatus();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to launch investigation");
    } finally {
      setLaunching(false);
    }
  };

  const loadActions = async () => {
    try {
      const res = await agentApi.actions(caseId);
      setActions(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load actions");
    }
  };

  const loadAuditTrail = async () => {
    try {
      const res = await agentApi.auditTrail(caseId);
      setAuditTrail(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load audit trail");
    }
  };

  const handleTabSwitch = (mode: ViewMode) => {
    setViewMode(mode);
    if (mode === "actions" && !actions) loadActions();
    if (mode === "audit" && !auditTrail) loadAuditTrail();
  };

  const handleApprove = async (holdId: string) => {
    setDecidingHold(true);
    try {
      await agentApi.approveHold(holdId, holdReason || undefined);
      setHoldReason("");
      await fetchStatus();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to approve hold");
    } finally {
      setDecidingHold(false);
    }
  };

  const handleReject = async (holdId: string) => {
    setDecidingHold(true);
    try {
      await agentApi.rejectHold(holdId, holdReason || undefined);
      setHoldReason("");
      await fetchStatus();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to reject hold");
    } finally {
      setDecidingHold(false);
    }
  };

  const fieldStyle: React.CSSProperties = {
    width: "100%", padding: "8px 12px", background: "var(--surface-0)",
    border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
    color: "var(--text-primary)", font: "var(--type-body-sm)", outline: "none",
  };

  const isActive = status?.status === "investigating" || status?.status === "awaiting_approval";

  return (
    <div style={{ padding: "var(--space-4) 0" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: "var(--space-6)", flexWrap: "wrap", gap: "var(--space-3)",
      }}>
        <div>
          <h2 className="t-title-3" style={{ color: "var(--text-primary)", margin: 0, display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 22 }}>🤖</span> Autonomous Investigation
          </h2>
          <p className="t-body-sm" style={{ color: "var(--text-muted)", marginTop: 4 }}>
            ArmorIQ-protected AI agent with human-in-the-loop hold approval
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          {!isActive && (
            <Button variant="primary" onClick={launchInvestigation} disabled={launching}>
              {launching ? "Launching…" : "▶ Start Investigation"}
            </Button>
          )}
          {isActive && (
            <span style={{
              padding: "6px 14px", background: "rgba(99, 102, 241, 0.1)",
              borderRadius: 20, font: "var(--type-mono-xs)",
              color: "var(--accent)", display: "flex", alignItems: "center", gap: 6,
            }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--accent)", animation: "pulse 1.5s infinite" }} />
              Investigation Active
            </span>
          )}
        </div>
      </div>

      {/* Status Card */}
      {status && (
        <div style={{
          padding: "var(--space-5)", background: "var(--surface-1)",
          border: "1px solid var(--line)", borderRadius: "var(--radius-card)",
          marginBottom: "var(--space-5)",
        }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: "var(--space-4)" }}>
            <div>
              <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>STATUS</div>
              <div style={{ color: STATUS_COLORS[status.status] || "var(--text-primary)", fontWeight: 600, textTransform: "uppercase" }}>
                {status.status.replace(/_/g, " ")}
              </div>
            </div>
            <div>
              <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>ACTIONS</div>
              <div className="t-title-3" style={{ color: "var(--accent)" }}>{status.action_count}</div>
            </div>
            <div>
              <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>SESSION</div>
              <div className="t-mono-xs" style={{ color: "var(--text-secondary)" }}>
                {status.session_id ? status.session_id.slice(0, 8) + "…" : "—"}
              </div>
            </div>
            {status.started_at && (
              <div>
                <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>STARTED</div>
                <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
                  {new Date(status.started_at).toLocaleString()}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Case-load failure — investigation hard-stopped, zero actions executed */}
      {status?.status === "failed_case_load" && (
        <div style={{
          padding: "var(--space-4) var(--space-5)", marginBottom: "var(--space-5)",
          background: "var(--critical-tint)", border: "1px solid rgba(255,92,92,0.35)",
          borderRadius: "var(--radius-card)", color: "var(--critical)",
        }}>
          <strong>CASE LOAD FAILED</strong>
          <div className="t-body-sm" style={{ marginTop: 4, color: "var(--text-primary)" }}>
            Investigation stopped because the requested case could not be loaded.
            Zero investigative actions were executed.
          </div>
        </div>
      )}

      {/* Case State — the shared canonical state the agent reasoned over */}
      {status?.case_snapshot && status.case_snapshot.evidence !== undefined && (
        <div style={{
          padding: "var(--space-4) var(--space-5)", marginBottom: "var(--space-5)",
          background: "var(--surface-1)", border: "1px solid var(--line)",
          borderRadius: "var(--radius-card)",
        }}>
          <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: "var(--space-3)" }}>
            CASE STATE
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(90px, 1fr))", gap: "var(--space-3)" }}>
            {([
              ["Evidence", status.case_snapshot.evidence],
              ["Events", status.case_snapshot.events],
              ["Entities", status.case_snapshot.entities],
              ["Relationships", status.case_snapshot.relationships],
              ["Observed", status.case_snapshot.observed_relationships],
              ["Inferred", status.case_snapshot.inferred_relationships],
              ["Findings", status.case_snapshot.findings],
              ["High Priority", status.case_snapshot.high_priority],
            ] as const).map(([label, value]) => (
              <div key={label}>
                <div className="t-mono-xs" style={{ color: "var(--text-muted)" }}>{label}</div>
                <div style={{ color: "var(--text-primary)", fontWeight: 600 }}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Investigation Plan */}
      {status?.investigation_plan && status.investigation_plan.length > 0 && (
        <div style={{
          padding: "var(--space-4) var(--space-5)", marginBottom: "var(--space-5)",
          background: "var(--surface-1)", border: "1px solid var(--line)",
          borderRadius: "var(--radius-card)",
        }}>
          <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: "var(--space-3)" }}>
            INVESTIGATION PLAN
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {status.investigation_plan.map((step) => {
              const done = step.status === "complete";
              const active = step.status === "in_progress";
              return (
                <div key={step.id} style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                  <span className="t-mono-xs" style={{ color: "var(--text-muted)", width: 22 }}>
                    {String(step.id).padStart(2, "0")}
                  </span>
                  <span className="t-body-sm" style={{ flex: 1, color: "var(--text-primary)" }}>
                    {step.objective}
                  </span>
                  <span className="t-mono-xs" style={{
                    color: done ? "var(--positive, #4ade80)" : active ? "var(--warning, #f59e0b)" : "var(--text-muted)",
                  }}>
                    {done ? "✓ COMPLETE" : step.status.replace(/_/g, " ").toUpperCase()}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Final investigation report */}
      {status?.final_report && (
        <div style={{
          padding: "var(--space-5)", marginBottom: "var(--space-5)",
          background: "var(--surface-1)", border: "1px solid var(--line)",
          borderRadius: "var(--radius-card)",
        }}>
          <h3 className="t-label" style={{ color: "var(--positive, #4ade80)", margin: "0 0 var(--space-4)" }}>
            INVESTIGATION COMPLETE
          </h3>

          {[
            { title: "OBSERVED", items: status.final_report.observed },
            { title: "UNRESOLVED", items: status.final_report.unresolved },
            { title: "RECOMMENDED NEXT ACTIONS", items: status.final_report.recommended_next_actions },
          ].map((section) => (
            section.items.length > 0 && (
              <div key={section.title} style={{ marginBottom: "var(--space-4)" }}>
                <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>
                  {section.title}
                </div>
                <ul style={{ margin: 0, paddingLeft: 18, color: "var(--text-secondary)", font: "var(--type-body-sm)" }}>
                  {section.items.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              </div>
            )
          ))}

          {status.final_report.analytical_findings.length > 0 && (
            <div style={{ marginBottom: "var(--space-4)" }}>
              <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>
                ANALYTICAL FINDINGS
              </div>
              <ul style={{ margin: 0, paddingLeft: 18, color: "var(--text-secondary)", font: "var(--type-body-sm)" }}>
                {status.final_report.analytical_findings.map((f, i) => (
                  <li key={i}>{f.title} — <span style={{ color: "var(--text-muted)" }}>{f.severity}</span></li>
                ))}
              </ul>
            </div>
          )}

          <div style={{
            padding: "var(--space-3)", background: "var(--surface-0)",
            borderRadius: "var(--radius-sm)", border: "1px solid var(--line)",
          }}>
            <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>GOVERNANCE</div>
            <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
              {[
                ["High-impact executed", status.final_report.governance.high_impact_actions_executed],
                ["Blocked", status.final_report.governance.blocked_actions],
                ["Pending approvals", status.final_report.governance.pending_approvals],
                ["Analytical executed", status.final_report.governance.analytical_actions_executed],
              ].map(([label, value]) => (
                <span key={label as string} className="t-mono-xs" style={{ color: "var(--text-secondary)" }}>
                  {label}: <strong>{value}</strong>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Hold Approval Panel */}
      {status?.pending_hold && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          style={{
            padding: "var(--space-5)", marginBottom: "var(--space-5)",
            background: "rgba(255, 180, 0, 0.06)", border: "2px solid rgba(255, 180, 0, 0.3)",
            borderRadius: "var(--radius-card)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: "var(--space-3)" }}>
            <span style={{ fontSize: 20 }}>⚠️</span>
            <h3 className="t-label" style={{ color: "var(--warning, #f59e0b)", margin: 0 }}>
              {status.pending_hold.governance_outcome === "blocked_by_design"
                ? "GOVERNANCE BLOCK — Human Approval Required"
                : "Human Approval Required"}
            </h3>
          </div>

          {status.pending_hold.governance_outcome === "blocked_by_design" && (
            <div className="t-body-sm" style={{ color: "var(--text-secondary)", marginBottom: "var(--space-3)" }}>
              Blocked by ArmorIQ Live Intent Assurance — the action is not in the
              agent's signed authorization scope. <strong>No system modification was
              performed.</strong> This is a governance decision, not an application failure.
            </div>
          )}

          <div style={{ marginBottom: "var(--space-4)" }}>
            <div className="t-body-sm" style={{ color: "var(--text-primary)", marginBottom: 6 }}>
              <strong>Action:</strong> {status.pending_hold.action}
            </div>
            <div className="t-body-sm" style={{ color: "var(--text-secondary)", marginBottom: 6 }}>
              {status.pending_hold.description}
            </div>
            <div className="t-body-sm" style={{ color: "var(--text-secondary)", marginBottom: 6 }}>
              <strong>AI Reasoning:</strong> {status.pending_hold.ai_reasoning}
            </div>
            <div style={{ display: "flex", gap: "var(--space-4)", marginTop: "var(--space-2)" }}>
              <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                Risk: <span style={{ color: status.pending_hold.risk_level === "high" ? "var(--critical)" : "var(--warning, #f59e0b)" }}>
                  {status.pending_hold.risk_level?.toUpperCase() || "UNKNOWN"}
                </span>
              </span>
              <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                Boundary: {status.pending_hold.authorization_boundary}
              </span>
            </div>
          </div>

          <div style={{ marginBottom: "var(--space-3)" }}>
            <input
              style={fieldStyle}
              value={holdReason}
              onChange={(e) => setHoldReason(e.target.value)}
              placeholder="Optional: reason for your decision"
            />
          </div>

          <div style={{ display: "flex", gap: "var(--space-2)" }}>
            <Button
              variant="primary"
              onClick={() => handleApprove(status.pending_hold!.hold_id)}
              disabled={decidingHold}
            >
              ✓ Approve
            </Button>
            <Button
              variant="ghost"
              onClick={() => handleReject(status.pending_hold!.hold_id)}
              disabled={decidingHold}
            >
              ✕ Reject
            </Button>
          </div>
        </motion.div>
      )}

      {/* Sub-tabs */}
      <div style={{
        display: "flex", gap: 2, marginBottom: "var(--space-4)",
        borderBottom: "1px solid var(--line)", paddingBottom: 2,
      }}>
        {(["status", "actions", "audit"] as ViewMode[]).map((mode) => (
          <button
            key={mode}
            onClick={() => handleTabSwitch(mode)}
            style={{
              padding: "8px 16px", background: "none", border: "none",
              color: viewMode === mode ? "var(--accent)" : "var(--text-muted)",
              font: "var(--type-mono-xs)", letterSpacing: "0.06em",
              cursor: "pointer", textTransform: "uppercase",
              borderBottom: viewMode === mode ? "2px solid var(--accent)" : "2px solid transparent",
            }}
          >
            {mode === "status" ? "Live Status" : mode === "actions" ? "Action Ledger" : "Audit Chain"}
          </button>
        ))}
      </div>

      {/* Status View — Action timeline */}
      {viewMode === "status" && status?.actions && status.actions.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          {status.actions.map((a: any, i: number) => {
            const badge = ACTION_BADGES[a.status] || { label: a.status, color: "var(--text-muted)" };
            return (
              <div key={a.id || i} style={{
                display: "flex", alignItems: "flex-start", gap: "var(--space-3)",
                padding: "var(--space-3) var(--space-4)",
                background: "var(--surface-1)", border: "1px solid var(--line)",
                borderRadius: "var(--radius-sm)",
              }}>
                <span style={{
                  padding: "2px 8px", borderRadius: 4, fontSize: 10,
                  fontWeight: 700, letterSpacing: "0.08em",
                  background: badge.color + "18", color: badge.color,
                  flexShrink: 0,
                }}>
                  {badge.label}
                </span>
                <div style={{ flex: 1 }}>
                  <div className="t-body-sm" style={{ color: "var(--text-primary)" }}>
                    {a.description || a.action_type}
                  </div>
                  {a.timestamp && (
                    <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginTop: 2 }}>
                      {new Date(a.timestamp).toLocaleString()}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {viewMode === "status" && (!status || status.actions.length === 0) && (
        <div style={{ textAlign: "center", padding: "var(--space-8)", color: "var(--text-muted)" }}>
          {status ? "No agent actions yet. Launch an investigation to begin." : "Click Start Investigation to launch the autonomous agent."}
        </div>
      )}

      {/* Actions View — Full ledger */}
      {viewMode === "actions" && actions && (
        <div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))", gap: "var(--space-3)", marginBottom: "var(--space-4)" }}>
            {[
              { label: "Total", value: actions.total },
              { label: "Executed", value: actions.executed, color: "var(--positive, #4ade80)" },
              { label: "Blocked", value: actions.blocked, color: "var(--critical)" },
              { label: "Approved", value: actions.approved, color: "var(--accent)" },
              { label: "Rejected", value: actions.rejected, color: "var(--critical)" },
            ].map((c) => (
              <div key={c.label} style={{
                padding: "var(--space-3)", background: "var(--surface-1)",
                borderRadius: "var(--radius-sm)", border: "1px solid var(--line)", textAlign: "center",
              }}>
                <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 2 }}>{c.label}</div>
                <div className="t-title-3" style={{ color: c.color || "var(--text-primary)" }}>{c.value}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {actions.actions.map((a, i) => {
              const badge = ACTION_BADGES[a.status] || { label: a.status, color: "var(--text-muted)" };
              return (
                <div key={a.id || i} style={{
                  display: "flex", alignItems: "center", gap: "var(--space-3)",
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--surface-1)", border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                }}>
                  <span style={{
                    padding: "2px 8px", borderRadius: 4, fontSize: 10,
                    fontWeight: 700, background: badge.color + "18", color: badge.color,
                  }}>{badge.label}</span>
                  <span className="t-body-sm" style={{ color: "var(--text-primary)", flex: 1 }}>
                    {a.description}
                  </span>
                  <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                    {a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Audit Trail */}
      {viewMode === "audit" && auditTrail && (
        <div>
          <div style={{
            padding: "var(--space-4)", background: "var(--surface-1)",
            border: "1px solid var(--line)", borderRadius: "var(--radius-card)",
            marginBottom: "var(--space-4)",
          }}>
            <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>
              SHA-256 CHAIN · {auditTrail.sha256_chain_entries.length} entries
            </div>
            <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
              {[
                { label: "Executed", value: auditTrail.totals.executed },
                { label: "Blocked", value: auditTrail.totals.blocked },
                { label: "Approved", value: auditTrail.totals.approved },
                { label: "Rejected", value: auditTrail.totals.rejected },
              ].map((t) => (
                <span key={t.label} className="t-mono-xs" style={{ color: "var(--text-secondary)" }}>
                  {t.label}: <strong>{t.value}</strong>
                </span>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {auditTrail.sha256_chain_entries.map((e) => (
              <div key={e.id} style={{
                padding: "var(--space-3) var(--space-4)",
                background: "var(--surface-1)", border: "1px solid var(--line)",
                borderRadius: "var(--radius-sm)",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                  <span className="t-mono-xs" style={{ color: "var(--accent)" }}>#{e.id}</span>
                  <span className="t-body-sm" style={{ color: "var(--text-primary)", flex: 1 }}>{e.action}</span>
                  <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                    {e.timestamp ? new Date(e.timestamp).toLocaleString() : ""}
                  </span>
                </div>
                <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginTop: 4, wordBreak: "break-all" }}>
                  🔗 {e.entry_hash.slice(0, 16)}…{e.entry_hash.slice(-8)}
                  <span style={{ color: "var(--line-strong)", margin: "0 6px" }}>←</span>
                  {e.prev_hash.slice(0, 16)}…
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div style={{
          padding: "var(--space-3) var(--space-4)", marginTop: "var(--space-4)",
          background: "var(--critical-tint)", border: "1px solid rgba(255,92,92,0.3)",
          borderRadius: "var(--radius-sm)", color: "var(--critical)", font: "var(--type-body-sm)",
        }}>
          {error}
        </div>
      )}

      {/* Pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
