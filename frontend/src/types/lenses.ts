/**
 * CyberDrishti AI / NETRA V5 — Forensic Lenses Types
 * Unified TypeScript interfaces matching backend/forensic/contracts.py
 */

export type ForensicLensType = 'MONEY' | 'COMMUNICATION' | 'GEOGRAPHIC';

export interface LensEntity {
  id: string;
  canonical_value: string;
  entity_type: string;
  role?: string | null;
  degree_centrality: number;
  bridge_score: number;
  mention_count: number;
  node_metadata: Record<string, any>;
}

export interface LensEvent {
  id: string;
  event_type: string;
  event_time?: string | null;
  recorded_at: string;
  time_confidence: 'CONFIRMED' | 'APPROXIMATE' | 'NORMALIZED' | 'RECORDED_ONLY' | string;
  summary: string;
  details: Record<string, any>;
  evidence_file_id?: string | null;
  source_doc?: string | null;
  source_page?: number | null;
  source_line?: number | null;
  provenance_confidence?: number | null;
  time_warning?: string | null;
}

export interface LensRelationship {
  id: string;
  source_entity_id: string;
  source_entity_value?: string | null;
  target_entity_id: string;
  target_entity_value?: string | null;
  relationship_type: string;
  direction: 'OUTBOUND' | 'INBOUND' | 'BIDIRECTIONAL' | string;
  epistemic_status: 'OBSERVED' | 'INFERRED' | 'HYPOTHETICAL' | 'EXCLUDED' | 'DISPUTED' | string;
  verification_status: 'UNREVIEWED' | 'CONFIRMED' | 'REJECTED' | string;
  is_canonical: boolean;
  confidence: number;
  evidence_refs: string[];
  event_refs: string[];
  created_by?: string | null;
}

export interface LensSignal {
  id: string;
  signal_type: string;
  severity: 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL' | string;
  title: string;
  description: string;
  timestamp?: string | null;
  entities_involved: string[];
  evidence_refs: string[];
  event_refs: string[];
  metrics: Record<string, any>;
}

export interface LensFinding {
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
  event_refs: string[];
}

export interface EvidenceRef {
  id: string;
  file_name: string;
  file_type?: string | null;
  sha256?: string | null;
  uploaded_at?: string | null;
}

export interface LensTimelineEvent {
  id: string;
  timestamp?: string | null;
  label: string;
  category: string;
  entities: string[];
  evidence_id?: string | null;
  source_doc?: string | null;
  source_page?: number | null;
  source_line?: number | null;
  disclaimer?: string | null;
}

export interface CrossLensSignal {
  id: string;
  title: string;
  description: string;
  lenses_involved: string[];
  time_window: {
    start?: string | null;
    end?: string | null;
  };
  entities_involved: string[];
  events_involved: string[];
  evidence_refs: string[];
  confidence: number;
}

export interface ForensicLensResponse {
  id: ForensicLensType;
  case_id: string;
  case_number: string;
  title: string;
  state_version: number;
  is_historical: boolean;
  disclaimer?: string | null;
  summary: Record<string, any>;
  entities: LensEntity[];
  events: LensEvent[];
  relationships: LensRelationship[];
  signals: LensSignal[];
  findings: LensFinding[];
  evidence_refs: EvidenceRef[];
  timeline: LensTimelineEvent[];
  cross_lens_signals: CrossLensSignal[];
}

export interface LensOverviewResponse {
  case_id: string;
  case_number: string;
  title: string;
  state_version: number;
  money_summary: {
    transaction_count: number;
    has_data: boolean;
    [key: string]: any;
  };
  communications_summary: {
    communication_count: number;
    has_data: boolean;
    [key: string]: any;
  };
  geographic_summary: {
    observation_count: number;
    has_data: boolean;
    disclaimer?: string;
    [key: string]: any;
  };
  cross_lens_coincidences_count: number;
  active_lenses: string[];
}
