import { useState, useEffect } from "react";
import { FindingBlock } from "../../../components/data/FindingBlock";
import { findingsForCase } from "../../../data/corpus";
import { useLiveStore } from "../../../state/useLiveStore";
import { adaptFinding } from "../../../adapters/findingAdapter";
import { copilotApi, type CopilotResponse } from "../../../api/copilot";
import { Button } from "../../../components/primitives/Button";
import { Icon } from "../../../components/icons";
import { CommIntelPanel } from "./CommIntelPanel";
import { FinanceIntelPanel } from "./FinanceIntelPanel";
import s from "../../../components/case/case.module.css";

export function AnalysisTab({ caseId, onOpenEvidence }: { caseId: string; onOpenEvidence: () => void }) {
  const { activeCaseSummary } = useLiveStore();
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [copilotResult, setCopilotResult] = useState<CopilotResponse | null>(null);
  const [copilotError, setCopilotError] = useState<string | null>(null);
  // AI availability is probed honestly from /copilot/status — null = unknown/checking.
  const [aiOnline, setAiOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    copilotApi.status()
      .then(st => { if (!cancelled) setAiOnline(!!st.ollama_online); })
      .catch(() => { if (!cancelled) setAiOnline(false); });
    return () => { cancelled = true; };
  }, []);

  const isDemo = caseId === "CYB-2026-042" || caseId === "demo-shadowlink";
  const rawFindings = activeCaseSummary?.findings;
  const fnds = (rawFindings && rawFindings.length > 0)
    ? rawFindings.map((f, i) => adaptFinding(f, i))
    : (isDemo ? findingsForCase(caseId) : []);

  // Deterministic case state. We never render zeros when the summary failed to
  // load — that would falsely imply an empty case.
  const counts = activeCaseSummary?.counts;
  const summaryUnavailable = !activeCaseSummary;

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setCopilotError(null);

    try {
      const res = await copilotApi.ask(caseId, question.trim());
      setCopilotResult(res);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 403) setCopilotError("Access denied for this case.");
      else if (status === 404) setCopilotError("Case or copilot endpoint not found.");
      else if (typeof status === "number" && status >= 500) setCopilotError("AI narrative service could not complete the request.");
      else setCopilotError("AI narrative unavailable. Deterministic findings above are unaffected.");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div>
      <p className={`t-body-lg measure ${s.analysisLede}`}>
        Autonomous analysis identifying cross-channel patterns, timing signatures, and anomaly clusters for this investigation.
      </p>

      {/* ── DETERMINISTIC CASE ANALYSIS ─────────────────────────────── */}
      <div style={{ marginBottom: "var(--space-8)", padding: "var(--space-5)", background: "var(--surface-1)", border: "1px solid var(--line)", borderRadius: "var(--radius-card)" }}>
        <div className="t-label" style={{ marginBottom: "var(--space-3)" }}>Case Analysis</div>
        {summaryUnavailable ? (
          <div style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)" }}>
            <strong style={{ color: "var(--critical)" }}>CASE ANALYSIS UNAVAILABLE</strong>
            <div style={{ marginTop: 4 }}>
              The case summary could not be loaded. Counts are not shown because they would
              falsely imply an empty case.
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: "var(--space-4)" }}>
            <AnalysisMetric label="Evidence" value={counts!.evidence} />
            <AnalysisMetric label="Events" value={counts!.events} />
            <AnalysisMetric label="Entities" value={counts!.entities} />
            <AnalysisMetric label="Relationships" value={counts!.connections} />
            <AnalysisMetric label="Findings" value={counts!.suspicious_findings} />
          </div>
        )}
      </div>

      {/* ── KEY FINDINGS (deterministic) ────────────────────────────── */}
      <div className="t-label" style={{ marginBottom: "var(--space-4)" }}>
        Key Findings ({fnds.length})
      </div>
      {fnds.length === 0 ? (
        <div style={{
          padding: "var(--space-10) var(--space-6)", textAlign: "center",
          background: "var(--surface-1)", border: "1px dashed var(--line-strong)",
          borderRadius: "var(--radius-card)"
        }}>
          <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "var(--space-2)" }}>
            Correlation Engine
          </div>
          <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
            No Findings Yet
          </h3>
          <p className="measure" style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", margin: "0 auto var(--space-6) auto" }}>
            Findings appear automatically once evidence is ingested and the cognitive
            analysis runs. They are derived deterministically — not from the language model.
          </p>
          <Button variant="primary" icon="plus" onClick={onOpenEvidence}>
            Ingest Evidence
          </Button>
        </div>
      ) : (
        fnds.map(f => (
          <div key={f.id} style={{ marginBottom: "var(--space-8)" }}>
            <FindingBlock finding={f} onOpenEvidence={onOpenEvidence} />
          </div>
        ))
      )}

      {/* ── NETRA FORENSIC COPILOT ───────────────────────────────────── */}
      <div style={{ marginBottom: "var(--space-10)", padding: "var(--space-6)", background: "var(--surface-1)", border: "1px solid var(--line)", borderRadius: "var(--radius-card)" }}>
        {/* Header with Title and Ready Status */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "var(--space-4)", flexWrap: "wrap", gap: "12px" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <h2 style={{ font: "var(--type-title-2)", fontWeight: 700, letterSpacing: "0.04em", margin: 0, color: "var(--text-primary)" }}>
                NETRA COPILOT
              </h2>
              <span style={{
                display: "inline-flex", alignItems: "center", gap: "6px",
                padding: "3px 10px", borderRadius: "12px",
                background: "rgba(80, 200, 120, 0.12)", border: "1px solid rgba(80, 200, 120, 0.3)",
                color: "var(--verified)", font: "var(--type-mono-xs)", fontWeight: 600, letterSpacing: "0.06em",
              }}>
                <span style={{ fontSize: "10px" }}>●</span> READY
              </span>
            </div>
            <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginTop: "4px" }}>
              Evidence-Grounded Investigation Assistant
            </div>
          </div>

          {/* Active Case Badge */}
          <div style={{
            padding: "8px 14px", background: "var(--surface-2)",
            border: "1px solid var(--line)", borderRadius: "var(--radius-input)",
            textAlign: "right",
          }}>
            <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", letterSpacing: "0.05em", textTransform: "uppercase" }}>
              Active Case
            </div>
            <div style={{ font: "var(--type-body-sm)", fontWeight: 600, color: "var(--text-primary)" }}>
              {activeCaseSummary?.title || "Operation Meridian"}
            </div>
            <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)" }}>
              {activeCaseSummary?.case_number || "CYB-2026-05EBE42"}
            </div>
          </div>
        </div>

        {/* Query Input */}
        <form onSubmit={handleAsk} style={{ display: "flex", gap: "var(--space-3)", marginBottom: "var(--space-3)" }}>
          <input
            style={{
              flex: 1, height: 44, padding: "0 var(--space-4)",
              background: "var(--surface-2)", border: "1px solid var(--line)",
              borderRadius: "var(--radius-input)", color: "var(--text-primary)",
              font: "var(--type-body-sm)", outline: "none",
            }}
            placeholder="Ask an investigative question..."
            value={question}
            onChange={e => setQuestion(e.target.value)}
          />
          <Button variant="primary" type="submit" disabled={asking}>
            {asking ? "ANALYZING..." : "ASK NETRA"}
          </Button>
        </form>

        {/* Demo Preset Question Chips */}
        <div style={{ marginBottom: "var(--space-4)" }}>
          <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginBottom: "6px", letterSpacing: "0.05em" }}>
            DEMO INVESTIGATIVE QUESTIONS:
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
            {[
              "What amount was transferred through ACC-001?",
              "What relationships connect ACC-001 to the available phone numbers?",
              "What happened between August 20 and August 25?",
            ].map((q, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setQuestion(q)}
                style={{
                  background: "var(--surface-2)",
                  border: "1px solid var(--line)",
                  borderRadius: "16px",
                  padding: "5px 12px",
                  color: "var(--text-secondary)",
                  font: "var(--type-body-sm)",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "all 0.15s ease",
                }}
              >
                • {q}
              </button>
            ))}
          </div>
        </div>

        {/* Loading State */}
        {asking && (
          <div style={{
            marginTop: "var(--space-4)", padding: "var(--space-5)",
            background: "rgba(56, 139, 253, 0.05)", border: "1px solid rgba(56, 139, 253, 0.2)",
            borderRadius: "var(--radius-card)",
          }}>
            <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", fontWeight: 700, letterSpacing: "0.08em", marginBottom: "8px" }}>
              ANALYZING CASE EVIDENCE...
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "4px", font: "var(--type-body-sm)", color: "var(--text-secondary)" }}>
              <div>▸ Retrieving graph relationships...</div>
              <div>▸ Checking structured records...</div>
              <div>▸ Verifying sources...</div>
            </div>
          </div>
        )}

        {copilotError && (
          <div style={{ marginTop: "var(--space-3)", color: "var(--critical)", font: "var(--type-mono-xs)" }}>
            {copilotError}
          </div>
        )}

        {/* Response Presentation Card */}
        {copilotResult && !asking && (
          <div style={{ marginTop: "var(--space-6)", paddingTop: "var(--space-5)", borderTop: "1px solid var(--line)" }}>
            {/* Status Header & Legal Governance Strip */}
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              marginBottom: "var(--space-4)", paddingBottom: "var(--space-3)",
              borderBottom: "1px solid rgba(255,255,255,0.06)", flexWrap: "wrap", gap: "8px",
            }}>
              <div style={{ display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
                {/* Generation Provider Badge */}
                {copilotResult.fallback_used || copilotResult.provider === "offline" ? (
                  <span style={{
                    padding: "3px 10px", borderRadius: "4px", font: "var(--type-mono-xs)",
                    background: "rgba(234, 179, 8, 0.15)", color: "#eab308", fontWeight: 700,
                    border: "1px solid rgba(234, 179, 8, 0.3)", display: "inline-flex", alignItems: "center", gap: "6px"
                  }}>
                    <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#eab308" }} />
                    GENERATION: NETRA Offline Fallback
                  </span>
                ) : copilotResult.provider === "ollama" ? (
                  <span style={{
                    padding: "3px 10px", borderRadius: "4px", font: "var(--type-mono-xs)",
                    background: "rgba(34, 197, 94, 0.15)", color: "#22c55e", fontWeight: 700,
                    border: "1px solid rgba(34, 197, 94, 0.3)", display: "inline-flex", alignItems: "center", gap: "6px"
                  }}>
                    <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#22c55e" }} />
                    GENERATION: Ollama — {copilotResult.model_used}
                  </span>
                ) : (
                  <span style={{
                    padding: "3px 10px", borderRadius: "4px", font: "var(--type-mono-xs)",
                    background: "rgba(56, 139, 253, 0.15)", color: "#388bfd", fontWeight: 700,
                    border: "1px solid rgba(56, 139, 253, 0.3)", display: "inline-flex", alignItems: "center", gap: "6px"
                  }}>
                    <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#388bfd" }} />
                    GENERATION: {copilotResult.provider} — {copilotResult.model_used}
                  </span>
                )}

                {/* Grounding Badge */}
                <span style={{
                  padding: "3px 8px", borderRadius: "4px", font: "var(--type-mono-xs)",
                  background: "rgba(80, 200, 120, 0.12)", color: "var(--verified)", fontWeight: 600,
                }}>
                  Grounding: {Math.round((copilotResult.grounded_claim_ratio ?? copilotResult.grounded_ratio ?? 1.0) * 100)}%
                </span>

                {/* Sources Count Badge */}
                <span style={{
                  padding: "3px 8px", borderRadius: "4px", font: "var(--type-mono-xs)",
                  background: "rgba(56, 139, 253, 0.12)", color: "var(--intel)", fontWeight: 600,
                }}>
                  Sources: {copilotResult.citation_count ?? copilotResult.citations?.length ?? 0}
                </span>

                {/* Latency Badge */}
                {(copilotResult.latency_ms || copilotResult.stage_latencies?.total_ms) && (
                  <span style={{
                    padding: "3px 8px", borderRadius: "4px", font: "var(--type-mono-xs)",
                    background: "rgba(255, 255, 255, 0.06)", color: "var(--text-muted)", fontWeight: 600,
                  }}>
                    Latency: {Math.round(copilotResult.stage_latencies?.total_ms ?? copilotResult.latency_ms ?? 0)}ms
                  </span>
                )}
              </div>
              <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                Model: {copilotResult.model_used}
              </div>
            </div>

            {/* 1. ANSWER Section */}
            <div style={{ marginBottom: "var(--space-6)" }}>
              <div style={{ font: "var(--type-mono-xs)", letterSpacing: "0.08em", color: "var(--intel)", textTransform: "uppercase", marginBottom: "8px", fontWeight: 700 }}>
                ANSWER
              </div>
              <div style={{
                font: "var(--type-body)", color: "var(--text-primary)", whiteSpace: "pre-wrap",
                lineHeight: 1.6, padding: "var(--space-4)", background: "var(--surface-2)",
                borderRadius: "var(--radius-input)", border: "1px solid var(--line)",
              }}>
                {copilotResult.answer}
              </div>
            </div>

            {/* 2. EVIDENCE Section */}
            {copilotResult.citations && copilotResult.citations.length > 0 && (
              <div style={{ marginBottom: "var(--space-6)" }}>
                <div style={{ font: "var(--type-mono-xs)", letterSpacing: "0.08em", color: "var(--verified)", textTransform: "uppercase", marginBottom: "8px", fontWeight: 700 }}>
                  EVIDENCE
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "10px" }}>
                  {copilotResult.citations.slice(0, 6).map((c, i) => (
                    <div key={i} style={{
                      padding: "10px 12px", background: "var(--surface-2)",
                      border: "1px solid var(--line)", borderRadius: "var(--radius-input)",
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                        <span style={{ font: "var(--type-mono-xs)", fontWeight: 700, color: "var(--verified)" }}>
                          {c.file}
                        </span>
                        {c.page && c.page !== "N/A" && (
                          <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                            p. {c.page}
                          </span>
                        )}
                      </div>
                      <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", fontSize: "12px", lineHeight: 1.4 }}>
                        {c.text.length > 130 ? `${c.text.slice(0, 130)}…` : c.text}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 3. ANALYTICAL INFERENCE & EPISTEMIC STATUS (Observed vs Inferred) */}
            <div style={{ marginBottom: "var(--space-6)" }}>
              <div style={{ font: "var(--type-mono-xs)", letterSpacing: "0.08em", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: "8px", fontWeight: 700 }}>
                ANALYTICAL INFERENCE
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                {/* OBSERVED COLUMN */}
                <div style={{
                  padding: "12px 14px", background: "rgba(80, 200, 120, 0.04)",
                  border: "1px solid rgba(80, 200, 120, 0.2)", borderRadius: "var(--radius-input)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
                    <span style={{ color: "var(--verified)", fontSize: "12px" }}>●</span>
                    <span style={{ font: "var(--type-mono-xs)", fontWeight: 700, color: "var(--verified)", letterSpacing: "0.06em" }}>
                      OBSERVED
                    </span>
                  </div>
                  <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", fontSize: "12px", marginBottom: "6px" }}>
                    Directly supported by case evidence.
                  </div>
                  {copilotResult.observed_facts && copilotResult.observed_facts.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                      {copilotResult.observed_facts.slice(0, 4).map((f, i) => (
                        <div key={i} style={{ font: "var(--type-mono-xs)", color: "var(--text-primary)", fontSize: "11px" }}>
                          ✓ {f}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", fontSize: "11px" }}>
                      No direct graph relations observed.
                    </div>
                  )}
                </div>

                {/* INFERRED COLUMN */}
                <div style={{
                  padding: "12px 14px", background: "rgba(56, 139, 253, 0.04)",
                  border: "1px solid rgba(56, 139, 253, 0.2)", borderRadius: "var(--radius-input)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "6px", marginBottom: "6px" }}>
                    <span style={{ color: "var(--intel)", fontSize: "12px" }}>◌</span>
                    <span style={{ font: "var(--type-mono-xs)", fontWeight: 700, color: "var(--intel)", letterSpacing: "0.06em" }}>
                      INFERRED
                    </span>
                  </div>
                  <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", fontSize: "12px", marginBottom: "6px" }}>
                    Analytical relationship derived from available evidence.
                  </div>
                  {copilotResult.inferred_facts && copilotResult.inferred_facts.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                      {copilotResult.inferred_facts.slice(0, 4).map((f, i) => (
                        <div key={i} style={{ font: "var(--type-mono-xs)", color: "var(--text-primary)", fontSize: "11px" }}>
                          ◌ {f}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", fontSize: "11px" }}>
                      No multi-hop inference required for this factual query.
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 4. SOURCES Section with Open Evidence Action */}
            {copilotResult.citations && copilotResult.citations.length > 0 && (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <div style={{ font: "var(--type-mono-xs)", letterSpacing: "0.08em", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: 700 }}>
                    SOURCES
                  </div>
                  <Button variant="ghost" onClick={onOpenEvidence}>
                    View All Seized Evidence →
                  </Button>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "8px" }}>
                  {Array.from(new Set(copilotResult.citations.map(c => c.file))).map((file, i) => (
                    <div key={i} style={{
                      padding: "4px 10px", background: "var(--surface-2)",
                      border: "1px solid var(--line)", borderRadius: "4px",
                      font: "var(--type-mono-xs)", color: "var(--text-secondary)",
                      display: "flex", alignItems: "center", gap: "6px",
                    }}>
                      <span>📄</span> {file}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Deep Intelligence Panels ─────────────────────────────────── */}
      <CommIntelPanel caseId={caseId} />
      <FinanceIntelPanel caseId={caseId} />
    </div>
  );
}

function AnalysisMetric({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div>
      <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ font: "var(--type-title-2)", color: color || "var(--text-primary)" }}>{value}</div>
    </div>
  );
}
