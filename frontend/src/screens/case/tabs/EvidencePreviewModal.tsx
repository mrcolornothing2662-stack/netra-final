/**
 * NETRA 5.0 / CyberDrishti AI — Pre-Hash Forensic Evidence Intake Modal
 *
 * Implements two-stage forensic evidence intake for single and multiple files:
 * 1. Pre-Hash Batch Preview: Stages unhashed bitstreams in quarantine enclave.
 *    Extracts magic-byte MIME validation, structure metrics, and read-only content viewports
 *    without modifying or hashing original bitstreams.
 * 2. Investigator Confirmation: Server computes canonical SHA-256 on exact staged original bytes,
 *    encrypts file, and seals Section 63 BSA chain-of-custody records independently per file.
 *    Partial failures are strictly isolated without rolling back valid evidence records.
 */
import React, { useEffect, useState, useId, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  evidenceApi,
  type EvidencePreviewResponse,
  type EvidenceConfirmResponse,
  type EvidenceConfirmBatchResponse,
  type BatchPreviewItem,
  type BatchSealedItem,
  type BatchFailedItem,
} from "../../../api/evidence";
import { Icon } from "../../../components/icons";
import { Button } from "../../../components/primitives/Button";

interface Props {
  isOpen: boolean;
  caseId: string;
  files?: File[];
  file?: File | null;
  onClose: () => void;
  onConfirmed?: (response: EvidenceConfirmResponse | EvidenceConfirmBatchResponse) => void;
  onBatchConfirmed?: (response: EvidenceConfirmBatchResponse) => void;
}

export interface FileBatchItem {
  id: string;
  file: File;
  previewId?: string;
  sourceType: string;
  status: "staging" | "staged" | "error" | "confirming" | "sealed" | "failed" | "duplicate";
  previewData?: BatchPreviewItem | EvidencePreviewResponse;
  sealedData?: BatchSealedItem;
  failedData?: BatchFailedItem;
  error?: string;
}

const SOURCE_TYPE_OPTIONS = [
  { value: "unknown", label: "Auto-detect / Generic Evidence" },
  { value: "cdr", label: "Call Detail Record (CDR / Telecom Log)" },
  { value: "whatsapp", label: "WhatsApp / Messaging Extraction" },
  { value: "bank_txn", label: "Bank Transaction Ledger (CSV / Statement)" },
  { value: "network_log", label: "Network / Firewall / Syslog Dump" },
  { value: "document_text", label: "Document / FIR / Legal Report" },
  { value: "cctv", label: "CCTV / Surveillance Frame / Image" },
  { value: "disk_dump", label: "Forensic Disk Image / Compressed Archive" },
];

function formatBytes(bytes?: number): string {
  if (bytes === undefined || bytes === null) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function inferSourceType(filename: string): string {
  const name = filename.toLowerCase();
  if (name.endsWith(".csv") || name.endsWith(".xlsx")) {
    if (name.includes("cdr") || name.includes("call")) return "cdr";
    if (name.includes("bank") || name.includes("stmt") || name.includes("ledger") || name.includes("trans")) return "bank_txn";
    return "bank_txn";
  }
  if (name.endsWith(".pdf")) return "document_text";
  if (name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".webp")) return "cctv";
  if (name.endsWith(".zip") || name.endsWith(".tar") || name.endsWith(".gz")) return "disk_dump";
  if (name.endsWith(".txt") && (name.includes("chat") || name.includes("wa") || name.includes("msg"))) return "whatsapp";
  return "unknown";
}

