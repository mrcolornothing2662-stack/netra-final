import React, { useState } from "react";
import type {
  IdentityCandidateQueueItem,
  IdentityCandidateDetail,
} from "../../../types/entities";
import { entitiesApi } from "../../../api/entities";
import s from "./EntityExplorer.module.css";

interface IdentityConflictPanelProps {
  candidate: IdentityCandidateQueueItem | IdentityCandidateDetail;
  caseId: string;
  caseStateVersion?: number;
  canResolve?: boolean;
  onResolved?: (candidateId: string, verdict: string) => void;
  onSelectEntity?: (entityId: string) => void;
}

export function IdentityConflictPanel({
  candidate,
  caseId,
  caseStateVersion,
  canResolve = true,
  onResolved,
  onSelectEntity,
}: IdentityConflictPanelProps) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [localStatus, setLocalStatus] = useState(candidate.resolution_status);

  // Normalize canonical and candidate entity references
  const queueItem = candidate as Partial<IdentityCandidateQueueItem>;
  const detailItem = candidate as Partial<IdentityCandidateDetail>;

  const canonicalValue =
    queueItem.canonical_entity?.canonical_value ||
    "Primary Entity";
  const canonicalId =
    queueItem.canonical_entity?.id ||
    detailItem.canonical_entity_id ||
    null;
  const canonicalType =
    queueItem.canonical_entity?.entity_type || "UNKNOWN";

  const candidateValue =
    queueItem.candidate_entity?.canonical_value ||
    candidate.candidate_value ||
    "Ambiguous Entity";
  const candidateId = queueItem.candidate_entity?.id || null;
  const candidateType =
    queueItem.candidate_entity?.entity_type ||
    candidate.candidate_type ||
    "UNKNOWN";

  const isResolved =
    localStatus !== "UNRESOLVED" && localStatus !== "PENDING";

  const handleResolve = async (verdict: "CONFIRMED_SAME" | "CONFIRMED_DIFFERENT") => {
    if (submitting || isResolved) return;
    setSubmitting(true);
    setError(null);

    try {
      await entitiesApi.resolveIdentityCandidate(caseId, candidate.id, {
        verdict,
        reason: reason.trim() || undefined,
        base_case_version: caseStateVersion,
      });

      setLocalStatus(verdict);
      if (onResolved) {
        onResolved(candidate.id, verdict);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to adjudicate identity conflict";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className={`${s.conflictCard} ${
        !isResolved ? s.conflictCardUnresolved : ""
      }`}
    >
      {/* Epistemic Safety Notice */}
      <div className={s.conflictBanner}>
        <span style={{ fontSize: "18px" }}>⚠️</span>
        <div>
          <strong>Cognitive Identity Ambiguity</strong> — Invariant:{" "}
          <code>Candidate Identity ≠ Confirmed Entity</code>. AI similarity results
          never auto-merge entities. Explicit human adjudication is required.
        </div>
      </div>

      {/* Side-by-Side Comparison */}
      <div className={s.compareGrid}>
        <div className={s.compareColumn}>
          <div className={s.columnHeader}>
            <span>Canonical Entity</span>
            <span className={s.typeBadge}>{canonicalType}</span>
          </div>
          <div className={s.columnValue}>{canonicalValue}</div>
          {canonicalId && (
            <div style={{ marginTop: "var(--space-2)" }}>
              {onSelectEntity ? (
                <button
                  type="button"
                  onClick={() => onSelectEntity(canonicalId)}
                  style={{
                    background: "none",
                    border: "none",
                    color: "var(--intel)",
                    cursor: "pointer",
                    fontSize: "12px",
                    textDecoration: "underline",
                    padding: 0,
                  }}
                >
                  View Dossier →
                </button>
              ) : (
                <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                  ID: {canonicalId}
                </span>
              )}
            </div>
          )}
        </div>

        <div className={s.compareColumn}>
          <div className={s.columnHeader}>
            <span>Candidate / Ambiguous</span>
            <span className={s.typeBadge}>{candidateType}</span>
          </div>
          <div className={s.columnValue}>{candidateValue}</div>
          {candidateId && onSelectEntity && (
            <div style={{ marginTop: "var(--space-2)" }}>
              <button
                type="button"
                onClick={() => onSelectEntity(candidateId)}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--intel)",
                  cursor: "pointer",
                  fontSize: "12px",
                  textDecoration: "underline",
                  padding: 0,
                }}
              >
                View Dossier →
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Signals: Match vs Conflict */}
      <div className={s.signalsSection}>
        {candidate.match_signals && candidate.match_signals.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            <span className={s.sectionTitle} style={{ color: "var(--verified)" }}>
              Supporting Match Signals ({candidate.match_signals.length})
            </span>
            {candidate.match_signals.map((sig, idx) => (
              <div key={`m-${idx}`} className={`${s.signalBox} ${s.signalBoxMatch}`}>
                <div className={`${s.signalTitle} ${s.signalMatchTitle}`}>
                  <span>{sig.signal}</span>
                  <span className="t-mono-xs" style={{ opacity: 0.8 }}>
                    STRENGTH: {sig.strength}
                  </span>
                </div>
                <div className={s.signalText}>{sig.detail}</div>
              </div>
            ))}
          </div>
        )}

        {candidate.conflict_signals && candidate.conflict_signals.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "var(--space-2)" }}>
            <span className={s.sectionTitle} style={{ color: "var(--critical)" }}>
              Contradicting / Conflicting Signals ({candidate.conflict_signals.length})
            </span>
            {candidate.conflict_signals.map((sig, idx) => (
              <div key={`c-${idx}`} className={`${s.signalBox} ${s.signalBoxConflict}`}>
                <div className={`${s.signalTitle} ${s.signalConflictTitle}`}>
                  <span>{sig.signal}</span>
                  <span className="t-mono-xs" style={{ opacity: 0.8 }}>
                    SEVERITY: {sig.severity}
                  </span>
                </div>
                <div className={s.signalText}>{sig.detail}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Resolution Actions or Status */}
      {isResolved ? (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid var(--line)", paddingTop: "var(--space-3)" }}>
          <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
            Adjudication Complete:
          </span>
          <span className={`${s.resolutionStatusBadge} ${s[`status${localStatus}`] || ""}`}>
            {localStatus === "CONFIRMED_SAME"
              ? "✓ CONFIRMED SAME (CANONICAL SAME_AS)"
              : localStatus === "CONFIRMED_DIFFERENT"
              ? "✗ KEPT SEPARATE (CONFIRMED DIFFERENT)"
              : localStatus}
          </span>
        </div>
      ) : (
        <div className={s.adjudicateActions}>
          <label htmlFor={`reason-${candidate.id}`} className={s.sectionTitle}>
            Investigator Adjudication Rationale
          </label>
          <textarea
            id={`reason-${candidate.id}`}
            className={s.reasonInput}
            placeholder="Record legal justification, investigative basis, or corroborate with physical evidence..."
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={submitting || !canResolve}
          />

          {error && (
            <div style={{ color: "var(--critical)", fontSize: "12px" }}>
              {error}
            </div>
          )}

          <div className={s.actionBtnRow}>
            <button
              type="button"
              className={`${s.btnDifferent} ${
                submitting || !canResolve ? s.btnDisabled : ""
              }`}
              onClick={() => handleResolve("CONFIRMED_DIFFERENT")}
              disabled={submitting || !canResolve}
              title={
                !canResolve
                  ? "Requires Investigator or Admin role (CAP_ENTITY_WRITE)"
                  : "Preserve separate entity identities with no aliases"
              }
            >
              {submitting ? "Processing..." : "Keep Separate (Confirmed Different)"}
            </button>

            <button
              type="button"
              className={`${s.btnSame} ${
                submitting || !canResolve ? s.btnDisabled : ""
              }`}
              onClick={() => handleResolve("CONFIRMED_SAME")}
              disabled={submitting || !canResolve}
              title={
                !canResolve
                  ? "Requires Investigator or Admin role (CAP_ENTITY_WRITE)"
                  : "Establish canonical SAME_AS edge and alias reference"
              }
            >
              {submitting ? "Processing..." : "Resolve Identities (Confirmed Same)"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
