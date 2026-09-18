import { apiClient } from "./client";

export interface BackendCaseItem {
  id: string;
  case_number: string;
  title: string;
  description?: string;
  fir_number?: string;
  police_station?: string;
  priority: "high" | "medium" | "low" | "critical";
  status: string;
  crime_type?: string | null;
  assigned_officer_id?: string | null;
  created_at: string;
  updated_at: string;
  tags?: string[];
}

export interface CasesListResponse {
  items?: BackendCaseItem[];
  cases?: BackendCaseItem[];
  total?: number;
  page?: number;
}

export interface BackendCaseSummary {
  case_id: string;
  case_number: string;
  title: string;
  status: string;
  priority: string;
  crime_type: string | null;
  fir_number: string | null;
  police_station: string | null;
  lead_officer: string | null;
  created_at: string;
  counts: {
    evidence: number;
    entities: number;
    connections: number;
    events: number;
    suspicious_findings: number;
  };
  progress: {
    evidence_collection: number;
    entity_extraction: number;
    correlation_analysis: number;
    financial_analysis: number;
    report_ready: number;
  };
  findings?: Array<{
    id: string;
    title: string;
    description: string;
    confidence: number;
    finding_type: string;
    risk_level: string;
    related_entities?: string[];
  }>;
}

export interface CreateCasePayload {
  title: string;
  description?: string;
  priority?: "high" | "medium" | "low" | "critical";
  fir_number?: string;
  police_station?: string;
  crime_type?: string;
  case_number?: string;
}

export const casesApi = {
  list: async (params?: Record<string, string | number>): Promise<BackendCaseItem[]> => {
    const query = params ? "?" + new URLSearchParams(params as Record<string, string>).toString() : "";
    const res = await apiClient.get<CasesListResponse | BackendCaseItem[]>(`/cases${query}`);
    if (Array.isArray(res)) return res;
    return res.items || res.cases || [];
  },

  get: (id: string): Promise<BackendCaseItem> =>
    apiClient.get<BackendCaseItem>(`/cases/${id}`),

  create: (payload: CreateCasePayload): Promise<BackendCaseItem> =>
    apiClient.post<BackendCaseItem>("/cases", payload),

  summary: (id: string): Promise<BackendCaseSummary> =>
    apiClient.get<BackendCaseSummary>(`/cases/${id}/summary`),

  stats: () => apiClient.get<Record<string, unknown>>("/cases/stats/summary"),

  update: (id: string, payload: Partial<CreateCasePayload> & { status?: string }) =>
    apiClient.patch<BackendCaseItem>(`/cases/${id}`, payload),
};
