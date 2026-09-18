/**
 * CyberDrishti AI — Correlations / Hidden Links Panel
 * Run correlation analysis, view scored entity pairs, verify/dispute findings.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import {
  intelApi,
  type CorrelationItem,
  type CorrelationsListResponse,
  type CorrelationsRunResponse,
} from "../../../api/intelligence";
import { Button } from "../../../components/primitives/Button";

const SCORE_FEATURES: Array<{ key: string; label: string; isCount?: boolean }> = [
  { key: "jaccard", label: "jaccard" },
  { key: "adamic_adar_norm", label: "adamic-adar" },
  { key: "temporal_norm", label: "temporal" },
  { key: "fin_score", label: "financial" },
  { key: "bridge_score", label: "bridge" },
  { key: "common_neighbors", label: "common nbrs", isCount: true },
];

function ScoreBar({ score, max = 1 }: { score: number; max?: number }) {
  const pct = Math.max(2, Math.min(100, (score / max) * 100));
  const color = score >= 0.7 ? "var(--critical)" : score >= 0.4 ? "var(--accent)" : "var(--line-strong)";
  return (
    <div style={{ width: 60, height: 6, background: "var(--surface-1)", borderRadius: 3, overflow: "hidden" }}>
      <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 3, transition: "width 0.3s" }} />
    </div>
  );
}

export function CorrelationsPanel({ caseId }: { caseId: string }) {
  const [correlations, setCorrelations] = useState<CorrelationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<{ entity_count: number; flagged: number } | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadCorrelations = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await intelApi.correlations(caseId);
      setCorrelations(res.correlations || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load correlations");
    } finally {
      setLoading(false);
    }
  };

  const runAnalysis = async () => {
    setRunning(true);
    setError(null);
    try {
      const res = await intelApi.runCorrelations(caseId);
      // The run endpoint returns aggregate counts only; the flagged list is
      // fetched separately from GET /correlations/{caseId}.
      setRunResult({ entity_count: res.entity_count, flagged: res.flagged });
      await loadCorrelations();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Correlation analysis failed");
    } finally {
      setRunning(false);
    }
  };

  const handleVerify = async (id: string, verdict: "confirmed" | "disputed") => {
    setVerifyingId(id);
    try {
      await intelApi.verifyCorrelation(id, verdict);
      // Disputed links become decision='not_flagged' server-side and drop out
      // of the flagged list — reload to reflect the real post-review state.
      await loadCorrelations();
    } catch (err: unknown) {
      setError(`Failed to ${verdict} correlation`);
    } finally {
      setVerifyingId(null);
    }
  };

  return (
    <div style={{
      background: "var(--surface-0)", border: "1px solid var(--line)",
      borderRadius: "var(--radius-card)", padding: "var(--space-5)",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-4)" }}>
        <div>
          <h3 className="t-label" style={{ color: "var(--text-primary)", marginBottom: 4 }}>
            🔗 Hidden Link Analysis
          </h3>
          <p className="t-body-sm" style={{ color: "var(--text-muted)", margin: 0 }}>
            Rule-based weighted scoring: Jaccard · Adamic-Adar · temporal · financial · bridge · common neighbours
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button variant="ghost" onClick={loadCorrelations} disabled={loading}>
            {loading ? "Loading…" : "Load"}
          </Button>
          <Button variant="primary" onClick={runAnalysis} disabled={running}>
            {running ? "Analyzing…" : "Run Analysis"}
          </Button>
        </div>
      </div>

      {runResult && (
        <div style={{
          padding: "var(--space-3) var(--space-4)", marginBottom: "var(--space-4)",
          background: "rgba(99, 102, 241, 0.06)", border: "1px solid rgba(99, 102, 241, 0.2)",
          borderRadius: "var(--radius-sm)", font: "var(--type-mono-xs)", color: "var(--accent)",
        }}>
          Evaluated {runResult.entity_count} entity pairs → flagged {runResult.flagged} correlations
        </div>
      )}

      {error && (
        <div style={{
          padding: "var(--space-3) var(--space-4)", marginBottom: "var(--space-4)",
          background: "var(--critical-tint)", border: "1px solid rgba(255,92,92,0.3)",
          borderRadius: "var(--radius-sm)", color: "var(--critical)", font: "var(--type-body-sm)",
        }}>
          {error}
        </div>
      )}

      {correlations.length === 0 && !loading && !running && (
        <div style={{ textAlign: "center", padding: "var(--space-8)", color: "var(--text-muted)", font: "var(--type-body-sm)" }}>
          No correlations found. Click <strong>Run Analysis</strong> to detect hidden links in this case.
        </div>
      )}

      {correlations.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          {correlations.map((c) => {
            const isExpanded = expandedId === c.id;
            return (
              <motion.div
                key={c.id}
                layout
                style={{
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--surface-1)", border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)", cursor: "pointer",
                  borderLeft: c.verified_by ? "3px solid var(--positive, #4ade80)" : "3px solid var(--accent)",
                }}
                onClick={() => setExpandedId(isExpanded ? null : c.id)}
              >
                {/* Header Row */}
                <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                  <div style={{ flex: 1 }}>
                    <div className="t-body-sm" style={{ color: "var(--text-primary)" }}>
                      <span style={{ fontFamily: "var(--font-mono)" }}>{c.entity_a.value}</span>
                      <span style={{ color: "var(--text-muted)", margin: "0 8px" }}>↔</span>
                      <span style={{ fontFamily: "var(--font-mono)" }}>{c.entity_b.value}</span>
                    </div>
                    <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                      <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>{c.entity_a.type}</span>
                      <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>{c.entity_b.type}</span>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                    <ScoreBar score={c.final_score} />
                    <span className="t-mono-xs" style={{ color: "var(--accent)", minWidth: 36, textAlign: "right" }}>
                      {(c.final_score * 100).toFixed(0)}%
                    </span>
                    {c.verified_by && <span title="Human-verified" style={{ fontSize: 14 }}>✅</span>}
                  </div>
                </div>

                {/* Expanded Detail */}
                {isExpanded && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    style={{ marginTop: "var(--space-3)", paddingTop: "var(--space-3)", borderTop: "1px solid var(--line-faint)" }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginBottom: "var(--space-3)" }}>
                    {c.source_citations?.length
                      ? `${c.source_citations.length} co-occurrence citation(s) in evidence support this link.`
                      : "Rule-based hidden-link score from entity co-occurrence, temporal, and financial features."}
                  </p>

                    {/* Feature Score Breakdown */}
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-2)", marginBottom: "var(--space-3)" }}>
                      {SCORE_FEATURES.map((feat) => {
                        const val = c.component_scores?.[feat.key] ?? 0;
                        return (
                          <div key={feat.key} style={{
                            display: "flex", alignItems: "center", gap: 6,
                            padding: "4px 8px", background: "var(--surface-0)", borderRadius: 4,
                          }}>
                            <span className="t-mono-xs" style={{ color: "var(--text-muted)", minWidth: 60 }}>
                              {feat.label}
                            </span>
                            {feat.isCount ? (
                              <span className="t-mono-xs" style={{ color: "var(--text-secondary)", flex: 1, textAlign: "right" }}>
                                {Math.round(val)} shared
                              </span>
                            ) : (
                              <>
                                <ScoreBar score={val} />
                                <span className="t-mono-xs" style={{ color: "var(--text-secondary)" }}>
                                  {val.toFixed(2)}
                                </span>
                              </>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {/* Verify/Dispute Buttons */}
                    {!c.verified_by && (
                      <div style={{ display: "flex", gap: "var(--space-2)" }}>
                        <Button
                          variant="primary"
                          onClick={() => handleVerify(c.id, "confirmed")}
                          disabled={verifyingId === c.id}
                        >
                          ✓ Confirm Link
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => handleVerify(c.id, "disputed")}
                          disabled={verifyingId === c.id}
                        >
                          ✕ Dispute
                        </Button>
                      </div>
                    )}

                    {c.verified_by && (
                      <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginTop: 6 }}>
                        Reviewed by {c.verified_by} · {c.verified_at ? new Date(c.verified_at).toLocaleString() : ""}
                      </div>
                    )}
                  </motion.div>
                )}
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}
