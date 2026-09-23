import { apiClient } from "./client";

export type ReportType = "intelligence_brief" | "formal_dossier";
export type ReportLifecycleStatus = "DRAFT" | "REVIEW" | "READY_FOR_EXPORT" | "APPROVED" | "EXPORTED" | "REJECTED";

export interface EvidenceCitation {
  evidence_id: string;
  file_name: string;
  sha256_hash: string;
  source_page?: number;
  source_line?: number;
  event_id?: string;
  citation_label: string;
  source_type?: string;
}

export interface ReportClaim {
  claim_id: string;
  text: string;
  claim_type: string;
  epistemic_status: string;
  confidence_status: string;
  entity_refs: string[];
  relationship_refs: string[];
  event_refs: string[];
  finding_refs: string[];
  evidence_refs: EvidenceCitation[];
  limitations: string[];
  generated_from: string;
  provenance_status: "VERIFIED" | "REVIEW_REQUIRED" | "UNLINKED";
  provenance_chain?: {
    trace_steps?: string[];
    warnings?: string[];
    finding_ref?: any;
    relationship_ref?: any;
  };
}

export interface ReportSection {
  section_id: string;
  title: string;
  order: number;
  summary?: string;
  claims: ReportClaim[];
  data: Record<string, any>;
  limitations: string[];
}

export interface ReportSnapshotMetadata {
  report_id: string;
  case_id: string;
  case_number: string;
  case_title: string;
  report_type: ReportType;
  status: ReportLifecycleStatus;
  case_state_version: number;
  template_version: string;
  content_hash: string;
  title: string;
  summary?: string;
  generated_by?: string;
  generated_at: string;
  approved_by?: string;
  approved_at?: string;
  rejection_reason?: string;
  claims_count: number;
  linked_claims_count: number;
  review_required_claims_count: number;
}

export interface ReportPayload {
  metadata: ReportSnapshotMetadata;
  sections: ReportSection[];
  statutory_provisions: Record<string, string>;
  provenance_summary: {
    total_claims: number;
    verified_claims: number;
    review_required_claims: number;
    verified_percentage: number;
    has_warnings: boolean;
  };
}

export interface EvidenceUsage {
  evidence_id: string;
  case_id: string;
  filename: string;
  sha256_hash: string;
  file_size_bytes?: number;
  upload_status: string;
  findings: Array<{ id: string; title: string; severity: string; freshness_status: string }>;
  claims: Array<{ claim_id: string; text: string; report_type: string; report_id: string }>;
  relationships: Array<{ id: string; rel_type: string; source_name: string; target_name: string; status: string }>;
  total_usages: number;
}

export const reportsApi = {
  generateReport: async (
    caseId: string,
    req: { report_type: ReportType; title?: string; section_keys?: string[] }
  ): Promise<ReportPayload> => {
    return apiClient.post<ReportPayload>(`/cases/${caseId}/reports/generate`, req);
  },

  listSnapshots: async (caseId: string): Promise<ReportSnapshotMetadata[]> => {
    return apiClient.get<ReportSnapshotMetadata[]>(`/cases/${caseId}/reports/snapshots`);
  },

  getSnapshot: async (caseId: string, snapshotId: string): Promise<ReportPayload> => {
    return apiClient.get<ReportPayload>(`/cases/${caseId}/reports/snapshots/${snapshotId}`);
  },

  submitForReview: async (caseId: string, snapshotId: string): Promise<{ status: string; new_status: string }> => {
    return apiClient.post(`/cases/${caseId}/reports/snapshots/${snapshotId}/submit-review`, {});
  },

  reviewSnapshot: async (
    caseId: string,
    snapshotId: string,
    body: { action: "APPROVE" | "REJECT"; rejection_reason?: string }
  ): Promise<{ status: string; new_status: string; approved_by?: string; approved_at?: string }> => {
    return apiClient.post(`/cases/${caseId}/reports/snapshots/${snapshotId}/review`, body);
  },

  exportSnapshot: async (
    caseId: string,
    snapshotId: string,
    format: "json" | "markdown" | "html" | "pdf" = "json"
  ): Promise<any> => {
    if (format === "markdown" || format === "html") {
      const blob = await apiClient.getBlob(`/cases/${caseId}/reports/snapshots/${snapshotId}/export?export_format=${format}`);
      const text = await blob.text();
      return text;
    }
    return apiClient.post(`/cases/${caseId}/reports/snapshots/${snapshotId}/export?export_format=${format}`, {});
  },

  getEvidenceUsage: async (caseId: string, evidenceId: string): Promise<EvidenceUsage> => {
    return apiClient.get<EvidenceUsage>(`/cases/${caseId}/reports/evidence/${evidenceId}/usage`);
  },

  downloadPdf: async (caseId: string, caseNumber = "case"): Promise<void> => {
    const blob = await apiClient.getBlob(`/report/${caseId}`);
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `65B_Certificate_${caseNumber}.pdf`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  },
};
