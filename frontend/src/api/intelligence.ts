import { apiClient } from "./client";

export interface CrossMatchItem {
  case_id: string;
  case_number: string;
  case_title: string;
  crime_type: string | null;
  priority: string;
  status: string;
  entity_value: string;
  entity_type: string;
  first_seen: string | null;
  last_seen: string | null;
  mention_count: number;
}

export interface CrossMatchResponse {
  query: string;
  normalized_query: string;
  total_matches: number;
  matches: CrossMatchItem[];
}

export interface SyndicateCaseItem {
  case_id: string;
  case_number: string;
  case_title: string;
  crime_type: string | null;
  priority: string;
  status: string;
}

export interface SyndicateEntity {
  canonical_value: string;
  entity_type: string;
  case_count: number;
  cases: SyndicateCaseItem[];
}

export interface SyndicateListResponse {
  total_syndicates: number;
  syndicates: SyndicateEntity[];
}

/* ── Communication Intelligence (deep CDR/WhatsApp analysis) ──────────── */

export interface CallPair {
  caller: string;
  callee: string;
  call_count: number;
  total_duration_sec: number;
  first_call: string | null;
  last_call: string | null;
}

export interface CommBurst {
  start: string;
  end: string;
  call_count: number;
  duration_minutes: number;
}

export interface WhatsAppSender {
  sender: string;
  message_count: number;
  first_message: string | null;
  last_message: string | null;
}

export interface CommIntelResponse {
  case_id: string;
  call_pairs: CallPair[];
  call_pair_count: number;
  total_calls: number;
  total_whatsapp_messages: number;
  communication_bursts: CommBurst[];
  whatsapp_senders: WhatsAppSender[];
  hourly_message_distribution: Record<string, number>;
}

/* ── Financial Intelligence (deep bank transaction analysis) ──────────── */

export interface FinancialTransaction {
  id: string;
  timestamp: string | null;
  narration: string;
  debit: number | null;
  credit: number | null;
  balance: number | null;
  source_line: number | null;
  source_page: number | null;
  source_doc: string;
  parse_status?: string;
}

export interface RoundNumberTxn {
  amount: number;
  timestamp: string | null;
  narration: string;
  direction: string;
}

export interface RapidTransfer {
  txn_a_id: string;
  txn_b_id: string;
  txn_a_ts: string;
  txn_b_ts: string;
  gap_minutes: number;
  txn_a_narration: string;
  txn_b_narration: string;
}

export interface Counterparty {
  narration: string;
  total_amount: number;
}

export interface FinancialIntelResponse {
  case_id: string;
  total_transactions: number;
  total_debit: number;
  total_credit: number;
  net_flow: number;
  transactions: FinancialTransaction[];
  round_number_transactions: RoundNumberTxn[];
  rapid_transfers: RapidTransfer[];
  top_counterparties_by_volume: Counterparty[];
}

/* ── Correlations / Hidden Links ──────────────────────────────────────── */

export interface CorrelationEntityRef {
  id: string;
  type: string;
  value: string;
}

export interface CorrelationItem {
  id: string;
  case_id: string;
  entity_a: CorrelationEntityRef;
  entity_b: CorrelationEntityRef;
  final_score: number;
  threshold: number;
  decision: string;
  component_scores: Record<string, number>;
  model_weights?: Record<string, number> | null;
  source_citations?: Array<Record<string, unknown>>;
  verified_by: string | null;
  verified_at: string | null;
  created_at?: string | null;
}

export interface CorrelationsRunResponse {
  case_id: string;
  case_number: string;
  flagged: number;
  entity_count: number;
  threshold: number;
  message: string;
}

export interface CorrelationsListResponse {
  case_id: string;
  count: number;
  correlations: CorrelationItem[];
}

/* ── API Functions ────────────────────────────────────────────────────── */

export const intelApi = {
  crossMatch: (query?: string): Promise<CrossMatchResponse> => {
    const q = query ? `?query=${encodeURIComponent(query)}` : "";
    return apiClient.get<CrossMatchResponse>(`/intel/cross-match${q}`);
  },

  syndicates: (limit = 50): Promise<SyndicateListResponse> =>
    apiClient.get<SyndicateListResponse>(`/intel/syndicates?limit=${limit}`),

  events: () => apiClient.get<unknown[]>("/events"),

  /** Deep CDR + WhatsApp analysis. */
  communicationIntel: (caseId: string): Promise<CommIntelResponse> =>
    apiClient.get<CommIntelResponse>(`/intelligence/communication/${caseId}`),

  /** Deep bank transaction analysis. */
  financialIntel: (caseId: string): Promise<FinancialIntelResponse> =>
    apiClient.get<FinancialIntelResponse>(`/intelligence/financial/${caseId}`),

  /** List flagged correlations. */
  correlations: (caseId: string): Promise<CorrelationsListResponse> =>
    apiClient.get<CorrelationsListResponse>(`/correlations/${caseId}`),

  /** Run correlation analysis. */
  runCorrelations: (caseId: string): Promise<CorrelationsRunResponse> =>
    apiClient.post<CorrelationsRunResponse>(`/correlations/${caseId}/run`),

  /** Verify or dispute a correlation. */
  verifyCorrelation: (correlationId: string, verdict: string, notes?: string) =>
    apiClient.post(`/correlations/${correlationId}/verify`, { verdict, notes }),
};
