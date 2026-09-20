import { apiClient } from "./client";

export interface BackendEvidenceFile {
  id: string;
  case_id: string;
  original_name: string;
  file_type?: string;
  source_type?: string;
  sha256_hash: string;
  upload_status: "pending" | "processing" | "processed" | "failed";
  storage_path?: string;
  file_size?: number;
  file_size_bytes?: number;
  uploaded_at: string;
  processed_at?: string;
  parse_error?: string;
  parent_evidence_id?: string | null;
  version_number?: number;
  version_status?: string;
  fingerprint?: string;
  variant_details?: Record<string, any>;
  is_variant?: boolean;
  variant_note?: string | null;
  metadata?: Record<string, unknown>;
}

export interface EvidenceListResponse {
  case_id: string;
  count: number;
  files: BackendEvidenceFile[];
}

export interface EvidenceUploadResponse {
  message: string;
  uploaded: Array<{
    id: string;
    filename: string;
    sha256_hash: string;
    status: string;
  }>;
  duplicates?: Array<{
    id: string;
    filename: string;
    sha256_hash: string;
  }>;
}

export interface VersionLineage {
  root_id: string;
  root_filename: string;
  source_type?: string;
  has_variants: boolean;
  total_versions: number;
  versions: Array<{
    id: string;
    filename: string;
    file_type?: string;
    source_type?: string;
    file_size_bytes?: number;
    sha256_hash: string;
    version_number: number;
    version_status: string;
    parent_evidence_id?: string | null;
    uploaded_at?: string | null;
    processed_at?: string | null;
    fingerprint_hash?: string;
    variant_details?: Record<string, any>;
  }>;
}

export interface VersionTimelineResponse {
  case_id: string;
  total_files: number;
  variant_count: number;
  lineage_count: number;
  lineages: VersionLineage[];
}

export interface EvidencePreviewMetadata {
  file_type: string;
  line_count?: number;
  text_snippet?: string;
  page_count?: number;
  pdf_metadata?: Record<string, any>;
  column_names?: string[];
  sample_rows?: Array<Record<string, string>>;
  row_count?: number;
  dimensions?: [number, number];
  thumbnail_data_url?: string;
  member_count?: number;
  members?: string[];
  error?: string;
}

export interface EvidencePreviewResponse {
  preview_id: string;
  filename: string;
  mime_type: string;
  file_size: number;
  status: "unhashed_preview";
  warning: string;
  metadata: EvidencePreviewMetadata;
}

export interface EvidenceConfirmResponse {
  status: "sealed";
  message: string;
  id: string | null;
  filename: string;
  sha256_hash: string | null;
  uploaded_count: number;
  duplicate_count: number;
  files: Array<{ id: string; filename: string; sha256_hash: string }>;
  duplicates: Array<{ id: string; filename: string; sha256_hash: string }>;
}

export interface BatchPreviewItem extends Omit<EvidencePreviewResponse, "status"> {
  status: "unhashed_preview" | "error" | string;
  error?: string;
  source_type?: string;
}

export interface BatchPreviewResponse {
  case_id: string;
  total: number;
  items: BatchPreviewItem[];
}

export interface BatchSealedItem {
  id: string;
  filename: string;
  sha256_hash: string;
  file_size_bytes?: number;
  preview_id?: string;
}

export interface BatchFailedItem {
  preview_id?: string | null;
  filename: string;
  error: string;
}

export interface EvidenceConfirmBatchResponse {
  status: string;
  message: string;
  sealed_count: number;
  duplicate_count: number;
  failed_count: number;
  sealed: BatchSealedItem[];
  duplicates: BatchSealedItem[];
  failed: BatchFailedItem[];
}

export const evidenceApi = {
  list: async (caseId: string): Promise<BackendEvidenceFile[]> => {
    const res = await apiClient.get<EvidenceListResponse | BackendEvidenceFile[]>(`/evidence/${caseId}`);
    if (Array.isArray(res)) return res;
    return res.files || [];
  },

  versionTimeline: async (caseId: string): Promise<VersionTimelineResponse> => {
    return apiClient.get<VersionTimelineResponse>(`/evidence/${caseId}/version-timeline`);
  },

  upload: async (caseId: string, files: File[], sourceType = "unknown"): Promise<EvidenceUploadResponse> => {
    const fd = new FormData();
    fd.append("case_id", caseId);
    fd.append("source_type", sourceType);
    files.forEach((f) => fd.append("files", f));
    return apiClient.postForm<EvidenceUploadResponse>("/evidence/upload", fd);
  },

  preview: async (caseId: string, file: File, sourceType = "unknown"): Promise<EvidencePreviewResponse> => {
    const fd = new FormData();
    fd.append("case_id", caseId);
    fd.append("source_type", sourceType);
    fd.append("file", file);
    return apiClient.postForm<EvidencePreviewResponse>("/evidence/preview", fd);
  },

  previewBatch: async (caseId: string, files: File[], sourceType = "unknown"): Promise<BatchPreviewResponse> => {
    const fd = new FormData();
    fd.append("case_id", caseId);
    fd.append("source_type", sourceType);
    files.forEach((f) => fd.append("files", f));
    return apiClient.postForm<BatchPreviewResponse>("/evidence/preview/batch", fd);
  },

  cancelPreview: async (caseId: string, previewId: string): Promise<{ status: string; preview_id: string; purged: boolean }> => {
    const fd = new FormData();
    fd.append("case_id", caseId);
    fd.append("preview_id", previewId);
    return apiClient.postForm<{ status: string; preview_id: string; purged: boolean }>("/evidence/preview/cancel", fd);
  },

  cancelBatch: async (caseId: string, previewIds: string[]): Promise<{ status: string; purged_count: number; purged_ids: string[] }> => {
    const fd = new FormData();
    fd.append("case_id", caseId);
    previewIds.forEach((pid) => fd.append("preview_ids", pid));
    return apiClient.postForm<{ status: string; purged_count: number; purged_ids: string[] }>("/evidence/preview/cancel/batch", fd);
  },

  confirm: async (caseId: string, previewId: string, sourceType = "unknown", originalName?: string): Promise<EvidenceConfirmResponse> => {
    const fd = new FormData();
    fd.append("case_id", caseId);
    fd.append("preview_id", previewId);
    fd.append("source_type", sourceType);
    if (originalName) {
      fd.append("original_name", originalName);
    }
    return apiClient.postForm<EvidenceConfirmResponse>("/evidence/confirm", fd);
  },

  confirmBatch: async (
    caseId: string,
    items: Array<{ preview_id: string; source_type?: string; original_name?: string }>,
    sourceType = "unknown"
  ): Promise<EvidenceConfirmBatchResponse> => {
    const fd = new FormData();
    fd.append("case_id", caseId);
    fd.append("source_type", sourceType);
    fd.append("items", JSON.stringify(items));
    return apiClient.postForm<EvidenceConfirmBatchResponse>("/evidence/confirm/batch", fd);
  },

  retryProcessing: async (caseId: string, evidenceId: string): Promise<{ status: string; message: string; evidence_id: string }> => {
    return apiClient.post<{ status: string; message: string; evidence_id: string }>(`/evidence/${caseId}/${evidenceId}/retry`, {});
  },
};

