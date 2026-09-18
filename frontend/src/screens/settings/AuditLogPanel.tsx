/**
 * CyberDrishti AI — Audit Log Viewer Panel
 * Browsable SHA-256 chained audit trail with pagination and filtering.
 */
import { useState, useEffect, useCallback } from "react";
import { auditApi, type AuditLogEntry } from "../../api/audit";
import { systemApi, type AuditVerification } from "../../api/system";
import { Button } from "../../components/primitives/Button";

const ACTION_COLORS: Record<string, string> = {
  GENESIS: "var(--accent)",
  CASE_CREATED: "var(--positive, #4ade80)",
  EVIDENCE_UPLOADED: "var(--positive, #4ade80)",
  EVIDENCE_PROCESSED: "var(--accent)",
  ENTITY_EXTRACTED: "var(--accent)",
  CORRELATION_FLAGGED: "var(--warning, #f59e0b)",
  AGENT_ACTION: "var(--accent)",
  AGENT_HOLD_APPROVED: "var(--positive, #4ade80)",
  AGENT_HOLD_REJECTED: "var(--critical)",
  LOGIN: "var(--text-muted)",
  PASSWORD_CHANGED: "var(--warning, #f59e0b)",
};

export function AuditLogPanel() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [filterAction, setFilterAction] = useState("");
  const [filterCaseId, setFilterCaseId] = useState("");
  const perPage = 25;

  const loadEntries = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await auditApi.list({
        page,
        page_size: perPage,
        action: filterAction || undefined,
        case_id: filterCaseId || undefined,
      });
      if (Array.isArray(res)) {
        setEntries(res);
        setTotal(res.length);
      } else {
        setEntries(res.items || []);
        setTotal(res.total || 0);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load audit logs");
    } finally {
      setLoading(false);
    }
  }, [page, filterAction, filterCaseId]);

  useEffect(() => { loadEntries(); }, [loadEntries]);

  const verifyChain = async () => {
    setVerifying(true);
    try {
      const res = await systemApi.verifyAudit();
      setVerification(res);
    } catch {
      setVerification(null);
    } finally {
      setVerifying(false);
    }
  };

  useEffect(() => { verifyChain(); }, []);

  const fieldStyle: React.CSSProperties = {
    padding: "6px 10px", background: "var(--surface-0)",
    border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
    color: "var(--text-primary)", font: "var(--type-body-sm)", outline: "none",
  };

  return (
    <div>
      {/* Chain Verification Badge */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "var(--space-4)", marginBottom: "var(--space-4)",
        background: verification?.intact ? "rgba(74, 222, 128, 0.06)" : "var(--surface-1)",
        border: `1px solid ${verification?.intact ? "rgba(74, 222, 128, 0.3)" : "var(--line)"}`,
        borderRadius: "var(--radius-card)",
      }}>
        <div>
          <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: 2 }}>
            SHA-256 AUDIT CHAIN
          </div>
          <div className="t-body-sm" style={{
            color: verification?.intact ? "var(--positive, #4ade80)" : verification ? "var(--critical)" : "var(--text-muted)",
          }}>
            {verifying ? "Verifying chain integrity…"
              : verification?.intact ? `✓ Chain verified · ${verification.global_entry_count ?? "?"} entries`
              : verification ? `⚠ Chain integrity broken at entry #${verification.first_broken_entry_id}`
              : "Chain status unknown"}
          </div>
        </div>
        <Button variant="ghost" onClick={verifyChain} disabled={verifying}>
          {verifying ? "Checking…" : "Re-verify"}
        </Button>
      </div>

      {/* Filters */}
      <div style={{ display: "flex", gap: "var(--space-3)", marginBottom: "var(--space-4)", flexWrap: "wrap" }}>
        <input
          style={{ ...fieldStyle, width: 180 }}
          value={filterAction}
          onChange={(e) => { setFilterAction(e.target.value); setPage(1); }}
          placeholder="Filter by action…"
        />
        <input
          style={{ ...fieldStyle, width: 200 }}
          value={filterCaseId}
          onChange={(e) => { setFilterCaseId(e.target.value); setPage(1); }}
          placeholder="Filter by case ID…"
        />
        <Button variant="ghost" onClick={loadEntries} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </Button>
      </div>

      {error && (
        <div style={{
          padding: "var(--space-3) var(--space-4)", marginBottom: "var(--space-4)",
          background: "var(--critical-tint)", border: "1px solid rgba(255,92,92,0.3)",
          borderRadius: "var(--radius-sm)", color: "var(--critical)", font: "var(--type-body-sm)",
        }}>
          {error}
        </div>
      )}

      {/* Log Table */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", font: "var(--type-body-sm)" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--line)" }}>
              {["#", "Action", "Resource", "ID", "Hash", "Time"].map((h) => (
                <th key={h} style={{
                  padding: "8px 10px", textAlign: "left",
                  color: "var(--text-muted)", font: "var(--type-mono-xs)",
                  letterSpacing: "0.05em",
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} style={{ borderBottom: "1px solid var(--line-faint)" }}>
                <td style={{ padding: "6px 10px", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                  {e.id}
                </td>
                <td style={{ padding: "6px 10px" }}>
                  <span style={{
                    padding: "2px 8px", borderRadius: 4, fontSize: 10,
                    fontWeight: 700, letterSpacing: "0.06em",
                    background: (ACTION_COLORS[e.action] || "var(--text-muted)") + "18",
                    color: ACTION_COLORS[e.action] || "var(--text-secondary)",
                  }}>
                    {e.action}
                  </span>
                </td>
                <td style={{ padding: "6px 10px", color: "var(--text-secondary)" }}>{e.resource_type}</td>
                <td style={{ padding: "6px 10px", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11, maxWidth: 120, overflow: "hidden", textOverflow: "ellipsis" }}>
                  {e.resource_id}
                </td>
                <td style={{ padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent)" }}>
                  {e.entry_hash.slice(0, 12)}…
                </td>
                <td style={{ padding: "6px 10px", color: "var(--text-muted)", fontSize: 11, whiteSpace: "nowrap" }}>
                  {e.event_timestamp ? new Date(e.event_timestamp).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {entries.length === 0 && !loading && (
        <div style={{ textAlign: "center", padding: "var(--space-8)", color: "var(--text-muted)" }}>
          No audit entries found.
        </div>
      )}

      {/* Pagination */}
      {total > perPage && (
        <div style={{ display: "flex", justifyContent: "center", gap: "var(--space-3)", marginTop: "var(--space-4)" }}>
          <Button variant="ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            ← Previous
          </Button>
          <span className="t-mono-xs" style={{ color: "var(--text-muted)", alignSelf: "center" }}>
            Page {page} of {Math.ceil(total / perPage)}
          </span>
          <Button variant="ghost" disabled={page >= Math.ceil(total / perPage)} onClick={() => setPage((p) => p + 1)}>
            Next →
          </Button>
        </div>
      )}
    </div>
  );
}
