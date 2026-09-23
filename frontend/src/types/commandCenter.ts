/**
 * CyberDrishti AI / NETRA V5 — Investigation Command Center TypeScript Contracts
 * Single consolidated read-only projection answering:
 * "What requires my attention in this case right now?"
 */

export interface WidgetHeader {
  title: string;
  status: string; // "URGENT_ACTION" | "REVIEW_REQUIRED" | "HEALTHY" | "SYNCED" | "INFO" | "PROCESSING" | "OPTIMAL" | "DEGRADED" | "CRITICAL"
  metric: string | number;
  last_updated?: string | null;
  source_refs: string[];
  click_action: string;
}

export interface AttentionItem {
  item_id: string;
  priority: 'URGENT_ACTION' | 'REVIEW_REQUIRED' | 'NEW_INTELLIGENCE' | 'INFORMATION';
  category: 'IDENTITY_CONFLICT' | 'RELATIONSHIP_REVIEW' | 'STALE_FINDING' | 'SYNC_CONFLICT' | 'INFORMATION_GAP';
  title: string;
  description: string;
  source_refs: string[];
  click_action: string;
}

export interface AttentionQueueWidget {
  header: WidgetHeader;
  items: AttentionItem[];
  counts_by_priority: Record<string, number>;
}

export interface InvestigationHealthWidget {
  header: WidgetHeader;
  overall_score: number;
  integrity_status: string;
  state_version: number;
  entities_count: number;
  evidence_count: number;
  processed_evidence_count: number;
  relationships_count: number;
  canonical_count: number;
  inferred_count: number;
  unreviewed_relationships_count: number;
  findings_count: number;
  stale_findings_count: number;
  unresolved_identities_count: number;
}

export interface ActivityItem {
  id: string;
  activity_type: string;
  actor: string;
  reason?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  created_at: string;
}

export interface RecentActivityWidget {
  header: WidgetHeader;
  items: ActivityItem[];
}

export interface FindingReviewItem {
  id: string;
  title: string;
  finding_type: string;
  severity: string;
  confidence?: number | null;
  freshness_status: string;
  status: string;
  supporting_refs: string[];
  suggested_actions: string[];
  click_action: string;
}

export interface FindingsWidget {
  header: WidgetHeader;
  items: FindingReviewItem[];
  total_findings: number;
  stale_count: number;
}

export interface IdentityConflictItem {
  id: string;
  candidate_value: string;
  candidate_type: string;
  canonical_entity_id?: string | null;
  resolution_status: string;
  conflict_signals: string[];
  supporting_refs: string[];
  source_refs: string[];
  click_action: string;
}

export interface IdentityConflictsWidget {
  header: WidgetHeader;
  items: IdentityConflictItem[];
  total_unresolved: number;
}

export interface RelationshipReviewItem {
  id: string;
  source_entity_id: string;
  target_entity_id: string;
  source_value?: string | null;
  target_value?: string | null;
  relationship_type: string;
  epistemic_status: string;
  verification_status: string;
  confidence?: number | null;
  source_refs: string[];
  click_action: string;
}

export interface RelationshipReviewWidget {
  header: WidgetHeader;
  items: RelationshipReviewItem[];
  total_unreviewed: number;
}

export interface EvidenceStatusItem {
  id: string;
  filename: string;
  file_type: string;
  upload_status: string;
  sha256_hash: string;
  uploaded_at: string;
  click_action: string;
}

export interface EvidenceStatusWidget {
  header: WidgetHeader;
  items: EvidenceStatusItem[];
  total_files: number;
  processed_files: number;
  pending_files: number;
}

export interface SyncWidget {
  header: WidgetHeader;
  server_state_version: number;
  pending_conflicts_count: number;
  recent_synced_count: number;
  last_synced_at?: string | null;
  sync_status: string;
  click_action: string;
}

export interface LensSummaryWidget {
  header: WidgetHeader;
  money_events_count: number;
  comms_events_count: number;
  geo_events_count: number;
  cross_lens_signals_count: number;
  disclaimer: string;
  click_action: string;
}

export interface MiniNetworkNode {
  id: string;
  label: string;
  entity_type: string;
}

export interface MiniNetworkEdge {
  id: string;
  source: string;
  target: string;
  relationship_type: string;
  is_canonical: boolean;
}

export interface MiniNetworkWidget {
  header: WidgetHeader;
  nodes: MiniNetworkNode[];
  edges: MiniNetworkEdge[];
  click_action: string;
}

export interface CommandCenterProjection {
  case_id: string;
  case_number: string;
  title: string;
  crime_type?: string | null;
  priority: string;
  status: string;
  state_version: number;
  generated_at: string;
  attention_queue: AttentionQueueWidget;
  investigation_health: InvestigationHealthWidget;
  recent_activity: RecentActivityWidget;
  findings_requiring_review: FindingsWidget;
  identity_conflicts: IdentityConflictsWidget;
  relationship_review: RelationshipReviewWidget;
  evidence_status: EvidenceStatusWidget;
  sync_status: SyncWidget;
  lens_summary: LensSummaryWidget;
  mini_network: MiniNetworkWidget;
}
