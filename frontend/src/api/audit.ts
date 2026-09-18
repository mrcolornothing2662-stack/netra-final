/**
 * CyberDrishti AI — Audit Log API Client
 */
import { apiClient } from "./client";

export interface AuditLogEntry {
  id: number;
  action: string;
  resource_type: string;
  resource_id: string;
  user_id: string | null;
  entry_hash: string;
  prev_hash: string;
  details: Record<string, unknown> | null;
  event_timestamp: string;
}

/** Response shape of GET /audit — { page, total, items } as returned by the backend. */
export interface AuditLogListResponse {
  page: number;
  total: number;
  items: AuditLogEntry[];
}

export const auditApi = {
  /**
   * List audit log entries with optional filtering.
   * Param names match the backend contract (page / page_size / action /
   * resource_type / case_id).
   */
  list: (params?: {
    page?: number;
    page_size?: number;
    case_id?: string;
    action?: string;
    resource_type?: string;
  }) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.page_size) q.set("page_size", String(params.page_size));
    if (params?.case_id) q.set("case_id", params.case_id);
    if (params?.action) q.set("action", params.action);
    if (params?.resource_type) q.set("resource_type", params.resource_type);
    const qs = q.toString();
    return apiClient.get<AuditLogListResponse | AuditLogEntry[]>(
      `/audit${qs ? `?${qs}` : ""}`,
    );
  },
};
