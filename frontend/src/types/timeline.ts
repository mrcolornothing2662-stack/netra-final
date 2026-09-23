/**
 * Types for Milestone 4: Timeline & Investigation Incident Replay
 */

export type TimelineMode = 'incident' | 'investigation' | 'all';

export type TimeConfidence = 'CONFIRMED' | 'APPROXIMATE' | 'NORMALIZED' | 'RECORDED_ONLY';

export interface TimelineProvenance {
  evidence_file_id?: string | null;
  file_name?: string | null;
  page_num?: number | null;
  line_num?: number | null;
  confidence?: number | null;
  source_record_id?: string | null;
}

export interface TimelineEventItem {
  id: string;
  stream: 'INCIDENT' | 'INVESTIGATION';
  event_time: string | null;
  recorded_at: string;
  time_confidence: TimeConfidence;
  category: string;
  summary: string;
  state_version: number | null;
  actor: string;
  details: Record<string, any>;
  provenance: TimelineProvenance;
  time_warning: string | null;
}

export interface TimelineSummary {
  total_items: number;
  incident_events_count: number;
  investigation_events_count: number;
  unresolved_time_count: number;
  current_case_version: number;
}

export interface TimelineResponse {
  mode: TimelineMode;
  total: number;
  summary: TimelineSummary;
  events: TimelineEventItem[];
}

export interface ReplayVersionItem {
  version: number;
  timestamp: string | null;
  state_hash: string | null;
  activity_type: string;
  summary: string;
  actor: string;
}

export interface ReplayIndexResponse {
  case_id: string;
  case_number: string;
  title: string;
  current_version: number;
  total_versions: number;
  versions: ReplayVersionItem[];
}

export interface HistoricalEntity {
  id: string;
  canonical_value: string;
  entity_type: string;
  degree_centrality: number;
  bridge_score: number;
  created_at?: string | null;
}

export interface HistoricalRelationship {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  relationship_type: string;
  direction: string;
  epistemic_status: string;
  verification_status: string;
  is_canonical: boolean;
  confidence: number;
  evidence_refs: string[];
  event_refs: string[];
}

export interface HistoricalCandidate {
  id: string;
  canonical_entity_id?: string | null;
  candidate_value: string;
  candidate_type: string;
  resolution_status: 'UNRESOLVED' | 'CONFIRMED_SAME' | 'CONFIRMED_DIFFERENT';
  created_at?: string | null;
}

export interface HistoricalFinding {
  id: string;
  finding_type: string;
  title: string;
  severity: string;
  confidence: number;
  status: string;
  freshness_status: string;
  generated_at_case_version: number;
  evidence_refs: string[];
  entity_refs: string[];
}

export interface HistoricalStateProjection {
  case_id: string;
  case_number: string;
  title: string;
  state_version: number;
  current_case_version: number;
  is_historical: boolean;
  checkpoint_timestamp: string | null;
  state_hash: string | null;
  cursor_activity: {
    id: string;
    activity_type: string;
    target_type?: string | null;
    target_id?: string | null;
    actor_id?: string | null;
    reason?: string | null;
    created_at?: string | null;
  } | null;
  metrics: {
    entities_count: number;
    canonical_relationships_count: number;
    inferred_relationships_count: number;
    findings_count: number;
    unresolved_candidates_count: number;
    evidence_files_count: number;
  };
  entities: HistoricalEntity[];
  relationships: {
    canonical: HistoricalRelationship[];
    inferred: HistoricalRelationship[];
  };
  identity_candidates: HistoricalCandidate[];
  findings: HistoricalFinding[];
}
