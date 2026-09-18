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
};