function getFileIcon(filename: string): string {
  const name = filename.toLowerCase();
  if (name.endsWith(".pdf")) return "file-text";
  if (name.endsWith(".csv") || name.endsWith(".xlsx")) return "table";
  if (name.endsWith(".zip") || name.endsWith(".tar") || name.endsWith(".gz")) return "archive";
  if (name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image";
  return "file";
}

export function EvidencePreviewModal({
  isOpen,
  caseId,
  files,
  file,
  onClose,
  onConfirmed,
  onBatchConfirmed,
}: Props) {
  // Mode: "batch_list" | "detail_inspect" | "result_summary"
  const [viewMode, setViewMode] = useState<"batch_list" | "detail_inspect" | "result_summary">("batch_list");
  const [activeInspectId, setActiveInspectId] = useState<string | null>(null);
  const [items, setItems] = useState<FileBatchItem[]>([]);
  const [batchResult, setBatchResult] = useState<EvidenceConfirmBatchResponse | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  const modalTitleId = useId();

  // Normalize incoming files prop
  const inputFiles = useMemo(() => {
    if (files && files.length > 0) return files;
    if (file) return [file];
    return [];
  }, [files, file]);

  // Reset or initialize state whenever modal opens or file list changes
  useEffect(() => {
    if (!isOpen || inputFiles.length === 0) {
      setItems([]);
      setBatchResult(null);
      setViewMode("batch_list");
      setActiveInspectId(null);
      setConfirming(false);
      return;
    }

    // Initialize item batch state
    const initialItems: FileBatchItem[] = inputFiles.map((f, idx) => ({
      id: `${f.name}_${f.size}_${idx}_${Date.now()}`,
      file: f,
      sourceType: inferSourceType(f.name),
      status: "staging",
    }));

    setItems(initialItems);
    setViewMode("batch_list");
    setBatchResult(null);
    setActiveInspectId(null);

    // Trigger batch staging preview on backend
    let active = true;

    evidenceApi
      .previewBatch(caseId, inputFiles)
      .then((res) => {
        if (!active) return;
        setItems((current) =>
          current.map((item, idx) => {
            const stagedMatch =
              (res.items && res.items[idx]) ||
              res.items.find((si) => si.filename === item.file.name);
            if (!stagedMatch) {
              return {
                ...item,
                status: "error",
                error: "Staging failed to return matching file metadata",
              };
            }
            if (stagedMatch.status === "error") {
              return {
                ...item,
                status: "error",
                error: stagedMatch.error || "File rejected during inspection",
                previewData: stagedMatch,
              };
            }
            return {
              ...item,
              previewId: stagedMatch.preview_id,
              status: "staged",
              previewData: stagedMatch,
            };
          })
        );
      })
      .catch((err: unknown) => {
        if (!active) return;
        const msg = err instanceof Error ? err.message : "Failed to stage evidence preview batch";
        setItems((current) =>
          current.map((item) => ({
            ...item,
            status: "error",
            error: msg,
          }))
        );
      });

    return () => {
      active = false;
    };
  }, [isOpen, inputFiles, caseId]);

  // Cancel entire batch & discard all staged files
  const handleCancelBatch = async () => {
    const stagedPreviewIds = items
      .map((it) => it.previewId)
      .filter((pid): pid is string => Boolean(pid));

    if (stagedPreviewIds.length > 0) {
      try {
        await evidenceApi.cancelBatch(caseId, stagedPreviewIds);
      } catch (e) {
        console.warn("Purge staging batch failed:", e);
      }
    }
    setItems([]);
    setBatchResult(null);
    onClose();
  };

  // Remove individual file from batch
  const handleRemoveItem = async (itemId: string) => {
    const target = items.find((i) => i.id === itemId);
    if (target?.previewId) {
      try {
        await evidenceApi.cancelPreview(caseId, target.previewId);
      } catch (e) {
        console.warn("Cancel staging for item failed:", e);
      }
    }

    const remaining = items.filter((i) => i.id !== itemId);
    setItems(remaining);

    if (activeInspectId === itemId) {
      setActiveInspectId(null);
      setViewMode("batch_list");
    }

    if (remaining.length === 0) {
      onClose();
    }
  };

  // Update source type for a specific item
  const handleUpdateSourceType = (itemId: string, newType: string) => {
    setItems((current) =>
      current.map((i) => (i.id === itemId ? { ...i, sourceType: newType } : i))
    );
  };

  // Confirm and Seal Batch
  const handleConfirmBatch = async () => {
    const stageable = items.filter((i) => i.status === "staged" && i.previewId);
    if (stageable.length === 0) return;

    setConfirming(true);
    setItems((current) =>
      current.map((i) =>
        i.status === "staged" ? { ...i, status: "confirming" } : i
      )
    );

    const payload = stageable.map((i) => ({
      preview_id: i.previewId!,
      source_type: i.sourceType,
      original_name: i.file.name,
    }));

    try {
      const res = await evidenceApi.confirmBatch(caseId, payload);
      setBatchResult(res);

      // Update per-item status from batch results
      setItems((current) =>
        current.map((i) => {
          const sealedMatch = res.sealed.find(
            (s) => s.preview_id === i.previewId || s.filename === i.file.name
          );
          if (sealedMatch) {
            return { ...i, status: "sealed", sealedData: sealedMatch };
          }
          const dupMatch = res.duplicates.find(
            (d) => d.preview_id === i.previewId || d.filename === i.file.name
          );
          if (dupMatch) {
            return { ...i, status: "duplicate", sealedData: dupMatch };
          }
          const failMatch = res.failed.find(
            (f) => f.preview_id === i.previewId || f.filename === i.file.name
          );
          if (failMatch) {
            return { ...i, status: "failed", failedData: failMatch, error: failMatch.error };
          }
          return i;
        })
      );

      setViewMode("result_summary");
      if (onBatchConfirmed) onBatchConfirmed(res);
      else if (onConfirmed) onConfirmed(res);
    } catch (err: unknown) {
      // Rather than assuming outright failure on network timeout, check if server actually sealed the evidence
      try {
        const liveFiles = await evidenceApi.list(caseId);
        const stageableNames = new Set(stageable.map((s) => s.file.name));
        const matchedSealed = liveFiles.filter((lf) => stageableNames.has(lf.original_name));
        if (matchedSealed.length > 0) {
          setItems((current) =>
            current.map((i) => {
              const lf = matchedSealed.find((m) => m.original_name === i.file.name);
              if (lf) {
                return {
                  ...i,
                  status: "sealed",
                  sealedData: {
                    id: lf.id,
                    filename: lf.original_name,
                    sha256_hash: lf.sha256_hash,
                    file_size_bytes: lf.file_size_bytes,
                  },
                };
              }
              return i;
            })
          );
          setViewMode("result_summary");
          return;
        }
      } catch {
        // Fall back to displaying actionable error
      }

      const msg = err instanceof Error ? err.message : "Upload result could not be confirmed. Checking server status...";
      setItems((current) =>
        current.map((i) =>
          i.status === "confirming" ? { ...i, status: "failed", error: msg } : i
        )
      );
    } finally {
      setConfirming(false);
    }
  };

  // Copy SHA-256 hash helper
  const handleCopyHash = (hash: string) => {
    navigator.clipboard.writeText(hash);
    setCopiedHash(hash);
    setTimeout(() => setCopiedHash(null), 2500);
  };

  if (!isOpen) return null;

  const activeItem = items.find((i) => i.id === activeInspectId);
  const isAllStaged = items.length > 0 && items.every((i) => i.status === "staged" || i.status === "error");
  const hasStagedFiles = items.some((i) => i.status === "staged");

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 1050,
          background: "rgba(5, 7, 10, 0.84)",
          backdropFilter: "blur(6px)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "var(--space-4)",
        }}
        onClick={handleCancelBatch}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.96, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.96, y: 12 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby={modalTitleId}
          style={{
            background: "var(--surface-1)",
            border: "1px solid var(--line-strong)",
            borderRadius: "var(--radius-card)",
            width: "100%",
            maxWidth: viewMode === "detail_inspect" ? 860 : 820,
            maxHeight: "92vh",
            display: "flex",
            flexDirection: "column",
            boxShadow: "0 24px 48px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.05)",
            overflow: "hidden",
          }}
        >
          {/* Header */}
          <div
            style={{
              padding: "16px 22px",
              borderBottom: "1px solid var(--line)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              background: "linear-gradient(180deg, rgba(255,255,255,0.03) 0%, transparent 100%)",
            }}
          >
            <div>
              <div
                style={{
                  font: "var(--type-mono-xs)",
                  color: "var(--accent)",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 4,
                }}
              >
                <span>CYBERDRISHTI // EVIDENCE INTAKE ENCLAVE</span>
                <span>·</span>
                <span>SEC 63 BSA PRE-FLIGHT BATCH</span>
              </div>
              <h2
                id={modalTitleId}
                style={{
                  font: "var(--type-title-3)",
                  color: "var(--text-primary)",
                  margin: 0,
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                {viewMode === "result_summary" ? (
                  <>
                    <span style={{ color: "var(--verified)" }}>✓</span>
                    <span>Batch Evidence Processing Complete</span>
                  </>
                ) : viewMode === "detail_inspect" ? (
                  <>
                    <button
                      onClick={() => setViewMode("batch_list")}
                      style={{
                        background: "var(--surface-2)",
                        border: "1px solid var(--line)",
                        borderRadius: "4px",
                        padding: "4px 8px",
                        color: "var(--accent)",
                        cursor: "pointer",
                        font: "var(--type-mono-xs)",
                        display: "flex",
                        alignItems: "center",
                        gap: 4,
                      }}
                    >
                      ← Back to Batch
                    </button>
                    <span>Evidence Preview: {activeItem?.file.name}</span>
                  </>
                ) : (
                  <>
                    <span>Evidence Review</span>
                    <span
                      style={{
                        font: "var(--type-mono-xs)",
                        padding: "2px 8px",
                        borderRadius: "4px",
                        background: "rgba(88, 166, 255, 0.12)",
                        color: "var(--accent)",
                        border: "1px solid rgba(88, 166, 255, 0.25)",
                      }}
                    >
                      {items.length} {items.length === 1 ? "file" : "files"}
                    </span>
                    <span
                      style={{
                        font: "var(--type-mono-xs)",
                        padding: "2px 8px",
                        borderRadius: "4px",
                        background: "rgba(245, 158, 11, 0.15)",
                        color: "var(--warning)",
                        border: "1px solid rgba(245, 158, 11, 0.35)",
                        letterSpacing: "0.04em",
                      }}
                    >
                      ⚠ UNSEALED · PRE-HASH
                    </span>
                  </>
                )}
              </h2>
            </div>
            <button
              onClick={handleCancelBatch}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-muted)",
                cursor: "pointer",
                padding: "6px",
                borderRadius: "4px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
              aria-label="Close modal"
            >
              <Icon name="close" size={18} />
            </button>
          </div>

          {/* Modal Body */}
          <div
            style={{
              padding: "20px 24px",
              overflowY: "auto",
              flex: 1,
              display: "flex",
              flexDirection: "column",
              gap: "18px",
            }}
          >
            {/* VIEW MODE 1: BATCH REVIEW LIST */}
            {viewMode === "batch_list" && (
              <>
                {/* Warning Banner */}
                <div
                  style={{
                    padding: "12px 16px",
                    background: "rgba(245, 158, 11, 0.08)",
                    border: "1px solid rgba(245, 158, 11, 0.3)",
                    borderRadius: "var(--radius-card)",
                    display: "flex",
                    gap: 12,
                    alignItems: "flex-start",
                  }}
                  role="status"
                >
                  <span style={{ color: "var(--warning)", fontSize: 18, lineHeight: 1 }}>⚠</span>
                  <div style={{ flex: 1 }}>
                    <div
                      style={{
                        font: "var(--type-mono-xs)",
                        color: "var(--warning)",
                        fontWeight: 600,
                        letterSpacing: "0.04em",
                        marginBottom: 2,
                      }}
                    >
                      STATUS: PRE-HASH BATCH PREVIEW — Evidence has not yet been fingerprinted.
                    </div>
                    <div style={{ font: "var(--type-body-xs)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
                      Review files below before cryptographic sealing. Clicking <strong>Preview</strong> allows read-only inspection without modifying or hashing bytes.
                      Upon confirmation, NETRA computes canonical SHA-256 for each file independently.
                    </div>
                  </div>
                </div>

                {/* Batch File Table */}
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                    maxHeight: "420px",
                    overflowY: "auto",
                  }}
                >
                  {items.map((item) => (
                    <div
                      key={item.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        padding: "12px 16px",
                        background: "var(--surface-0)",
                        border: "1px solid var(--line)",
                        borderRadius: "var(--radius-sm)",
                        gap: 12,
                      }}
                    >
                      {/* Left: Icon, Name, Type, Size */}
                      <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0, flex: 1 }}>
                        <div
                          style={{
                            width: 34,
                            height: 34,
                            borderRadius: "6px",
                            background: "rgba(255,255,255,0.04)",
                            border: "1px solid var(--line)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            fontSize: 16,
                            color: "var(--accent)",
                            flexShrink: 0,
                          }}
                        >
                          📄
                        </div>
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div
                            style={{
                              font: "var(--type-body-sm)",
                              color: "var(--text-primary)",
                              fontWeight: 500,
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                            title={item.file.name}
                          >
                            {item.file.name}
                          </div>
                          <div
                            style={{
                              font: "var(--type-mono-xs)",
                              color: "var(--text-muted)",
                              display: "flex",
                              gap: 8,
                              marginTop: 2,
                            }}
                          >
                            <span>{formatBytes(item.file.size)}</span>
                            <span>·</span>
                            <span style={{ color: "var(--text-secondary)", textTransform: "uppercase" }}>
                              {item.previewData?.mime_type || item.file.type || "FILE"}
                            </span>
                            {item.previewData?.metadata?.page_count !== undefined && (
                              <>
                                <span>·</span>
                                <span>{item.previewData.metadata.page_count} page(s)</span>
                              </>
                            )}
                            {item.previewData?.metadata?.row_count !== undefined && (
                              <>
                                <span>·</span>
                                <span>~{item.previewData.metadata.row_count} row(s)</span>
                              </>
                            )}
                            {item.previewData?.metadata?.member_count !== undefined && (
                              <>
                                <span>·</span>
                                <span>{item.previewData.metadata.member_count} archive members</span>
                              </>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Middle: Source Modality Dropdown */}
                      <div style={{ width: 180, flexShrink: 0 }}>
                        <select
                          value={item.sourceType}
                          onChange={(e) => handleUpdateSourceType(item.id, e.target.value)}
                          style={{
                            width: "100%",
                            padding: "6px 10px",
                            background: "var(--surface-2)",
                            border: "1px solid var(--line)",
                            borderRadius: "4px",
                            color: "var(--text-primary)",
                            font: "var(--type-mono-xs)",
                            outline: "none",
                          }}
                          aria-label={`Source type for ${item.file.name}`}
                        >
                          {SOURCE_TYPE_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </div>

                      {/* Right: Status & Actions */}
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                        {item.status === "staging" ? (
                          <span style={{ font: "var(--type-mono-xs)", color: "var(--accent)" }}>
                            Staging…
                          </span>
                        ) : item.status === "error" ? (
                          <span style={{ font: "var(--type-mono-xs)", color: "var(--critical)" }} title={item.error}>
                            Rejected
                          </span>
                        ) : (
                          <span style={{ font: "var(--type-mono-xs)", color: "var(--verified)" }}>
                            ✓ Pre-Flight OK
                          </span>
                        )}

                        <Button
                          variant="secondary"
                          onClick={() => {
                            setActiveInspectId(item.id);
                            setViewMode("detail_inspect");
                          }}
                          disabled={item.status === "staging" || !item.previewData}
                        >
                          Preview
                        </Button>

                        <button
                          onClick={() => handleRemoveItem(item.id)}
                          style={{
                            background: "transparent",
                            border: "1px solid var(--line)",
                            borderRadius: "4px",
                            color: "var(--text-muted)",
                            cursor: "pointer",
                            padding: "5px 8px",
                            font: "var(--type-mono-xs)",
                            transition: "all 0.15s ease",
                          }}
                          title="Remove from batch"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* VIEW MODE 2: INDIVIDUAL DETAIL INSPECTION */}
            {viewMode === "detail_inspect" && activeItem && activeItem.previewData && (
              <>
                {/* Warning Banner */}
                <div
                  style={{
                    padding: "10px 14px",
                    background: "rgba(245, 158, 11, 0.08)",
                    border: "1px solid rgba(245, 158, 11, 0.3)",
                    borderRadius: "var(--radius-card)",
                    display: "flex",
                    gap: 10,
                    alignItems: "center",
                  }}
                  role="status"
                >
                  <span style={{ color: "var(--warning)", fontSize: 16 }}>⚠</span>
                  <div style={{ font: "var(--type-mono-xs)", color: "var(--warning)" }}>
                    STATUS: PRE-HASH PREVIEW — This evidence has not been fingerprinted yet. Read-only inspection enclaved.
                  </div>
                </div>

                {/* Metadata Details */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                    gap: 10,
                  }}
                >
                  <div style={{ background: "var(--surface-0)", border: "1px solid var(--line)", padding: "8px 12px", borderRadius: "4px" }}>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", display: "block", textTransform: "uppercase" }}>
                      Filename
                    </span>
                    <span style={{ font: "var(--type-body-sm)", color: "var(--text-primary)", fontWeight: 500, wordBreak: "break-all" }}>
                      {activeItem.file.name}
                    </span>
                  </div>

                  <div style={{ background: "var(--surface-0)", border: "1px solid var(--line)", padding: "8px 12px", borderRadius: "4px" }}>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", display: "block", textTransform: "uppercase" }}>
                      Detected MIME
                    </span>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--verified)" }}>
                      {activeItem.previewData.mime_type} ✓
                    </span>
                  </div>

                  <div style={{ background: "var(--surface-0)", border: "1px solid var(--line)", padding: "8px 12px", borderRadius: "4px" }}>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", display: "block", textTransform: "uppercase" }}>
                      Size
                    </span>
                    <span style={{ font: "var(--type-body-sm)", color: "var(--text-primary)" }}>
                      {formatBytes(activeItem.file.size)}
                    </span>
                  </div>

                  <div style={{ background: "var(--surface-0)", border: "1px solid var(--line)", padding: "8px 12px", borderRadius: "4px" }}>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", display: "block", textTransform: "uppercase" }}>
                      Source Modality
                    </span>
                    <select
                      value={activeItem.sourceType}
                      onChange={(e) => handleUpdateSourceType(activeItem.id, e.target.value)}
                      style={{
                        width: "100%",
                        background: "transparent",
                        border: "none",
                        color: "var(--accent)",
                        font: "var(--type-body-sm)",
                        fontWeight: 500,
                        outline: "none",
                        cursor: "pointer",
                      }}
                    >
                      {SOURCE_TYPE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value} style={{ background: "var(--surface-1)", color: "var(--text-primary)" }}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Viewport Renderers */}
                <div
                  style={{
                    background: "var(--surface-0)",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius-card)",
                    overflow: "hidden",
                    display: "flex",
                    flexDirection: "column",
                  }}
                >
                  <div
                    style={{
                      padding: "8px 14px",
                      background: "var(--surface-2)",
                      borderBottom: "1px solid var(--line)",
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                    }}
                  >
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-secondary)", textTransform: "uppercase" }}>
                      Read-Only Content Inspection
                    </span>
                    <span style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                      Zero Mutation · Staging Enclave
                    </span>
                  </div>

                  {/* CSV / Tabular Viewport */}
                  {activeItem.previewData.metadata.column_names && activeItem.previewData.metadata.sample_rows && (
                    <div style={{ overflowX: "auto", maxHeight: "280px" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", font: "var(--type-mono-xs)", textAlign: "left" }}>
                        <thead>
                          <tr style={{ background: "rgba(255,255,255,0.03)", borderBottom: "1px solid var(--line)" }}>
                            <th style={{ padding: "8px 12px", color: "var(--text-muted)", width: 40 }}>#</th>
                            {activeItem.previewData.metadata.column_names.map((col, idx) => (
                              <th
                                key={idx}
                                style={{
                                  padding: "8px 12px",
                                  color: "var(--accent)",
                                  fontWeight: 600,
                                  borderRight: "1px solid var(--line)",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                {col}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {activeItem.previewData.metadata.sample_rows.map((row, rIdx) => (
                            <tr
                              key={rIdx}
                              style={{
                                borderBottom: "1px solid var(--line)",
                                background: rIdx % 2 === 0 ? "transparent" : "rgba(255,255,255,0.01)",
                              }}
                            >
                              <td style={{ padding: "6px 12px", color: "var(--text-muted)" }}>{rIdx + 1}</td>
                              {activeItem.previewData!.metadata.column_names!.map((col, cIdx) => (
                                <td
                                  key={cIdx}
                                  style={{
                                    padding: "6px 12px",
                                    color: "var(--text-secondary)",
                                    borderRight: "1px solid var(--line)",
                                    whiteSpace: "nowrap",
                                    maxWidth: 220,
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                  }}
                                  title={row[col]}
                                >
                                  {row[col] ?? ""}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* Image Thumbnail Viewport */}
                  {activeItem.previewData.metadata.thumbnail_data_url && (
                    <div style={{ padding: "20px", display: "flex", justifyContent: "center", alignItems: "center", background: "rgba(0,0,0,0.3)" }}>
                      <div style={{ border: "1px solid var(--line-strong)", borderRadius: "4px", overflow: "hidden", maxHeight: 260, maxWidth: "100%" }}>
                        <img
                          src={activeItem.previewData.metadata.thumbnail_data_url}
                          alt={activeItem.file.name}
                          style={{ maxWidth: "100%", maxHeight: 260, display: "block", objectFit: "contain" }}
                        />
                      </div>
                    </div>
                  )}

                  {/* PDF / Text Snippet Viewport */}
                  {activeItem.previewData.metadata.text_snippet && !activeItem.previewData.metadata.column_names && (
                    <div style={{ padding: "14px 16px", maxHeight: "260px", overflowY: "auto" }}>
                      <pre style={{ font: "var(--type-mono-xs)", color: "var(--text-primary)", margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all", lineHeight: 1.5 }}>
                        {activeItem.previewData.metadata.text_snippet}
                      </pre>
                    </div>
                  )}

                  {/* Archive / ZIP Member Listing */}
                  {activeItem.previewData.metadata.members && (
                    <div style={{ padding: "12px 16px", maxHeight: "240px", overflowY: "auto" }}>
                      <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", marginBottom: 8 }}>
                        Archive Member Manifest ({activeItem.previewData.metadata.member_count} entries):
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {activeItem.previewData.metadata.members.map((m, idx) => (
                          <div
                            key={idx}
                            style={{
                              font: "var(--type-mono-xs)",
                              color: "var(--text-secondary)",
                              padding: "4px 8px",
                              background: "rgba(255,255,255,0.02)",
                              borderRadius: "4px",
                              border: "1px solid var(--line)",
                              display: "flex",
                              alignItems: "center",
                              gap: 8,
                            }}
                          >
                            <span style={{ color: "var(--text-muted)" }}>📄</span>
                            <span>{m}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </>
            )}

            {/* VIEW MODE 3: BATCH CONFIRMATION RESULTS */}
            {viewMode === "result_summary" && batchResult && (
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {/* Result Header Card */}
                <div
                  style={{
                    padding: "16px",
                    background: "rgba(16, 185, 129, 0.05)",
                    border: "1px solid rgba(16, 185, 129, 0.25)",
                    borderRadius: "var(--radius-card)",
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                  }}
                >
                  <div
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: "50%",
                      background: "rgba(16, 185, 129, 0.15)",
                      color: "var(--verified)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 22,
                      fontWeight: "bold",
                    }}
                  >
                    ✓
                  </div>
                  <div>
                    <div style={{ font: "var(--type-title-3)", color: "var(--text-primary)" }}>
                      Batch Cryptographic Intake Completed
                    </div>
                    <div style={{ font: "var(--type-mono-xs)", color: "var(--verified)", letterSpacing: "0.04em", marginTop: 2 }}>
                      {batchResult.sealed_count} evidence file(s) sealed into Section 63 BSA custody
                      {batchResult.duplicate_count > 0 && ` · ${batchResult.duplicate_count} duplicate(s) detected`}
                      {batchResult.failed_count > 0 && ` · ${batchResult.failed_count} file(s) failed`}
                    </div>
                  </div>
                </div>

                {/* Sealed Files List */}
                {batchResult.sealed.length > 0 && (
                  <div>
                    <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)", textTransform: "uppercase", marginBottom: 8 }}>
                      Sealed Evidence Items ({batchResult.sealed.length})
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: "200px", overflowY: "auto" }}>
                      {batchResult.sealed.map((sFile, idx) => (
                        <div
                          key={sFile.id || idx}
                          style={{
                            padding: "10px 14px",
                            background: "var(--surface-0)",
                            border: "1px solid var(--line)",
                            borderRadius: "var(--radius-sm)",
                            display: "flex",
                            flexDirection: "column",
                            gap: 4,
                          }}
                        >
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                            <span style={{ font: "var(--type-body-sm)", color: "var(--text-primary)", fontWeight: 500 }}>
                              ✓ {sFile.filename}
                            </span>
                            <button
                              onClick={() => handleCopyHash(sFile.sha256_hash)}
                              style={{
                                background: "var(--surface-2)",
                                border: "1px solid var(--line)",
                                borderRadius: "4px",
                                padding: "2px 8px",
                                color: copiedHash === sFile.sha256_hash ? "var(--verified)" : "var(--text-secondary)",
                                font: "var(--type-mono-xs)",
                                cursor: "pointer",
                              }}
                            >
                              {copiedHash === sFile.sha256_hash ? "Copied ✓" : "Copy Hash"}
                            </button>
                          </div>
                          <code style={{ font: "var(--type-mono-xs)", color: "var(--accent)", wordBreak: "break-all" }}>
                            SHA-256: {sFile.sha256_hash}
                          </code>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Duplicate Files List */}
                {batchResult.duplicates.length > 0 && (
                  <div>
                    <div style={{ font: "var(--type-mono-xs)", color: "var(--warning)", textTransform: "uppercase", marginBottom: 8 }}>
                      Duplicate Files Detected ({batchResult.duplicates.length})
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {batchResult.duplicates.map((dFile, idx) => (
                        <div
                          key={dFile.id || idx}
                          style={{
                            padding: "8px 12px",
                            background: "rgba(245, 158, 11, 0.05)",
                            border: "1px solid rgba(245, 158, 11, 0.2)",
                            borderRadius: "4px",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                          }}
                        >
                          <span style={{ font: "var(--type-body-xs)", color: "var(--text-primary)" }}>
                            ⚠ {dFile.filename} (Identical bitstream already in custody)
                          </span>
                          <code style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                            {dFile.sha256_hash.slice(0, 16)}…
                          </code>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Failed Files List */}
                {batchResult.failed.length > 0 && (
                  <div>
                    <div style={{ font: "var(--type-mono-xs)", color: "var(--critical)", textTransform: "uppercase", marginBottom: 8 }}>
                      Failed Ingestion Files ({batchResult.failed.length})
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {batchResult.failed.map((fFile, idx) => (
                        <div
                          key={idx}
                          style={{
                            padding: "8px 12px",
                            background: "rgba(239, 68, 68, 0.08)",
                            border: "1px solid rgba(239, 68, 68, 0.25)",
                            borderRadius: "4px",
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                          }}
                        >
                          <div>
                            <span style={{ font: "var(--type-body-xs)", color: "var(--critical)", fontWeight: 500 }}>
                              ✗ {fFile.filename}
                            </span>
                            <div style={{ font: "var(--type-mono-xs)", color: "var(--text-muted)" }}>
                              {fFile.error}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer Actions */}
          <div
            style={{
              padding: "16px 24px",
              borderTop: "1px solid var(--line)",
              background: "var(--surface-0)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            {viewMode === "result_summary" ? (
              <div style={{ width: "100%", display: "flex", justifyContent: "flex-end" }}>
                <Button variant="primary" onClick={handleCancelBatch}>
                  Close & View in Evidence Locker
                </Button>
              </div>
            ) : viewMode === "detail_inspect" ? (
              <>
                <Button variant="secondary" onClick={() => setViewMode("batch_list")}>
                  ← Back to Batch
                </Button>
                {activeItem && (
                  <button
                    onClick={() => handleRemoveItem(activeItem.id)}
                    style={{
                      background: "rgba(239, 68, 68, 0.1)",
                      border: "1px solid rgba(239, 68, 68, 0.3)",
                      borderRadius: "4px",
                      color: "var(--critical)",
                      cursor: "pointer",
                      padding: "8px 14px",
                      font: "var(--type-body-sm)",
                    }}
                  >
                    Remove Evidence
                  </button>
                )}
              </>
            ) : (
              <>
                <Button variant="secondary" onClick={handleCancelBatch} disabled={confirming}>
                  Cancel Batch
                </Button>
                <Button
                  variant="primary"
                  onClick={handleConfirmBatch}
                  disabled={!hasStagedFiles || confirming || !isAllStaged}
                >
                  {confirming
                    ? "Computing SHA-256 & Sealing…"
                    : `Confirm & Hash All (${items.filter((i) => i.status === "staged").length} files)`}
                </Button>
              </>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
