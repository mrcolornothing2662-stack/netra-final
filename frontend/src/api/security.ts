import { apiClient } from "./client";

export interface SecurityOverview {
  status: "HEALTHY" | "TAMPERING_DETECTED";
  audit_chain: {
    intact: boolean;
    status: string;
    global_entry_count: number;
    genesis_hash?: string;
    last_hash?: string;
    message?: string;
  };
  metrics: {
    total_audit_events: number;
    failed_auth_events: number;
    permission_denials: number;
    evidence_access_events: number;
    report_approvals: number;
    export_events: number;
    active_sessions: number;
    offline_conflicts: number;
  };
}

export interface SecurityEvent {
  id: number;
  action: string;
  category: string;
  user_id: string | null;
  resource_type: string | null;
  resource_id: string | null;
  event_timestamp: string | null;
  details: Record<string, any>;
  prev_hash: string;
  entry_hash: string;
}

export interface UserSessionItem {
  session_id: string;
  user_id: string;
  username: string;
  full_name: string | null;
  rank: string | null;
  role: string;
  device_id: string;
  issued_at: string | null;
  expires_at: string | null;
  last_seen: string | null;
  authentication_level: string;
  revoked: boolean;
  revoked_reason: string | null;
  ip_address: string | null;
  user_agent: string | null;
}

export const securityApi = {
  overview: async (): Promise<SecurityOverview> => {
    return apiClient.get<SecurityOverview>("/security/overview");
  },

  events: async (category = "all", page = 1, pageSize = 50): Promise<{
    page: number;
    page_size: number;
    total: number;
    category: string;
    items: SecurityEvent[];
  }> => {
    return apiClient.get(`/security/events?category=${encodeURIComponent(category)}&page=${page}&page_size=${pageSize}`);
  },

  sessions: async (): Promise<UserSessionItem[]> => {
    return apiClient.get<UserSessionItem[]>("/security/sessions");
  },

  revokeSession: async (sessionId: string, reason?: string): Promise<{ status: string; message: string }> => {
    const q = reason ? `?reason=${encodeURIComponent(reason)}` : "";
    return apiClient.post(`/security/sessions/${encodeURIComponent(sessionId)}/revoke${q}`);
  },
};

