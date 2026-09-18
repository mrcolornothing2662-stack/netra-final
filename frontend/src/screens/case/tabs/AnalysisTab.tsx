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

      {/* ── OPTIONAL AI NARRATIVE ───────────────────────────────────── */}
      <div className="t-label" style={{ marginBottom: "var(--space-3)", marginTop: "var(--space-6)" }}>
        AI Narrative <span style={{ color: "var(--text-muted)" }}>· optional</span>
      </div>
      {aiOnline === false ? (
        <div style={{ marginBottom: "var(--space-10)", padding: "var(--space-4) var(--space-5)", background: "var(--surface-1)", border: "1px dashed var(--line-strong)", borderRadius: "var(--radius-card)" }}>
          <div style={{ font: "var(--type-mono-xs)", letterSpacing: "0.08em", color: "var(--warning)" }}>
            AI NARRATIVE UNAVAILABLE
          </div>
          <div style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", marginTop: 4, lineHeight: 1.6 }}>
            The language-model provider is unavailable. No AI-generated narrative is shown.
            <strong> Deterministic analysis and findings above are unaffected.</strong>
          </div>
        </div>
      ) : (
      <div style={{ marginBottom: "var(--space-10)", padding: "var(--space-6)", background: "var(--surface-1)", border: "1px solid var(--line)", borderRadius: "var(--radius-card)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "var(--space-2)" }}>
          <Icon name="command" size={16} />
          <span className="t-label">AI Daya Forensic Copilot · Statutory Citation Engine</span>
        </div>
        <p className="t-body-sm measure" style={{ color: "var(--text-secondary)", marginBottom: "var(--space-4)" }}>
          Query evidence, identify money trails, and cross-reference statutory Indian legal sections (BSA / BNS).
        </p>

        <form onSubmit={handleAsk} style={{ display: "flex", gap: "var(--space-3)" }}>
          <input
            style={{
              flex: 1, height: 40, padding: "0 var(--space-4)",
              background: "var(--surface-2)", border: "1px solid var(--line)",
              borderRadius: "var(--radius-input)", color: "var(--text-primary)",
              font: "var(--type-body-sm)", outline: "none",
            }}
            placeholder="e.g. What are the suspect UPI IDs and phone numbers involved in this case?"
            value={question}
            onChange={e => setQuestion(e.target.value)}
          />
          <Button variant="primary" type="submit" disabled={asking || aiOnline === null}>
            {asking ? "Synthesizing…" : aiOnline === null ? "Checking…" : "Ask Copilot"}
          </Button>
        </form>

        {copilotError && (
          <div style={{ marginTop: "var(--space-3)", color: "var(--critical)", font: "var(--type-mono-xs)" }}>
            {copilotError}
          </div>
        )}

        {copilotResult && (
          <div style={{ marginTop: "var(--space-6)", paddingTop: "var(--space-4)", borderTop: "1px solid var(--line)" }}>
            <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: "var(--space-3)" }}>
              Analysis Output ({copilotResult.model_used})
            </div>
            <div style={{ font: "var(--type-body)", color: "var(--text-primary)", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
              {copilotResult.answer}
            </div>

            {copilotResult.citations && copilotResult.citations.length > 0 && (
              <div style={{ marginTop: "var(--space-6)" }}>
                <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>Verified Evidence Citations</div>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {copilotResult.citations.map((c, i) => (
                    <div key={i} style={{ padding: "8px 12px", background: "var(--surface-2)", border: "1px solid var(--line)", borderRadius: "var(--radius-input)", font: "var(--type-body-sm)" }}>
                      <span className="t-mono-xs" style={{ color: "var(--verified)", marginRight: "8px" }}>✓ [{c.file} · Line {c.line}]</span>
                      <span style={{ color: "var(--text-secondary)" }}>"{c.text}"</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── Output Verifier HUD (Feature 09) ─────────────── */}
            {(copilotResult as any).verification && (
              <div style={{
                marginTop: "var(--space-4)",
                padding: "var(--space-4) var(--space-5)",
                borderRadius: "var(--radius-input)",
                border: `1px solid ${(copilotResult as any).verification.passed ? "rgba(80, 200, 120, 0.3)" : "rgba(255, 92, 92, 0.3)"}`,
                background: (copilotResult as any).verification.passed ? "rgba(80, 200, 120, 0.04)" : "rgba(255, 92, 92, 0.04)",
              }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: "8px",
                  font: "var(--type-mono-xs)", letterSpacing: "0.06em",
                  textTransform: "uppercase" as const, marginBottom: "var(--space-2)",
                  color: (copilotResult as any).verification.passed ? "var(--verified)" : "var(--critical)",
                }}>
                  <span>{(copilotResult as any).verification.passed ? "🛡️ ✅" : "🛡️ ⚠️"}</span>
                  SEMANTIC VERIFIER · {(copilotResult as any).verification.passed ? "All checks passed" : `${(copilotResult as any).verification.flags?.length || 0} issue(s)`}
                </div>
                {(copilotResult as any).verification.flags?.map((f: { severity: string; message: string; check: string }, i: number) => (
                  <div key={i} style={{ display: "flex", gap: "var(--space-3)", padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                    <span style={{
                      padding: "2px 6px", borderRadius: "4px", font: "var(--type-mono-xs)", letterSpacing: "0.04em",
                      textTransform: "uppercase" as const, minWidth: "60px", textAlign: "center" as const,
                      background: f.severity === "error" ? "rgba(255,92,92,0.12)" : f.severity === "warning" ? "rgba(255,193,7,0.12)" : "rgba(88,166,255,0.12)",
                      color: f.severity === "error" ? "var(--critical)" : f.severity === "warning" ? "var(--warning)" : "var(--intel)",
                    }}>
                      {f.severity}
                    </span>
                    <span style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", flex: 1 }}>{f.message}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      )}

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
