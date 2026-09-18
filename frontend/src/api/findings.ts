/**
 * CyberDrishti AI — Unified Findings & Intelligence State API
 *
 * The Cognitive tab's primary data source: the orchestrator's persisted
 * InvestigationFinding rows plus the materialised per-case intelligence state.
 * Findings are the source of truth; engines are the drill-down behind them.
 */
import { apiClient } from "./client";

export type FindingType =
  | "CONTRADICTION"
  | "HIDDEN_LINK"
  | "HYPOTHESIS"
  | "UNCERTAINTY"
  | "NEXT_BEST_ACTION"
  | "MO_MATCH"
  | "FINGERPRINT_VARIANT"
  | "REPLAY_ANOMALY"
  | "CROSS_CASE_SIGNAL"
  | "COUNTERFACTUAL"
  | "VERIFICATION";

export type FindingSeverity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type FindingStatus = "OPEN" | "CONFIRMED" | "DISMISSED" | "SUPERSEDED";

export interface Finding {
  id: string;
  case_id: string;
  fingerprint: string;
  finding_type: FindingType;
  title: string;
  description: string | null;
  confidence: number | null;
  /** Honest meaning of the confidence value: CALIBRATED | NOT_CALIBRATED |
   *  RULE_BASED | SCREENING | INFERRED | DIRECT_OBSERVATION | SIMULATION | UNRESOLVED */
  confidence_status?: string;
  confidence_details?: {
    epistemic_tier: string;
    score_type: string;
    tier_description: string;
    raw_score: number | null;
    evidence_count: number;
  };
  severity: FindingSeverity;
  status: FindingStatus;
  source_engine: string | null;
  engine_version: string | null;
  entity_refs: string[];
  event_refs: string[];
  evidence_refs: string[];
  component_scores: Record<string, unknown>;
  reason_codes: string[];
  reasoning: string | null;
  citations: Array<Record<string, unknown>>;
  has_evidence: boolean;
  observed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface FindingsListResponse {
  case_id: string;
  count: number;
  findings: Finding[];
}

export interface EngineStatus {
  status: "ok" | "skipped" | "error";
  version?: string;
  findings?: number;
  reason?: string;
  error?: string;
}

export interface IntelligenceState {
  case_id: string;
  computed: boolean;
  evidence_count: number;
  processed_evidence_count: number;
  entity_count: number;
  event_count: number;
  relationship_count: number;
  observed_relationship_count: number;
  inferred_relationship_count: number;
  finding_count: number;
  high_priority_count: number;
  findings_by_type: Record<string, number>;
  engine_status: Record<string, EngineStatus>;
  last_run_id: string | null;
  last_run_at: string | null;
  updated_at?: string | null;
}

export interface AnalyzeResponse {
  run_id: string;
  case_id: string;
  status: string;
  trigger: string;
  duration_ms: number;
  engines_run: string[];
  engines_skipped: string[];
  engine_status: Record<string, EngineStatus>;
  findings_created: number;
  findings_updated: number;
  findings_total: number;
  state: Omit<IntelligenceState, "case_id" | "computed" | "engine_status" | "last_run_id" | "last_run_at">;
}

export interface FindingsFilter {
  finding_type?: string;
  severity?: FindingSeverity;
  status?: FindingStatus;
  min_confidence?: number;
  limit?: number;
  offset?: number;
}

function queryString(filter?: FindingsFilter): string {
  if (!filter) return "";
  const params = new URLSearchParams();
  Object.entries(filter).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  });
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const findingsApi = {
  /** Latest materialised intelligence snapshot for the case. */
  state: (caseId: string) =>
    apiClient.get<IntelligenceState>(`/intelligence/cases/${caseId}/state`),

  /** Unified findings, ranked by confidence. */
  list: (caseId: string, filter?: FindingsFilter) =>
    apiClient.get<FindingsListResponse>(`/intelligence/cases/${caseId}/findings${queryString(filter)}`),

  /** Run the cognitive orchestrator over the case's current evidence. */
  analyze: (caseId: string, engines?: string[]) =>
    apiClient.post<AnalyzeResponse>(`/intelligence/cases/${caseId}/analyze`, {
      engines: engines && engines.length ? engines : undefined,
    }),
};
