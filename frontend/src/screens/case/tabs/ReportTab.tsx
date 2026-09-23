import React, { useEffect, useState, useMemo } from "react";
import type { Case } from "../../../data/types";
import { Button } from "../../../components/primitives/Button";
import { useLiveStore } from "../../../state/useLiveStore";
import {
  reportsApi,
  type ReportPayload,
  type ReportSnapshotMetadata,
  type ReportType,
  type ReportClaim,
  type EvidenceCitation,
} from "../../../api/reports";
import { systemApi, type AuditVerification } from "../../../api/system";
import s from "../../../components/case/case.module.css";

interface Props {
  caseData: Case;
}

export function ReportTab({ caseData }: Props) {
  const { activeEvidence, activeCaseSummary } = useLiveStore();

  // Mode: "intelligence_brief" | "formal_dossier"
  const [activeReportType, setActiveReportType] = useState<ReportType>("intelligence_brief");

  // Snapshots state
  const [snapshots, setSnapshots] = useState<ReportSnapshotMetadata[]>([]);
  const [selectedSnapshotId, setSelectedSnapshotId] = useState<string | null>(null);
  const [currentReport, setCurrentReport] = useState<ReportPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Section filter
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);

  // Claim details inspection
  const [inspectingClaim, setInspectingClaim] = useState<ReportClaim | null>(null);
  const [inspectingCitation, setInspectingCitation] = useState<EvidenceCitation | null>(null);

  // Approval review modal
  const [reviewModalOpen, setReviewModalOpen] = useState(false);
  const [reviewAction, setReviewAction] = useState<"APPROVE" | "REJECT">("APPROVE");
  const [rejectionReason, setRejectionReason] = useState("");
  const [actionProcessing, setActionProcessing] = useState(false);

  // Audit chain verification
  const [verifying, setVerifying] = useState(true);
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const [verifyError, setVerifyError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setVerifying(true);
    setVerifyError(false);
    systemApi
      .verifyAudit()
      .then(res => { if (!cancelled) setVerification(res); })
      .catch(() => { if (!cancelled) setVerifyError(true); })
      .finally(() => { if (!cancelled) setVerifying(false); });
    return () => { cancelled = true; };
  }, []);

  const chainIntact = verification?.intact === true;
  const chainBroken = verification?.intact === false;
  const chainEntries = verification?.global_entry_count ?? verification?.case_entry_count ?? null;
  const sealText = verifying
    ? "Verifying audit chain…"
    : verifyError
      ? "Chain verification unavailable"
      : chainIntact
        ? `✓ Audit chain verified${chainEntries != null ? ` · ${chainEntries} entries` : ""}`
        : chainBroken
          ? `⚠ Chain integrity failed${verification?.first_broken_entry_id != null ? ` (entry #${verification.first_broken_entry_id})` : ""}`
          : "Chain status unknown";

  // Load existing snapshots
  const loadSnapshots = async () => {
    try {
      setLoading(true);
      const list = await reportsApi.listSnapshots(caseData.id);
      setSnapshots(list || []);
      if (list && list.length > 0 && !selectedSnapshotId) {
        setSelectedSnapshotId(list[0].report_id);
      }
    } catch (err: unknown) {
      console.warn("Failed to load report snapshots:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSnapshots();
  }, [caseData.id]);

  // Load selected snapshot payload or generate on-demand preview
  useEffect(() => {
    let cancelled = false;
    const fetchPayload = async () => {
      if (selectedSnapshotId) {
        try {
          setLoading(true);
          const data = await reportsApi.getSnapshot(caseData.id, selectedSnapshotId);
          if (!cancelled) {
            setCurrentReport(data);
            setActiveReportType(data.metadata.report_type);
            setErrorMsg(null);
          }
        } catch (err: unknown) {
          if (!cancelled) {
            setErrorMsg("Could not load report snapshot. Generating fresh draft preview...");
            handleGenerateSnapshot();
          }
        } finally {
          if (!cancelled) setLoading(false);
        }
      } else {
        // Auto-generate initial draft if none exists
        handleGenerateSnapshot();
      }
    };
    fetchPayload();
    return () => { cancelled = true; };
  }, [selectedSnapshotId]);

  const handleGenerateSnapshot = async (forcedType?: ReportType) => {
    const typeToGen = forcedType || activeReportType;
    setGenerating(true);
    setErrorMsg(null);
    try {
      const payload = await reportsApi.generateReport(caseData.id, {
        report_type: typeToGen,
        title: `${typeToGen === "formal_dossier" ? "Formal Investigation Dossier" : "Investigation Intelligence Brief"} — ${caseData.name}`,
      });
      setCurrentReport(payload);
      setSelectedSnapshotId(payload.metadata.report_id);
      await loadSnapshots();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to generate report snapshot");
    } finally {
      setGenerating(false);
    }
  };

  const handleTypeToggle = (type: ReportType) => {
    setActiveReportType(type);
    // Find matching recent snapshot of this type or generate
    const match = snapshots.find(s => s.report_type === type);
    if (match) {
      setSelectedSnapshotId(match.report_id);
    } else {
      handleGenerateSnapshot(type);
    }
  };

  const handleSubmitForReview = async () => {
    if (!currentReport) return;
    setActionProcessing(true);
    try {
      await reportsApi.submitForReview(caseData.id, currentReport.metadata.report_id);
      await loadSnapshots();
      const updated = await reportsApi.getSnapshot(caseData.id, currentReport.metadata.report_id);
      setCurrentReport(updated);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to submit for review");
    } finally {
      setActionProcessing(false);
    }
  };

  const handleReviewAction = async () => {
    if (!currentReport) return;
    if (reviewAction === "REJECT" && !rejectionReason.trim()) {
      alert("Please provide a rejection reason.");
      return;
    }
    setActionProcessing(true);
    try {
      await reportsApi.reviewSnapshot(caseData.id, currentReport.metadata.report_id, {
        action: reviewAction,
        rejection_reason: reviewAction === "REJECT" ? rejectionReason : undefined,
      });
      setReviewModalOpen(false);
      setRejectionReason("");
      await loadSnapshots();
      const updated = await reportsApi.getSnapshot(caseData.id, currentReport.metadata.report_id);
      setCurrentReport(updated);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Review submission failed");
    } finally {
      setActionProcessing(false);
    }
  };

  const handleExport = async (format: "json" | "markdown" | "html" | "pdf") => {
    if (!currentReport) return;
    try {
      if (format === "pdf") {
        await reportsApi.downloadPdf(caseData.id, caseData.id);
        return;
      }
      const data = await reportsApi.exportSnapshot(caseData.id, currentReport.metadata.report_id, format);
      const mime = format === "json" ? "application/json" : "text/plain";
      const blob = new Blob([typeof data === "string" ? data : JSON.stringify(data, null, 2)], { type: mime });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `CyberDrishti_${caseData.id}_${currentReport.metadata.report_type}.${format === "json" ? "json" : format === "markdown" ? "md" : "html"}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Export failed");
    }
  };

  const sectionsToDisplay = useMemo(() => {
    if (!currentReport) return [];
    if (!selectedSectionId) return currentReport.sections;
    return currentReport.sections.filter(s => s.section_id === selectedSectionId);
  }, [currentReport, selectedSectionId]);

  const meta = currentReport?.metadata;
  const prov = currentReport?.provenance_summary;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
      {/* ── View Toggle & Top Bar ────────────────────────────────────────── */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        flexWrap: "wrap",
        gap: "var(--space-4)",
        background: "var(--surface-1)",
        padding: "16px 20px",
        borderRadius: "var(--radius-card)",
        border: "1px solid var(--line)",
      }}>
        {/* View Switcher */}
        <div style={{ display: "flex", gap: "8px", background: "var(--surface-2)", padding: "4px", borderRadius: "8px" }}>
          <button
            onClick={() => handleTypeToggle("intelligence_brief")}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              font: "var(--type-ui)",
              fontSize: "12px",
              fontWeight: 600,
              background: activeReportType === "intelligence_brief" ? "var(--accent)" : "transparent",
              color: activeReportType === "intelligence_brief" ? "#fff" : "var(--text-secondary)",
              transition: "all 0.15s ease",
            }}
          >
            📋 Investigation Intelligence Brief
          </button>
          <button
            onClick={() => handleTypeToggle("formal_dossier")}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: "none",
              cursor: "pointer",
              font: "var(--type-ui)",
              fontSize: "12px",
              fontWeight: 600,
              background: activeReportType === "formal_dossier" ? "var(--accent)" : "transparent",
              color: activeReportType === "formal_dossier" ? "#fff" : "var(--text-secondary)",
              transition: "all 0.15s ease",
            }}
          >
            ⚖ Formal Investigation Dossier
          </button>
        </div>

        {/* Action Controls */}
        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          <Button
            variant="secondary"
            icon="command"
            onClick={() => handleGenerateSnapshot()}
            disabled={generating}
          >
            {generating ? "Generating Snapshot…" : "Generate New Snapshot"}
          </Button>

          {meta?.status === "DRAFT" && (
            <Button
              variant="primary"
              onClick={handleSubmitForReview}
              disabled={actionProcessing}
            >
              Submit for Review
            </Button>
          )}

          {meta?.status === "REVIEW" && (
            <Button
              variant="primary"
              onClick={() => setReviewModalOpen(true)}
              disabled={actionProcessing}
            >
              Supervisor Review (Four-Eyes)
            </Button>
          )}

          {meta?.status === "APPROVED" && (
            <div style={{ display: "flex", gap: "6px" }}>
              <Button variant="secondary" onClick={() => handleExport("markdown")}>
                Export Markdown
              </Button>
              <Button variant="secondary" onClick={() => handleExport("json")}>
                Export JSON
              </Button>
              <Button variant="primary" icon="download" onClick={() => handleExport("pdf")}>
                Download Certified PDF
              </Button>
            </div>
          )}

          {meta?.status === "EXPORTED" && (
            <div style={{ display: "flex", gap: "6px" }}>
              <Button variant="secondary" onClick={() => handleExport("markdown")}>
                Download MD
              </Button>
              <Button variant="primary" icon="download" onClick={() => handleExport("pdf")}>
                Download PDF
              </Button>
            </div>
          )}
        </div>
      </div>

      {/* ── Snapshot Version & Provenance Integrity Banner ─────────────── */}
      {meta && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
          gap: "16px",
        }}>
          {/* Snapshot State Card */}
          <div style={{
            background: "var(--surface-1)",
            padding: "16px 20px",
            borderRadius: "var(--radius-card)",
            border: "1px solid var(--line)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <span className="t-label">Case State Snapshot</span>
              <span style={{
                fontSize: "11px",
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: "12px",
                background:
                  meta.status === "APPROVED" || meta.status === "EXPORTED"
                    ? "rgba(16, 185, 129, 0.15)"
                    : meta.status === "REVIEW"
                      ? "rgba(245, 158, 11, 0.15)"
                      : "rgba(99, 102, 241, 0.15)",
                color:
                  meta.status === "APPROVED" || meta.status === "EXPORTED"
                    ? "var(--ok, #10B981)"
                    : meta.status === "REVIEW"
                      ? "var(--warn, #F59E0B)"
                      : "var(--accent, #6366F1)",
              }}>
                ● {meta.status}
              </span>
            </div>
            <div style={{ font: "var(--type-mono-sm)", fontWeight: 700, color: "var(--text-primary)" }}>
              Case Version: v{meta.case_state_version}
            </div>
            <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginTop: "4px" }}>
              SHA-256: {meta.content_hash.slice(0, 16)}...{meta.content_hash.slice(-8)}
            </div>
            <div className="t-body-xs" style={{ color: "var(--text-secondary)", marginTop: "6px" }}>
              Generated: {new Date(meta.generated_at).toLocaleString()}
            </div>
          </div>

          {/* Provenance Grounding Card */}
          <div style={{
            background: "var(--surface-1)",
            padding: "16px 20px",
            borderRadius: "var(--radius-card)",
            border: prov?.has_warnings ? "1px solid rgba(245, 158, 11, 0.4)" : "1px solid var(--line)",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <span className="t-label">Evidentiary Provenance</span>
              <span style={{
                fontSize: "11px",
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: "12px",
                background: prov?.has_warnings ? "rgba(245, 158, 11, 0.15)" : "rgba(16, 185, 129, 0.15)",
                color: prov?.has_warnings ? "var(--warn, #F59E0B)" : "var(--ok, #10B981)",
              }}>
                {prov?.has_warnings ? "⚠ REVIEW REQUIRED" : "✓ 100% GROUNDED"}
              </span>
            </div>
            <div style={{ font: "var(--type-mono-sm)", fontWeight: 700, color: "var(--text-primary)" }}>
              {prov?.verified_claims ?? 0} / {prov?.total_claims ?? 0} Claims Fully Linked ({prov?.verified_percentage ?? 100}%)
            </div>
            <div className="t-body-xs" style={{ color: "var(--text-secondary)", marginTop: "6px" }}>
              {(prov?.review_required_claims ?? 0) > 0 ? (
                <span style={{ color: "var(--warn, #F59E0B)", fontWeight: 600 }}>
                  ⚠ {prov?.review_required_claims ?? 0} claim(s) require investigator review (unlinked bitstream citations).
                </span>
              ) : (
                "All assertions grounded with exact file, page, line, and SHA-256 citations."
              )}
            </div>
            <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginTop: "4px" }}>
              {sealText}
            </div>
          </div>
        </div>
      )}

      {/* ── Section Filter Buttons ────────────────────────────────────────── */}
      {currentReport && currentReport.sections && (
        <div style={{
          display: "flex",
          gap: "8px",
          overflowX: "auto",
          paddingBottom: "4px",
          borderBottom: "1px solid var(--line)",
        }}>
          <button
            onClick={() => setSelectedSectionId(null)}
            style={{
              padding: "6px 14px",
              borderRadius: "20px",
              border: "1px solid var(--line)",
              font: "var(--type-ui-sm)",
              fontSize: "11px",
              fontWeight: 600,
              background: selectedSectionId === null ? "var(--surface-3)" : "var(--surface-1)",
              color: selectedSectionId === null ? "var(--accent)" : "var(--text-secondary)",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            All Sections ({currentReport.sections.length})
          </button>
          {currentReport.sections.map(sec => (
            <button
              key={sec.section_id}
              onClick={() => setSelectedSectionId(sec.section_id)}
              style={{
                padding: "6px 14px",
                borderRadius: "20px",
                border: "1px solid var(--line)",
                font: "var(--type-ui-sm)",
                fontSize: "11px",
                fontWeight: 600,
                background: selectedSectionId === sec.section_id ? "var(--surface-3)" : "var(--surface-1)",
                color: selectedSectionId === sec.section_id ? "var(--accent)" : "var(--text-secondary)",
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {sec.title} ({sec.claims.length})
            </button>
          ))}
        </div>
      )}

      {/* ── Main Report Body & Claims Viewer ────────────────────────────── */}
      <div className={s.dossierPaper}>
        {loading && (
          <div style={{ padding: "40px", textAlign: "center", color: "var(--text-muted)" }}>
            Loading investigation dossier state…
          </div>
        )}

        {!loading && currentReport && (
          <div>
            {/* Header */}
            <div className={s.dossierHeader}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                  REPORT ID: {meta?.report_id.slice(0, 12).toUpperCase()} · STATE v{meta?.case_state_version}
                </span>
                <span className="t-mono-xs" style={{ color: chainIntact ? "var(--ok)" : "var(--warn)" }}>
                  {chainIntact ? "✓ TAMPER-EVIDENT AUDIT CHAIN VERIFIED" : "⚠ AUDIT INTEGRITY CHECK PENDING"}
                </span>
              </div>
              <h2 style={{ fontSize: "18px", fontWeight: 700, margin: "0 0 6px 0", color: "var(--text-primary)" }}>
                {meta?.title}
              </h2>
              <div className="t-body-sm" style={{ color: "var(--text-secondary)" }}>
                {meta?.summary}
              </div>
            </div>

            {/* Sections */}
            {sectionsToDisplay.map(sec => (
              <div key={sec.section_id} style={{ marginBottom: "28px" }}>
                <div style={{
                  borderBottom: "1px solid var(--line)",
                  paddingBottom: "6px",
                  marginBottom: "12px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                }}>
                  <h3 style={{ fontSize: "14px", fontWeight: 700, color: "var(--text-primary)", margin: 0 }}>
                    {sec.title}
                  </h3>
                  <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                    {sec.claims.length} claims
                  </span>
                </div>

                {sec.summary && (
                  <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginBottom: "12px", fontStyle: "italic" }}>
                    {sec.summary}
                  </p>
                )}

                {/* Claims */}
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  {sec.claims.map(claim => {
                    const isVerified = claim.provenance_status === "VERIFIED";
                    return (
                      <div
                        key={claim.claim_id}
                        style={{
                          background: isVerified ? "var(--surface-1)" : "rgba(245, 158, 11, 0.05)",
                          border: isVerified ? "1px solid var(--line)" : "1px solid rgba(245, 158, 11, 0.3)",
                          borderRadius: "var(--radius-input)",
                          padding: "12px 16px",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "10px", marginBottom: "6px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <span className="t-mono-xs" style={{ fontWeight: 700, color: "var(--accent)" }}>
                              {claim.claim_id}
                            </span>
                            <span style={{
                              fontSize: "10px",
                              fontWeight: 700,
                              textTransform: "uppercase",
                              padding: "1px 6px",
                              borderRadius: "4px",
                              background:
                                claim.epistemic_status === "confirmed"
                                  ? "rgba(16, 185, 129, 0.15)"
                                  : claim.epistemic_status === "contradicted"
                                    ? "rgba(239, 68, 68, 0.15)"
                                    : "rgba(99, 102, 241, 0.15)",
                              color:
                                claim.epistemic_status === "confirmed"
                                  ? "var(--ok, #10B981)"
                                  : claim.epistemic_status === "contradicted"
                                    ? "var(--critical, #EF4444)"
                                    : "var(--accent, #6366F1)",
                            }}>
                              {claim.epistemic_status}
                            </span>
                          </div>

                          {!isVerified ? (
                            <span style={{
                              fontSize: "10px",
                              fontWeight: 800,
                              background: "rgba(245, 158, 11, 0.2)",
                              color: "#F59E0B",
                              padding: "2px 8px",
                              borderRadius: "4px",
                              border: "1px solid rgba(245, 158, 11, 0.4)",
                            }}>
                              ⚠ PROVENANCE REVIEW REQUIRED
                            </span>
                          ) : (
                            <span style={{ fontSize: "10px", fontWeight: 700, color: "var(--ok)" }}>
                              ✓ VERIFIED
                            </span>
                          )}
                        </div>

                        <div className="t-body-sm" style={{ color: "var(--text-primary)", marginBottom: "8px" }}>
                          {claim.text}
                        </div>

                        {/* Granular Evidence Citations */}
                        {claim.evidence_refs && claim.evidence_refs.length > 0 && (
                          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center", marginTop: "6px" }}>
                            <span className="t-mono-xs" style={{ color: "var(--text-muted)", marginRight: "2px" }}>
                              Citations:
                            </span>
                            {claim.evidence_refs.map((cit, cidx) => (
                              <button
                                key={cidx}
                                onClick={() => setInspectingCitation(cit)}
                                style={{
                                  background: "rgba(59, 130, 246, 0.1)",
                                  border: "1px solid rgba(59, 130, 246, 0.3)",
                                  color: "var(--accent, #3B82F6)",
                                  fontFamily: "var(--font-mono)",
                                  fontSize: "10px",
                                  padding: "2px 8px",
                                  borderRadius: "4px",
                                  cursor: "pointer",
                                  transition: "all 0.15s ease",
                                }}
                                title={`Click to inspect bitstream citation for ${cit.file_name}`}
                              >
                                {cit.citation_label}
                              </button>
                            ))}
                          </div>
                        )}

                        {/* Provenance warnings if any */}
                        {claim.provenance_chain?.warnings && claim.provenance_chain.warnings.length > 0 && (
                          <div style={{ marginTop: "8px", borderTop: "1px dashed rgba(245, 158, 11, 0.3)", paddingTop: "6px" }}>
                            {claim.provenance_chain.warnings.map((w, widx) => (
                              <div key={widx} className="t-body-xs" style={{ color: "var(--warn, #F59E0B)" }}>
                                • {w}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {/* Section Limitations */}
                {sec.limitations && sec.limitations.length > 0 && (
                  <div style={{
                    marginTop: "12px",
                    background: "rgba(245, 158, 11, 0.08)",
                    border: "1px solid rgba(245, 158, 11, 0.2)",
                    borderRadius: "var(--radius-input)",
                    padding: "10px 14px",
                  }}>
                    <div className="t-label" style={{ color: "var(--warn)", marginBottom: "4px" }}>
                      Section Limitations & Technical Boundaries:
                    </div>
                    <ul style={{ margin: 0, paddingLeft: "16px", color: "var(--text-secondary)", fontSize: "11px" }}>
                      {sec.limitations.map((lim, lidx) => (
                        <li key={lidx}>{lim}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Citation Detail Modal / Slide-out ───────────────────────────── */}
      {inspectingCitation && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setInspectingCitation(null)}
        >
          <div
            style={{
              background: "var(--surface-1)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-card)",
              padding: "24px",
              width: "520px",
              maxWidth: "90vw",
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ margin: 0, fontSize: "16px", color: "var(--text-primary)" }}>
                Evidence Bitstream Citation
              </h3>
              <button
                onClick={() => setInspectingCitation(null)}
                style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "16px" }}
              >
                ✕
              </button>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
              <div>
                <div className="t-label" style={{ marginBottom: "2px" }}>Citation Badge</div>
                <div className="t-mono-sm" style={{ color: "var(--accent)", fontWeight: 700 }}>
                  {inspectingCitation.citation_label}
                </div>
              </div>

              <div>
                <div className="t-label" style={{ marginBottom: "2px" }}>Original Artifact</div>
                <div className="t-body-sm" style={{ color: "var(--text-primary)" }}>
                  {inspectingCitation.file_name} ({inspectingCitation.source_type || "generic"})
                </div>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div>
                  <div className="t-label" style={{ marginBottom: "2px" }}>Page Number</div>
                  <div className="t-mono-sm" style={{ color: "var(--text-primary)" }}>
                    {inspectingCitation.source_page ? `Page ${inspectingCitation.source_page}` : "N/A"}
                  </div>
                </div>
                <div>
                  <div className="t-label" style={{ marginBottom: "2px" }}>Line Number</div>
                  <div className="t-mono-sm" style={{ color: "var(--text-primary)" }}>
                    {inspectingCitation.source_line ? `Line ${inspectingCitation.source_line}` : "N/A"}
                  </div>
                </div>
              </div>

              <div>
                <div className="t-label" style={{ marginBottom: "2px" }}>Section 63 BSA SHA-256 Digest</div>
                <div style={{ background: "var(--surface-2)", padding: "8px", borderRadius: "4px", wordBreak: "break-all" }}>
                  <code className="t-mono-xs" style={{ color: "var(--text-primary)" }}>
                    {inspectingCitation.sha256_hash}
                  </code>
                </div>
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "20px" }}>
              <Button variant="primary" onClick={() => setInspectingCitation(null)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Supervisor Review / Four-Eyes Modal ─────────────────────────── */}
      {reviewModalOpen && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
          }}
          onClick={() => setReviewModalOpen(false)}
        >
          <div
            style={{
              background: "var(--surface-1)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-card)",
              padding: "24px",
              width: "480px",
              maxWidth: "90vw",
            }}
            onClick={e => e.stopPropagation()}
          >
            <h3 style={{ margin: "0 0 12px 0", fontSize: "16px", color: "var(--text-primary)" }}>
              Supervisor Export Sign-Off (Four-Eyes Principle)
            </h3>
            <p className="t-body-sm" style={{ color: "var(--text-secondary)", marginBottom: "16px" }}>
              Under Section 63 BSA and NETRA supervisory protocol, formal dossiers require sign-off
              by an officer other than the investigating author.
            </p>

            <div style={{ display: "flex", gap: "10px", marginBottom: "16px" }}>
              <button
                onClick={() => setReviewAction("APPROVE")}
                style={{
                  flex: 1,
                  padding: "10px",
                  borderRadius: "6px",
                  border: reviewAction === "APPROVE" ? "2px solid var(--ok)" : "1px solid var(--line)",
                  background: reviewAction === "APPROVE" ? "rgba(16, 185, 129, 0.15)" : "var(--surface-2)",
                  color: reviewAction === "APPROVE" ? "var(--ok)" : "var(--text-secondary)",
                  cursor: "pointer",
                  fontWeight: 600,
                }}
              >
                ✓ Approve for Export
              </button>
              <button
                onClick={() => setReviewAction("REJECT")}
                style={{
                  flex: 1,
                  padding: "10px",
                  borderRadius: "6px",
                  border: reviewAction === "REJECT" ? "2px solid var(--critical)" : "1px solid var(--line)",
                  background: reviewAction === "REJECT" ? "rgba(239, 68, 68, 0.15)" : "var(--surface-2)",
                  color: reviewAction === "REJECT" ? "var(--critical)" : "var(--text-secondary)",
                  cursor: "pointer",
                  fontWeight: 600,
                }}
              >
                ✕ Reject Submission
              </button>
            </div>

            {reviewAction === "REJECT" && (
              <div style={{ marginBottom: "16px" }}>
                <div className="t-label" style={{ marginBottom: "6px" }}>Rejection Reason (Required)</div>
                <textarea
                  value={rejectionReason}
                  onChange={e => setRejectionReason(e.target.value)}
                  placeholder="Detail evidentiary deficiencies or ungrounded claims requiring revision..."
                  style={{
                    width: "100%",
                    height: "80px",
                    background: "var(--surface-2)",
                    border: "1px solid var(--line)",
                    borderRadius: "4px",
                    color: "var(--text-primary)",
                    padding: "8px",
                    font: "var(--type-ui-sm)",
                  }}
                />
              </div>
            )}

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <Button variant="secondary" onClick={() => setReviewModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleReviewAction} disabled={actionProcessing}>
                {actionProcessing ? "Processing…" : `Confirm ${reviewAction}`}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
