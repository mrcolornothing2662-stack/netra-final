/**
 * CyberDrishti AI — Entity Explorer & Identity Resolution Types (V5 Milestone 3)
 */

export interface EntitySummary {
  id: string;
  canonical_value: string;
  entity_type: string;
  epistemic_status: "OBSERVED" | "INFERRED" | "INVESTIGATOR_ADDED";
  first_seen: string | null;
  last_seen: string | null;
  mention_count: number;
  relationship_count: number;
  degree_centrality: number;
  bridge_score: number;
  has_candidate_conflict: boolean;
  aliases: string[];
}

export interface SourceEvidenceFile {
  id: string;
  filename: string;
  file_type?: string;
  sha256_hash?: string;
  uploaded_at?: string | null;
}

export interface EntityMentionDetail {
  id: string;
  raw_value: string;
  entity_type: string;
  confidence?: number | null;
  extractor: string;
  span_start?: number | null;
  span_end?: number | null;
  event_id?: string | null;
  event_type?: string | null;
  event_timestamp?: string | null;
  source_doc?: string | null;
  source_file_id?: string | null;
  source_line?: number | null;
  source_page?: number | null;
  snippet?: string | null;
}

export interface RelatedEventDetail {
  id: string;
  event_type: string;
  event_timestamp?: string | null;
  text_content?: string;
  source_doc?: string | null;
  source_file_id?: string | null;
  source_line?: number | null;
  source_page?: number | null;
}

export interface EntityRelationshipDetail {
  id: string;
  is_outbound: boolean;
  direction: string;
  relationship_type: string;
  target_entity_id: string;
  target_canonical_value: string;
  target_entity_type: string;
  epistemic_status: "OBSERVED" | "INFERRED";
  verification_status?: string;
  is_canonical: boolean;
  confidence?: number | null;
  amount?: number | null;
  evidence_refs: string[];
  event_refs: string[];
  reason_codes: string[];
}

export interface MatchSignal {
  signal: string;
  detail: string;
  strength: "HIGH" | "MEDIUM" | "LOW" | string;
}

export interface ConflictSignal {
  signal: string;
  detail: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | string;
}

export interface IdentityCandidateDetail {
  id: string;
  canonical_entity_id?: string | null;
  candidate_value: string;
  candidate_type: string;
  resolution_status: "UNRESOLVED" | "CONFIRMED_SAME" | "CONFIRMED_DIFFERENT" | "REJECTED" | string;
  match_signals: MatchSignal[];
  conflict_signals: ConflictSignal[];
  created_at?: string | null;
  resolved_at?: string | null;
}

export interface EntityDossier {
  id: string;
  canonical_value: string;
  entity_type: string;
  epistemic_status: string;
  first_seen: string | null;
  last_seen: string | null;
  degree_centrality: number;
  bridge_score: number;
  aliases: string[];
  risk?: string | null;
  metadata?: Record<string, unknown>;
}

export interface EntityDossierResponse {
  case_id: string;
  case_state_version: number;
  entity: EntityDossier;
  provenance: {
    source_evidence_files: SourceEvidenceFile[];
    extractors: string[];
    mention_count: number;
  };
  mentions: EntityMentionDetail[];
  related_events: RelatedEventDetail[];
  relationships: {
    canonical: EntityRelationshipDetail[];
    analytical: EntityRelationshipDetail[];
    canonical_count: number;
    analytical_count: number;
  };
  identity_candidates: IdentityCandidateDetail[];
}

export interface IdentityCandidateEntityRef {
  id: string | null;
  canonical_value: string;
  entity_type: string;
  first_seen?: string | null;
  last_seen?: string | null;
}

export interface IdentityCandidateQueueItem {
  id: string;
  canonical_entity: IdentityCandidateEntityRef;
  candidate_entity: IdentityCandidateEntityRef;
  candidate_value: string;
  candidate_type: string;
  resolution_status: "UNRESOLVED" | "CONFIRMED_SAME" | "CONFIRMED_DIFFERENT" | "REJECTED" | string;
  match_signals: MatchSignal[];
  conflict_signals: ConflictSignal[];
  created_at: string | null;
  resolved_at: string | null;
}

export interface EntityListResponse {
  case_id: string;
  case_state_version: number;
  total: number;
  returned: number;
  limit: number;
  offset: number;
  summary: {
    total_in_case: number;
    pending_conflicts: number;
  };
  entities: EntitySummary[];
}

export interface IdentityCandidatesQueueResponse {
  case_id: string;
  case_state_version: number;
  count: number;
  pending_count: number;
  capabilities: {
    can_resolve: boolean;
  };
  candidates: IdentityCandidateQueueItem[];
}

export interface CandidateResolutionPayload {
  verdict: "CONFIRMED_SAME" | "CONFIRMED_DIFFERENT" | "REJECTED" | "resolve" | "keep_separate" | string;
  reason?: string;
  candidate_entity_id?: string;
  base_case_version?: number;
}

export interface CandidateResolutionResponse {
  candidate_id: string;
  resolution_status: string;
  action_taken: string;
  case_state_version: number;
  message: string;
}
