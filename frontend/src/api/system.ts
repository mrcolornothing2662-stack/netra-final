import { apiClient } from "./client";

export interface SystemHealth {
  status: string;
  version: string;
  environment: string;
  dependencies: {
    postgresql: string;
    chromadb: string;
    disk_free_gb: number;
    models: Record<string, boolean>;
  };
}

export interface AuditVerification {
  /** Recomputed tamper-evident chain integrity (true = unbroken from genesis). */
  intact: boolean;
  /** Total audit entries recomputed (global endpoint). */
  global_entry_count?: number;
  /** Entries scoped to a single case (per-case endpoint). */
  case_entry_count?: number;
  /** "VERIFIED" on success. */
  status?: string;
  /** Human-readable note (e.g. when no entries exist). */
  message?: string;
  /** Set when the chain is broken — the first entry whose hash failed. */
  first_broken_entry_id?: number;
  /** SHA-256 of the genesis entry (chain anchor). */
  genesis_hash?: string;
  /** SHA-256 of the most recent verified entry. */
  last_hash?: string;
}

export interface Officer {
  id: string;
  username: string;
  email: string;
  full_name?: string | null;
  rank?: string | null;
  unit?: string | null;
  role: string;
  is_active: boolean;
}

export interface OfficerCreatePayload {
  username: string;
  email: string;
  password: string;
  full_name?: string;
  rank?: string;
  unit?: string;
  role?: string;
}

export interface IntegrationItem {
  name: string;
  status: string;
  badge: string;
  endpoint: string;
  sync_mode: string;
  description: string;
  models?: Record<string, boolean>;
}

export type IntegrationsResponse = Record<string, IntegrationItem>;

export const systemApi = {
  health: () => apiClient.get<SystemHealth>("/health"),
  verifyAudit: () => apiClient.get<AuditVerification>("/audit/verify"),
  verifyCaseAudit: (caseId: string) =>
    apiClient.get<AuditVerification>(`/audit/verify/${encodeURIComponent(caseId)}`),
  integrations: () => apiClient.get<IntegrationsResponse>("/settings/integrations"),
};

export const officersApi = {
  list: () => apiClient.get<Officer[]>("/officers"),
  create: (body: OfficerCreatePayload) => apiClient.post<Officer>("/officers", body),
};
