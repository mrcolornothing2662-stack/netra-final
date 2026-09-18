/**
 * CyberDrishti AI — Financial Intelligence Deep Panel
 * Money flow summary, round-number flags, rapid transfer detection, top counterparties, transaction ledger.
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { intelApi, type FinancialIntelResponse } from "../../../api/intelligence";
import { Button } from "../../../components/primitives/Button";

const inr = (n: number) => "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function FinanceIntelPanel({ caseId }: { caseId: string }) {
  const [data, setData] = useState<FinancialIntelResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [showAllTxns, setShowAllTxns] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await intelApi.financialIntel(caseId);
      setData(res);
      setExpanded(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load financial intelligence");
    } finally {
      setLoading(false);
    }
  };

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
          <span style={{ fontSize: 20 }}>💹</span>
          <div>
            <div className="t-label" style={{ color: "var(--text-primary)" }}>Financial Intelligence</div>
            <div className="t-body-sm" style={{ color: "var(--text-muted)" }}>
              Transaction analysis · round-number detection · rapid transfers
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {data && (
            <span className="t-mono-xs" style={{ color: "var(--accent)" }}>
              {data.total_transactions} txns · Net {inr(data.net_flow)}
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
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "var(--space-3)", marginBottom: "var(--space-6)" }}>
            {[
              { label: "Total Debit", value: inr(data.total_debit), color: "var(--critical)" },
              { label: "Total Credit", value: inr(data.total_credit), color: "var(--positive, #4ade80)" },
              { label: "Net Flow", value: inr(data.net_flow), color: data.net_flow >= 0 ? "var(--positive, #4ade80)" : "var(--critical)" },
              { label: "Transactions", value: String(data.total_transactions), color: "var(--accent)" },
            ].map((card) => (
              <div key={card.label} style={{
                padding: "var(--space-4)", background: "var(--surface-1)", borderRadius: "var(--radius-sm)",
                border: "1px solid var(--line)", textAlign: "center",
              }}>
                <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 4 }}>{card.label}</div>
                <div className="t-title-3" style={{ color: card.color, fontSize: 18 }}>{card.value}</div>
              </div>
            ))}
          </div>

          {/* Round-Number Flags */}
          {data.round_number_transactions.length > 0 && (
            <div style={{ marginBottom: "var(--space-6)" }}>
              <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                ⚠ Round-Number Transactions ({data.round_number_transactions.length})
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                {data.round_number_transactions.slice(0, 10).map((rt, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "center", gap: "var(--space-3)",
                    padding: "var(--space-3) var(--space-4)",
                    background: "rgba(255, 180, 0, 0.06)", border: "1px solid rgba(255, 180, 0, 0.2)",
                    borderRadius: "var(--radius-sm)",
                  }}>
                    <span style={{ color: "var(--warning, #f59e0b)", font: "var(--type-mono-xs)", minWidth: 50 }}>
                      {rt.direction === "debit" ? "↗ OUT" : "↙ IN"}
                    </span>
                    <span className="t-body-sm" style={{ color: "var(--text-primary)", fontWeight: 600 }}>
                      {inr(rt.amount)}
                    </span>
                    <span className="t-body-sm" style={{ color: "var(--text-muted)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {rt.narration}
                    </span>
                    <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
                      {rt.timestamp ? new Date(rt.timestamp).toLocaleString() : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Rapid Transfers */}
          {data.rapid_transfers.length > 0 && (
            <div style={{ marginBottom: "var(--space-6)" }}>
              <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                🔴 Rapid Transfer Pairs ({data.rapid_transfers.length})
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                {data.rapid_transfers.slice(0, 8).map((rt, i) => (
                  <div key={i} style={{
                    padding: "var(--space-3) var(--space-4)",
                    background: "rgba(255, 92, 92, 0.05)", border: "1px solid rgba(255, 92, 92, 0.15)",
                    borderRadius: "var(--radius-sm)",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                      <span style={{ color: "var(--critical)", font: "var(--type-mono-xs)" }}>
                        {rt.gap_minutes.toFixed(0)}min gap
                      </span>
                    </div>
                    <div className="t-body-sm" style={{ color: "var(--text-secondary)" }}>
                      <span style={{ color: "var(--text-muted)" }}>A:</span> {rt.txn_a_narration}
                    </div>
                    <div className="t-body-sm" style={{ color: "var(--text-secondary)" }}>
                      <span style={{ color: "var(--text-muted)" }}>B:</span> {rt.txn_b_narration}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top Counterparties */}
          {data.top_counterparties_by_volume.length > 0 && (
            <div style={{ marginBottom: "var(--space-6)" }}>
              <h4 className="t-label" style={{ color: "var(--text-primary)", marginBottom: "var(--space-3)" }}>
                Top Counterparties by Volume
              </h4>
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {data.top_counterparties_by_volume.slice(0, 12).map((cp, i) => {
                  const max = data.top_counterparties_by_volume[0]?.total_amount || 1;
                  const pct = Math.max(4, (cp.total_amount / max) * 100);
                  return (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                      <div style={{ flex: 1, position: "relative", height: 24, background: "var(--surface-1)", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct}%`, background: "var(--accent)", opacity: 0.15, borderRadius: 3 }} />
                        <span style={{ position: "relative", padding: "0 8px", lineHeight: "24px", font: "var(--type-body-sm)", color: "var(--text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", display: "block" }}>
                          {cp.narration}
                        </span>
                      </div>
                      <span className="t-mono-xs" style={{ color: "var(--accent)", minWidth: 90, textAlign: "right" }}>
                        {inr(cp.total_amount)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Transaction Ledger */}
          {data.transactions.length > 0 && (
            <div>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "var(--space-3)" }}>
                <h4 className="t-label" style={{ color: "var(--text-primary)" }}>
                  Transaction Ledger ({data.transactions.length})
                </h4>
                {data.transactions.length > 15 && (
                  <Button variant="ghost" onClick={() => setShowAllTxns(!showAllTxns)}>
                    {showAllTxns ? "Show Less" : "Show All"}
                  </Button>
                )}
              </div>
              <div style={{ overflowX: "auto", maxHeight: showAllTxns ? undefined : 400 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", font: "var(--type-body-sm)" }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--line)" }}>
                      {["Date", "Narration", "Debit", "Credit", "Balance"].map((h) => (
                        <th key={h} style={{ padding: "8px 10px", textAlign: h === "Narration" ? "left" : "right", color: "var(--text-muted)", font: "var(--type-mono-xs)", letterSpacing: "0.05em" }}>
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(showAllTxns ? data.transactions : data.transactions.slice(0, 15)).map((txn, i) => (
                      <tr key={txn.id || i} style={{ borderBottom: "1px solid var(--line-faint)" }}>
                        <td style={{ padding: "6px 10px", color: "var(--text-muted)", fontSize: 11, whiteSpace: "nowrap", textAlign: "right" }}>
                          {txn.timestamp ? new Date(txn.timestamp).toLocaleDateString() : "—"}
                        </td>
                        <td style={{ padding: "6px 10px", color: "var(--text-primary)", maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {txn.narration}
                        </td>
                        <td style={{ padding: "6px 10px", textAlign: "right", color: txn.debit ? "var(--critical)" : "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                          {txn.debit ? inr(txn.debit) : "—"}
                        </td>
                        <td style={{ padding: "6px 10px", textAlign: "right", color: txn.credit ? "var(--positive, #4ade80)" : "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                          {txn.credit ? inr(txn.credit) : "—"}
                        </td>
                        <td style={{ padding: "6px 10px", textAlign: "right", color: "var(--text-secondary)", fontFamily: "var(--font-mono)" }}>
                          {txn.balance != null ? inr(txn.balance) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
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
