import type { BackendEvidenceFile } from "../api/evidence";
import type { Evidence, EvidenceKind, EvidenceStatus } from "../data/types";

function inferKind(filename?: string | null, fileType?: string, sourceType?: string): EvidenceKind {
  const safeName = filename || "";
  const ext = safeName.includes(".") ? safeName.split(".").pop()?.toLowerCase() || "" : "";
  if (["png", "jpg", "jpeg", "webp", "tiff", "bmp"].includes(ext) || fileType === "image") {
    return "IMAGE";
  }
  if (["txt", "chat"].includes(ext) || sourceType?.includes("whatsapp") || sourceType?.includes("chat")) {
    return "COMMS";
  }
  if (["csv", "xlsx", "json", "log"].includes(ext) || sourceType?.includes("cdr") || fileType === "csv") {
    return "DATA";
  }
  return "DOC";
}

function normalizeStatus(s?: string | null): EvidenceStatus {
  if (!s) return "VERIFIED";
  const lower = s.toLowerCase();
  if (lower === "processed") return "ANALYZED";
  if (lower === "processing" || lower === "pending") return "PROCESSING";
  if (lower === "failed") return "UNVERIFIED";
  return "VERIFIED";
}

function formatMeta(ev: BackendEvidenceFile): string {
  const parts: string[] = [];
  const rawEv = ev as Record<string, any>;
  const sourceType = ev.source_type || rawEv.sourceType;
  const fileType = ev.file_type || rawEv.fileType;
  const fileSize = ev.file_size ?? rawEv.file_size_bytes ?? rawEv.fileSizeBytes;

  if (sourceType && sourceType !== "unknown") {
    parts.push(String(sourceType).replace(/_/g, " ").toUpperCase());
  } else if (fileType) {
    parts.push(String(fileType).toUpperCase());
  }

  if (typeof fileSize === "number" && fileSize > 0) {
    const kb = Math.round(fileSize / 1024);
    parts.push(kb > 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb} KB`);
  }

  const uploadedAt = ev.uploaded_at || rawEv.uploadedAt;
  if (uploadedAt) {
    try {
      const d = new Date(uploadedAt);
      if (!isNaN(d.getTime())) {
        parts.push(d.toLocaleDateString(undefined, { month: "short", day: "numeric" }));
      }
    } catch {
      // ignore
    }
  }

  return parts.join(" · ") || "Evidence record";
}

export function adaptEvidenceFile(ev: BackendEvidenceFile): Evidence {
  const rawEv = ev as Record<string, any>;
  const fileName = ev.original_name || rawEv.filename || rawEv.name || "Evidence file";
  const hash = ev.sha256_hash || rawEv.sha256 || rawEv.hash || "";
  const uploadedAt = ev.uploaded_at || rawEv.uploadedAt;

  return {
    id: String(ev.id || rawEv._id || `ev-${Math.random().toString(36).slice(2, 7)}`),
    label: fileName,
    kind: inferKind(fileName, ev.file_type || rawEv.fileType, ev.source_type || rawEv.sourceType),
    meta: formatMeta(ev),
    status: normalizeStatus(ev.upload_status || rawEv.status),
    sha256: hash,
    notes: ev.parse_error
      ? `Note: ${ev.parse_error}`
      : hash
      ? `SHA-256 Verified: ${hash.slice(0, 16)}…`
      : "Cryptographic custody logged.",
    addedAt: uploadedAt ? new Date(uploadedAt).getTime() : Date.now(),
    user: false,
    parent_evidence_id: ev.parent_evidence_id || rawEv.parent_evidence_id || null,
    version_number: ev.version_number ?? rawEv.version_number ?? 1,
    version_status: ev.version_status || rawEv.version_status || "original",
    fingerprint_hash: ev.fingerprint || rawEv.fingerprint || null,
    variant_details: ev.variant_details || rawEv.variant_details || {},
    is_variant: Boolean(ev.is_variant || rawEv.is_variant || (ev.version_status === "variant") || (ev.parse_error && ev.parse_error.startsWith("[VARIANT]"))),
    variant_note: ev.variant_note || rawEv.variant_note || (ev.parse_error && ev.parse_error.startsWith("[VARIANT]") ? ev.parse_error : null),
  };
}
