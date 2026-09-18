/**
 * CyberDrishti AI — Communication Intelligence Deep Panel
 * CDR call pair analysis, burst detection, WhatsApp sender stats, hourly heatmap.
 */
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { intelApi, type CommIntelResponse } from "../../../api/intelligence";
import { Button } from "../../../components/primitives/Button";
import s from "../../../components/case/case.module.css";

export function CommIntelPanel({ caseId }: { caseId: string }) {
  const [data, setData] = useState<CommIntelResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await intelApi.communicationIntel(caseId);
      setData(res);
      setExpanded(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load communication intelligence");
    } finally {
      setLoading(false);
    }
  };

  const fmtDuration = (sec: number) => {
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  };

  const inr = (n: number) => "₹" + n.toLocaleString("en-IN");

  return (
    <div style={{ marginBottom: "var(--space-8)" }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "var(--space-4) var(--space-5)",
        background: "var(--surface-1)", border: "1px solid var(--line)",
        borderRadius: expanded ? "var(--radius-card) var(--radius-card) 0 0" : "var(--radius-card)",
        cursor: "pointer",
      }} onClick={() => data ? setExpanded(!expanded) : load()}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 20 }}>📡</span>
          <div>
            <div className="t-label" style={{ color: "var(--text-primary)" }}>Communication Intelligence</div>
            <div className="t-body-sm" style={{ color: "var(--text-muted)" }}>
              CDR call pairs · burst detection · WhatsApp analysis
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {data && (
            <span className="t-mono-xs" style={{ color: "var(--accent)" }}>
              {data.total_calls} calls · {data.total_whatsapp_messages} msgs
            </span>
          )}
          <Button variant="ghost" onClick={(e) => { e.stopPropagation(); load(); }} disabled={loading}>
            {loading ? "Loading…" : data ? "Refresh" : "Analyze"}
          </Button>
        </div>
      </div>

      {expanded && data && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          style={{
            background: "var(--surface-0)", border: "1px solid var(--line)", borderTop: "none",
            borderRadius: "0 0 var(--radius-card) var(--radius-card)",
            padding: "var(--space-5)",
          }}
        >
          {/* Summary Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "var(--space-3)", marginBottom: "var(--space-6)" }}>
            {[
              { label: "Call Pairs", value: data.call_pair_count },
              { label: "Total Calls", value: data.total_calls },
              { label: "WhatsApp Messages", value: data.total_whatsapp_messages },
              { label: "Burst Windows", value: data.communication_bursts.length },
            ].map((card) => (
              <div key={card.label} style={{
                padding: "var(--space-4)", background: "var(--surface-1)", borderRadius: "var(--radius-sm)",
                border: "1px solid var(--line)", textAlign: "center",
              }}>
                <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>{card.label}</div>
                <div className="t-title-3" style={{ color: "var(--accent)" }}>{card.value}</div>
              </div>
            ))}
          </div>

          {/* Bursts */}
          {data.communication_bursts.length > 0 && (
            <div style={{ marginBottom: "var(--space-6)" }}>
              <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                🔴 Communication Bursts
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                {data.communication_bursts.map((b, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "center", gap: "var(--space-3)",
                    padding: "var(--space-3) var(--space-4)",
                    background: "rgba(255, 92, 92, 0.06)", border: "1px solid rgba(255, 92, 92, 0.2)",
                    borderRadius: "var(--radius-sm)",
                  }}>
                    <span style={{ color: "var(--critical)", font: "var(--type-mono-xs)" }}>BURST</span>
                    <span className="t-body-sm" style={{ color: "var(--text-secondary)" }}>
                      {b.call_count} calls in {b.duration_minutes}min — {new Date(b.start).toLocaleTimeString()} → {new Date(b.end).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Call Pairs Table */}
          {data.call_pairs.length > 0 && (
            <div style={{ marginBottom: "var(--space-6)" }}>
              <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                Call Pairs (by frequency)
              </h4>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", font: "var(--type-body-sm)" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--line)" }}>
                      {["Caller", "Callee", "Calls", "Duration", "First", "Last"].map((h) => (
                        <th key={h} style={{ padding: "8px 12px", textAlign: "left", color: "var(--text-muted)", font: "var(--type-mono-xs)", letterSpacing: "0.05em" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {data.call_pairs.slice(0, 20).map((cp, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid var(--line-faint)" }}>
                        <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{cp.caller}</td>
                        <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", color: "var(--text-primary)" }}>{cp.callee}</td>
                        <td style={{ padding: "8px 12px", color: "var(--accent)", fontWeight: 600 }}>{cp.call_count}</td>
                        <td style={{ padding: "8px 12px", color: "var(--text-secondary)" }}>{fmtDuration(cp.total_duration_sec)}</td>
                        <td style={{ padding: "8px 12px", color: "var(--text-muted)", fontSize: 12 }}>{cp.first_call ? new Date(cp.first_call).toLocaleString() : "—"}</td>
                        <td style={{ padding: "8px 12px", color: "var(--text-muted)", fontSize: 12 }}>{cp.last_call ? new Date(cp.last_call).toLocaleString() : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Hourly Heatmap */}
          {Object.keys(data.hourly_message_distribution).length > 0 && (
            <div style={{ marginBottom: "var(--space-6)" }}>
              <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                Hourly Message Distribution
              </h4>
              <div style={{ display: "flex", gap: 2, alignItems: "end", height: 80 }}>
                {Array.from({ length: 24 }, (_, h) => {
                  const count = data.hourly_message_distribution[String(h)] || 0;
                  const max = Math.max(1, ...Object.values(data.hourly_message_distribution));
                  const height = Math.max(2, (count / max) * 76);
                  return (
                    <div key={h} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
                      <div style={{
                        width: "100%", height, borderRadius: 2,
                        background: count > max * 0.7 ? "var(--critical)" : count > max * 0.3 ? "var(--accent)" : "var(--line-strong)",
                        transition: "height 0.3s",
                      }} title={`${h}:00 — ${count} messages`} />
                      <span style={{ fontSize: 9, color: "var(--text-muted)" }}>{h}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* WhatsApp Senders */}
          {data.whatsapp_senders.length > 0 && (
            <div>
              <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                WhatsApp Senders
              </h4>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
                {data.whatsapp_senders.slice(0, 10).map((ws, i) => (
                  <div key={i} style={{
                    padding: "6px 14px", background: "var(--surface-1)", border: "1px solid var(--line)",
                    borderRadius: 20, font: "var(--type-body-sm)", color: "var(--text-primary)",
                  }}>
                    {ws.sender} <span style={{ color: "var(--accent)", fontWeight: 600, marginLeft: 6 }}>{ws.message_count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      )}

      {error && (
        <div style={{ padding: "var(--space-3) var(--space-5)", background: "var(--critical-tint)", borderRadius: "0 0 var(--radius-sm) var(--radius-sm)", color: "var(--critical)", font: "var(--type-body-sm)" }}>
          {error}
        </div>
      )}
    </div>
  );
}
