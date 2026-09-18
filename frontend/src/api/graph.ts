import { apiClient } from "./client";

export interface BackendGraphNode {
  id: string;
  entity_type: string;
  label: string;
  mention_count: number;
  degree_centrality: number;
  community_id?: number | null;
  bridge_score: number;
  is_prominent?: boolean;
  evidence_sources?: Array<{
    event_type: string;
    text_content: string;
    source_line?: number | null;
    source_page?: number | null;
    event_metadata?: Record<string, unknown>;
  }>;
}

export interface BackendGraphEdge {
  source: string;
  target: string;
  edge_type: string;
  weight: number;
  score?: number;
  component_scores?: Record<string, number>;
  // Unified case-graph provenance (present on observed semantic edges).
  relationship_type?: string | null;
  epistemic_status?: "OBSERVED" | "INFERRED";
  direction?: string | null;
  confidence?: number | null;
  amount?: number | null;
  evidence_refs?: string[];
  event_refs?: string[];
  observation_count?: number | null;
  has_provenance?: boolean;
  source_citations?: Array<Record<string, unknown>>;
}

export interface BackendRelationship {
  id: string;
  source: string | null;
  target: string | null;
  relationship_type: string;
  direction: string;
  epistemic_status: "OBSERVED" | "INFERRED";
  confidence: number | null;
  amount?: number | null;
  evidence_refs: string[];
  event_refs: string[];
  reason_codes?: string[];
}

export interface BackendGraphData {
  nodes: BackendGraphNode[];
  edges: BackendGraphEdge[];
  hidden_edges?: BackendGraphEdge[];
  relationships?: {
    observed: BackendRelationship[];
    inferred: BackendRelationship[];
    total: number;
  };
}

export interface BackendTimelineEvent {
  id: string;
  /** When the underlying activity actually happened (source clock). */
  event_time?: string | null;
  /** @deprecated alias of event_time — never the ingestion timestamp. */
  timestamp: string | null;
  /** When NETRA received/processed the artifact. */
  ingested_at?: string | null;
  /** OK | TIME_NORMALIZATION_REQUIRED */
  time_status?: string;
  event_type: string;
  /** True when this event is routine/low-signal (collapsed by the timeline). */
  is_routine?: boolean;
  text: string;
  text_content?: string;
  source_doc?: string | null;
  source_line?: number | null;
  source_page?: number | null;
  metadata?: Record<string, unknown>;
}

export interface TimelineResponse {
  events: BackendTimelineEvent[];
  count?: number;
  total_available?: number;
  time_normalization_required?: number;
  routine_count?: number;
  order?: string;
}

export const graphApi = {
  get: (caseId: string, twoHop = false): Promise<BackendGraphData> =>
    apiClient.get<BackendGraphData>(`/graph/${caseId}${twoHop ? "?two_hop=true" : ""}`),

  timeline: async (caseId: string): Promise<BackendTimelineEvent[]> => {
    const res = await apiClient.get<TimelineResponse | BackendTimelineEvent[]>(`/timeline/${caseId}`);
    if (Array.isArray(res)) return res;
    return res.events || [];
  },

  query: (caseId: string, question: string) =>
    apiClient.post(`/query/${caseId}`, { question }),
};
