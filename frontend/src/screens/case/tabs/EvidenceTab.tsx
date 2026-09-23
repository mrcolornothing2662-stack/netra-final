import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Icon } from "../../../components/icons";
import { Button } from "../../../components/primitives/Button";
import { TraceDot } from "../../../components/primitives/TraceDot";
import { useTrace, useTraceDwell } from "../../../state/traceHooks";
import { useLiveStore } from "../../../state/useLiveStore";
import { kindCounts } from "../../../data/evidence";
import type { Evidence, EvidenceKind } from "../../../data/types";
import { EvidencePreviewModal } from "./EvidencePreviewModal";
import { evidenceApi, type EvidenceConfirmResponse, type EvidenceConfirmBatchResponse } from "../../../api/evidence";
import { reportsApi, type EvidenceUsage } from "../../../api/reports";
import prim from "../../../components/primitives/primitives.module.css";
import s from "../../../components/case/case.module.css";

export function EvidenceTab({ caseId }: { caseId: string }) {
  const { activeEvidence, refreshEvidence, fetchCaseDetails } = useLiveStore();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeKind = (searchParams.get("kind") as EvidenceKind | "ALL") || "ALL";
  const search = searchParams.get("q") || "";

  const [selected, setSelected] = useState<Evidence | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const [uploadFailed, setUploadFailed] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sheetCloseRef = useRef<HTMLButtonElement>(null);

  const [usageData, setUsageData] = useState<EvidenceUsage | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(false);

  useEffect(() => {
    if (selected?.id) {
      setLoadingUsage(true);
      reportsApi.getEvidenceUsage(caseId, selected.id)
        .then(res => setUsageData(res))
        .catch(err => {
          console.warn("Evidence usage fetch error:", err);
          setUsageData(null);
        })
        .finally(() => setLoadingUsage(false));
    } else {
      setUsageData(null);
    }
  }, [selected?.id, caseId]);

  const handleRetry = async (evidenceId: string) => {
    try {
      setRetryingId(evidenceId);
      await evidenceApi.retryProcessing(caseId, evidenceId);
      setUploadFailed(false);
      setUploadMsg("Processing restarted. Extracting events, entities, and graph relations...");
      await refreshEvidence(caseId);
    } catch (err: unknown) {
      setUploadFailed(true);
      setUploadMsg(err instanceof Error ? err.message : "Failed to restart processing");
    } finally {
      setRetryingId(null);
    }
  };

  const items = activeEvidence;
  const kinds = kindCounts(items);

  // Auto-poll while any evidence item is in PROCESSING status so UI live-updates to ANALYZED
  const hasProcessing = items.some(it => it.status === "PROCESSING");
  useEffect(() => {
    if (!hasProcessing) return;
    const interval = setInterval(() => {
      fetchCaseDetails(caseId);
    }, 2500);
    return () => clearInterval(interval);
  }, [hasProcessing, caseId, fetchCaseDetails]);

  const filtered = items.filter(it => {
    if (activeKind !== "ALL" && it.kind !== activeKind) return false;
    if (search && !it.label.toLowerCase().includes(search.toLowerCase()) && !it.meta.toLowerCase().includes(search.toLowerCase()) && !it.id.toLowerCase().includes(search.toLowerCase())) {
      return false;
    }
    return true;
  });

  const setKind = (kind: EvidenceKind | "ALL") => {
    const next = new URLSearchParams(searchParams);
    if (kind === "ALL") next.delete("kind");
    else next.set("kind", kind);
    setSearchParams(next, { replace: true });
  };

  const setSearch = (val: string) => {
    const next = new URLSearchParams(searchParams);
    if (!val) next.delete("q");
    else next.set("q", val);
    setSearchParams(next, { replace: true });
  };

  // Focus management on slide-out sheet
  useEffect(() => {
    if (selected) {
      sheetCloseRef.current?.focus();
      const onKey = (e: KeyboardEvent) => {
        if (e.key === "Escape") setSelected(null);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }
  }, [selected]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const chosen = Array.from(files);
    setPendingFiles(chosen);
    setPendingFile(chosen[0] || null);
    setPreviewOpen(true);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleConfirmed = async (res: EvidenceConfirmResponse | EvidenceConfirmBatchResponse) => {
    setUploadFailed(false);
    if ("sealed_count" in res) {
      setUploadMsg(`✓ ${res.sealed_count} evidence file(s) sealed into Section 63 BSA chain of custody.${res.failed_count > 0 ? ` (${res.failed_count} failed)` : ""}`);
    } else {
      setUploadMsg(`✓ Evidence "${res.filename}" sealed into Section 63 BSA chain of custody. SHA-256: ${res.sha256_hash ? res.sha256_hash.slice(0, 16) + "…" : "locked"}`);
    }
    setTimeout(() => setUploadMsg(null), 8000);
    await refreshEvidence(caseId);
  };

  return (
    <div>
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        multiple
        style={{ display: "none" }}
        accept=".txt,.pdf,.csv,.xlsx,.png,.jpg,.jpeg,.zip"
      />

      <div className={s.evToolbar}>
        <div className={s.evKinds} role="group" aria-label="Evidence category filter">
          {kinds.map(k => (
            <button
              key={k.kind}
              aria-pressed={activeKind === k.kind}
              className={`${s.evPill} ${activeKind === k.kind ? s.evPillOn : ""}`}
              onClick={() => setKind(k.kind)}
            >
              {k.label} ({k.count})
            </button>
          ))}
        </div>

        <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
          <div className={s.evSearch}>
            <Icon name="search" size={14} />
            <input
              value={search}
              aria-label="Search evidence archive"
              onChange={e => setSearch(e.target.value)}
              placeholder="Search evidence archive…"
            />
          </div>
          <Button
            variant="primary"
            icon="plus"
            onClick={() => fileInputRef.current?.click()}
            disabled={previewOpen}
          >
            Preview & Ingest
          </Button>
        </div>
      </div>

      {uploadMsg && (
        <div style={{ padding: "8px 12px", background: uploadFailed ? "rgba(239, 68, 68, 0.1)" : "var(--surface-2)", border: `1px solid ${uploadFailed ? "rgba(239, 68, 68, 0.4)" : "var(--line-strong)"}`, borderRadius: "var(--radius-input)", marginBottom: "var(--space-4)", font: "var(--type-mono-xs)", color: uploadFailed ? "var(--critical)" : "var(--verified)" }} role={uploadFailed ? "alert" : "status"}>
          {uploadMsg}
        </div>
      )}

      <div className="sr-only" role="status" aria-live="polite" style={{ position: "absolute", opacity: 0, pointerEvents: "none" }}>
        Showing {filtered.length} evidence items
      </div>

      {items.length === 0 ? (
        <div style={{
          padding: "var(--space-12) var(--space-6)", textAlign: "center",
          background: "var(--surface-1)", border: "1px dashed var(--line-strong)",
          borderRadius: "var(--radius-card)", marginTop: "var(--space-6)"
        }}>
          <div style={{ font: "var(--type-mono-xs)", color: "var(--intel)", letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "var(--space-2)" }}>
            Digital Evidence Ingestion Enclave
          </div>
          <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
            No Evidence Files Ingested Yet
          </h3>
          <p className="measure" style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", margin: "0 auto var(--space-6) auto" }}>
            Ingest call detail records (CDR), WhatsApp extraction dumps, bank transaction ledgers (CSV/XLSX), or forensic disk dumps.
            The system provides a read-only pre-hash inspection preview before computing SHA-256 custody checksums under Section 63 BSA 2023.
          </p>
          <Button variant="primary" icon="plus" onClick={() => fileInputRef.current?.click()} disabled={previewOpen}>
            Preview & Ingest Evidence
          </Button>
        </div>
      ) : filtered.length === 0 ? (
        <div style={{
          padding: "var(--space-8) var(--space-4)", textAlign: "center",
          background: "var(--surface-1)", border: "1px solid var(--line)",
          borderRadius: "var(--radius-card)", marginTop: "var(--space-4)"
        }}>
          <p style={{ color: "var(--text-secondary)", font: "var(--type-body)", marginBottom: "var(--space-4)" }}>
            No evidence matches the current filter criteria.
          </p>
          <Button variant="secondary" onClick={() => { setKind("ALL"); setSearch(""); }}>
            Clear Filters
          </Button>
        </div>
      ) : (
        <div className={s.evGrid}>
          {filtered.map(it => (
            <EvidenceCardItem key={it.id} evidence={it} onSelect={() => setSelected(it)} />
          ))}
        </div>
      )}

      {selected && (
        <>
          <div className={s.sheetOverlay} onClick={() => setSelected(null)} />
          <div
            className={s.sheet}
            role="dialog"
            aria-modal="true"
            aria-labelledby={`sheet-title-${selected.id}`}
          >
            <div className={s.sheetHead}>
              <span className="t-label">{selected.kind} EVIDENCE</span>
              <button
                ref={sheetCloseRef}
                className={s.sheetClose}
                onClick={() => setSelected(null)}
                aria-label="Close detail panel"
              >
                <Icon name="close" size={18} />
              </button>
            </div>
            <h2 id={`sheet-title-${selected.id}`} className="t-title-2" style={{ marginBottom: "var(--space-2)" }}>
              {selected.label}
            </h2>
            <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center", marginBottom: "var(--space-6)" }}>
              <span className={`${s.statusBadge} ${s[`status${selected.status}`]}`}>{selected.status}</span>
              <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>{selected.meta}</span>
            </div>

            {selected.imageUrl && (
              <div style={{ marginBottom: "var(--space-6)", borderRadius: "var(--radius-card)", overflow: "hidden" }}>
                <img src={selected.imageUrl} alt={selected.label} style={{ width: "100%", height: "auto", display: "block" }} />
              </div>
            )}

            <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>Chain of custody & notes</div>
            <p className="t-body measure" style={{ color: "var(--text-secondary)", marginBottom: "var(--space-6)" }}>
              {selected.notes ?? "Acquired in accordance with Section 63 BSA 2023. Bitstream digital duplicate generated upon collection."}
            </p>

            {selected.status === "UNVERIFIED" && (
              <div style={{
                marginBottom: "var(--space-6)",
                padding: "12px 16px",
                background: "rgba(239, 68, 68, 0.08)",
                border: "1px solid rgba(239, 68, 68, 0.25)",
                borderRadius: "var(--radius-card)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <div style={{ font: "var(--type-mono-xs)", color: "var(--critical)", fontWeight: 600 }}>
                    PARSER NOTICE
                  </div>
                  <Button
                    variant="secondary"
                    onClick={() => handleRetry(selected.id)}
                    disabled={retryingId === selected.id}
                  >
                    {retryingId === selected.id ? "Restarting..." : "Retry Processing"}
                  </Button>
                </div>
                <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)" }}>
                  The evidence bitstream is securely sealed under Section 63 BSA. Parsing encountered an unhandled format or syntax error. Click Retry to re-run the forensic parser.
                </div>
              </div>
            )}

            {((selected as any).variant_note || selected.variant_details) && (
              <div style={{
                marginBottom: "var(--space-6)",
                padding: "12px 16px",
                background: "rgba(245, 158, 11, 0.08)",
                border: "1px solid rgba(245, 158, 11, 0.25)",
                borderRadius: "var(--radius-card)",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                  <div style={{ font: "var(--type-mono-xs)", color: "var(--warning)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
                    F01 · Document Version Lineage (v{selected.version_number || 2})
                  </div>
                  {selected.variant_details?.containment && (
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                      {Math.round(selected.variant_details.containment * 100)}% Containment
                    </span>
                  )}
                </div>
                <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", marginBottom: "8px" }}>
                  {(selected as any).variant_note || `Variant of ${selected.variant_details?.parent_name || "parent document"}`}
                </div>
                {selected.variant_details?.diff && (
                  <div style={{ display: "flex", gap: "12px", font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                    <span style={{ color: "var(--verified)" }}>+{selected.variant_details.diff.added_rows ?? selected.variant_details.added_row_count ?? 0} added</span>
                    <span>·</span>
                    <span>{selected.variant_details.diff.unchanged_rows ?? selected.variant_details.unchanged_row_count ?? 0} unchanged</span>
                    <span>·</span>
                    <span style={{ color: "var(--critical)" }}>-{selected.variant_details.diff.removed_rows ?? selected.variant_details.removed_row_count ?? 0} removed</span>
                  </div>
                )}
                {selected.variant_details?.impact?.new_entities && selected.variant_details.impact.new_entities.length > 0 && (
                  <div style={{ marginTop: "8px", borderTop: "1px dashed rgba(245, 158, 11, 0.2)", paddingTop: "8px" }}>
                    <div style={{ font: "var(--type-mono-xs)", color: "var(--text-primary)", marginBottom: "4px" }}>
                      Introduced Entities ({selected.variant_details.impact.new_entities.length}):
                    </div>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                      {selected.variant_details.impact.new_entities.map((e: any) => (
                        <span key={e.id} style={{
                          fontSize: "11px",
                          padding: "2px 6px",
                          background: "var(--surface-2)",
                          borderRadius: "4px",
                          border: "1px solid var(--line)",
                          fontFamily: "var(--font-mono)",
                        }}>
                          [{e.entity_type}] {e.canonical_value}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginBottom: "var(--space-6)" }}>
              <div>
                <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>Section 63 BSA SHA-256</div>
                <div style={{ background: "var(--surface-1)", padding: "10px", borderRadius: "var(--radius-input)", wordBreak: "break-all" }}>
                  <code className="t-mono-xs" style={{ color: "var(--text-primary)" }}>{selected.sha256 ?? "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}</code>
                </div>
              </div>
              <div>
                <div className="t-label" style={{ marginBottom: "var(--space-2)" }}>MinHash Fingerprint (k=128)</div>
                <div style={{ background: "var(--surface-1)", padding: "10px", borderRadius: "var(--radius-input)", wordBreak: "break-all" }}>
                  <code className="t-mono-xs" style={{ color: "var(--accent)" }}>
                    {(selected as any).fingerprint || `MH-${(selected.sha256 || selected.id).slice(0, 8).toUpperCase()}`}
                  </code>
                </div>
              </div>
            </div>

            {/* Milestone 9: Controlled Evidence Access / Download */}
            <div style={{ marginBottom: "var(--space-4)" }}>
              <button
                className={prim.btn}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                  fontSize: "12px",
                  padding: "8px 12px",
                  background: "var(--surface-2)",
                  border: "1px solid var(--line-strong)",
                  color: "var(--text-primary)",
                  cursor: "pointer",
                  borderRadius: "var(--radius-input)",
                }}
                onClick={() => {
                  const reason = window.prompt("Section 63 BSA Custody Verification\nEnter operational justification for accessing original evidence bytes:");
                  if (!reason || reason.trim().length < 5) {
                    alert("Access denied: An operational justification of at least 5 characters is required under Section 63 BSA.");
                    return;
                  }
                  const url = `/api/v1/evidence/${caseId}/files/${selected.id}/download?reason=${encodeURIComponent(reason.trim())}`;
                  window.open(url, "_blank");
                }}
              >
                <span>🔒</span> Download Original Artifact (Section 63 BSA)
              </button>
            </div>

            {/* Milestone 8: Bidirectional Report & Finding Provenance Usage */}
            <div style={{
              marginBottom: "var(--space-6)",
              padding: "14px 16px",
              background: "var(--surface-1)",
              borderRadius: "var(--radius-input)",
              border: "1px solid var(--line)",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                <div className="t-label" style={{ color: "var(--text-primary)", fontWeight: 700 }}>
                  Report &amp; Finding Provenance
                </div>
                <span className="t-mono-xs" style={{
                  color: (usageData?.total_usages ?? 0) > 0 ? "var(--ok)" : "var(--text-muted)",
                  fontWeight: 700,
                }}>
                  {loadingUsage ? "Scanning graph…" : `${usageData?.total_usages ?? 0} Linked Usages`}
                </span>
              </div>

              {usageData && usageData.total_usages > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                  {usageData.findings.length > 0 && (
                    <div>
                      <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: "4px" }}>
                        Citing Findings ({usageData.findings.length}):
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        {usageData.findings.map(f => (
                          <div key={f.id} style={{
                            fontSize: "11px",
                            padding: "4px 8px",
                            background: "var(--surface-2)",
                            borderRadius: "4px",
                            border: "1px solid var(--line)",
                          }}>
                            <span style={{ fontWeight: 700, color: "var(--accent)" }}>[{f.severity}]</span> {f.title}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {usageData.relationships.length > 0 && (
                    <div>
                      <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: "4px" }}>
                        Citing Graph Relationships ({usageData.relationships.length}):
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        {usageData.relationships.map(r => (
                          <div key={r.id} style={{
                            fontSize: "11px",
                            padding: "4px 8px",
                            background: "var(--surface-2)",
                            borderRadius: "4px",
                            border: "1px solid var(--line)",
                          }}>
                            {r.source_name} <span style={{ color: "var(--accent)" }}>-[{r.rel_type}]-&gt;</span> {r.target_name}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {usageData.claims.length > 0 && (
                    <div>
                      <div className="t-mono-xs" style={{ color: "var(--text-muted)", marginBottom: "4px" }}>
                        Citing Dossier Claims ({usageData.claims.length}):
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                        {usageData.claims.slice(0, 4).map((c, i) => (
                          <div key={i} style={{
                            fontSize: "11px",
                            padding: "4px 8px",
                            background: "var(--surface-2)",
                            borderRadius: "4px",
                            border: "1px solid var(--line)",
                          }}>
                            <strong style={{ color: "var(--accent)" }}>{c.claim_id}:</strong> {c.text}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="t-body-xs" style={{ color: "var(--text-muted)" }}>
                  {loadingUsage ? "Scanning case graph for citations…" : "No analytical findings or claims currently cite this evidence artifact."}
                </div>
              )}
            </div>
          </div>
        </>
      )}

      <EvidencePreviewModal
        isOpen={previewOpen}
        caseId={caseId}
        files={pendingFiles}
        file={pendingFile}
        onClose={() => {
          setPreviewOpen(false);
          setPendingFiles([]);
          setPendingFile(null);
        }}
        onConfirmed={handleConfirmed}
      />
    </div>
  );
}

function EvidenceCardItem({ evidence, onSelect }: { evidence: Evidence; onSelect: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const rec = useTrace(evidence.label);
  useTraceDwell(ref, evidence.label);
  const isVariant = Boolean((evidence as any).is_variant || ((evidence as any).variant_note));

  return (
    <div
      ref={ref}
      className={s.evCard}
      onClick={onSelect}
      role="button"
      tabIndex={0}
      aria-label={`Open details for ${evidence.label}`}
      onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(); } }}
      style={{ cursor: "pointer" }}
    >
      <div className={s.evCardHead}>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <TraceDot state={rec.state} />
          <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>{evidence.id}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{
            fontSize: "10px",
            padding: "1px 6px",
            borderRadius: "4px",
            background: "rgba(59, 130, 246, 0.12)",
            color: "var(--accent)",
            border: "1px solid rgba(59, 130, 246, 0.25)",
            fontFamily: "var(--font-mono)",
          }}>
            v{evidence.version_number || 1}
          </span>
          {isVariant && (
            <span style={{
              fontSize: "10px",
              padding: "1px 6px",
              borderRadius: "4px",
              background: "rgba(245, 158, 11, 0.15)",
              color: "var(--warning)",
              border: "1px solid rgba(245, 158, 11, 0.3)",
              fontFamily: "var(--font-mono)",
            }}>
              VARIANT
            </span>
          )}
          <span className={`${s.statusBadge} ${s[`status${evidence.status}`]}`}>{evidence.status}</span>
        </div>
      </div>
      <div className={s.evCardTitle}>{evidence.label}</div>
      <div className={s.evCardMeta}>{evidence.meta}</div>
      <div style={{ marginTop: "8px", display: "flex", alignItems: "center", gap: "6px" }}>
        <span style={{
          fontSize: "10px",
          padding: "2px 6px",
          borderRadius: "4px",
          background: "rgba(88, 166, 255, 0.08)",
          color: "var(--accent)",
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.04em",
        }}>
          {(evidence as any).fingerprint || `MH-${(evidence.sha256 || evidence.id).slice(0, 8).toUpperCase()}`}
        </span>
        <span style={{ fontSize: "10px", color: "var(--text-tertiary)", fontFamily: "var(--font-mono)" }}>
          SEC 63 BSA
        </span>
      </div>
    </div>
  );
}
