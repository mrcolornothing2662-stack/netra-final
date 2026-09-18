export type Priority = "CRITICAL" | "HIGH" | "MEDIUM" | null;
export type CaseStatus = "ACTIVE" | "ARCHIVED" | "NEW";

/**
 * Data provenance contract.
 *
 * Every object that reaches the UI is one of four kinds, and they must never
 * visually masquerade as one another:
 *   REAL_EVIDENCE     — a raw fact taken directly from ingested evidence
 *   DERIVED_ANALYSIS  — produced by deterministic extraction/correlation
 *   SYNTHETIC_DEMO    — the labelled demonstration dataset; never real
 *   USER_ASSERTED     — entered/edited by an investigator
 *
 * Sprint 1 only *applies* SYNTHETIC_DEMO (to drive the demo badge and the
 * demo gating seam). REAL_EVIDENCE / DERIVED_ANALYSIS / USER_ASSERTED tagging
 * and the full `provenance` payload are threaded through in later sprints.
 */
export type SourceType =
  | "REAL_EVIDENCE"
  | "DERIVED_ANALYSIS"
  | "SYNTHETIC_DEMO"
  | "USER_ASSERTED";

export interface Provenance {
  evidenceIds?: string[];
  extractionMethod?: string;
  createdBy?: string;
  confidence?: number;
}

export interface Case {
  id: string;
  name: string;
  domain: string;
  entities: number;
  evidence: number;
  leads: number;
  priority: Priority;
  status: CaseStatus;
  updated: string;
  brief: string;
  latest: string;
  user?: boolean;
  uuid?: string;
  case_number?: string;
  source_type?: SourceType;
  provenance?: Provenance;
}

export type EntityKind =
  | "PERSON"
  | "DEVICE"
  | "ACCOUNT"
  | "ORG"
  | "UPI"
  | "IFSC"
  | "BANK"
  | "AMOUNT"
  | "DOMAIN"
  | "IP"
  | "FILE"
  | "MALWARE"
  | "CAMPAIGN"
  | "EMAIL"
  | "THREAT_ACTOR"
  | "PHONE"
  | "CELL_TOWER";

export interface Entity {
  id: string;
  name: string;
  kind: EntityKind;
  meta: string;
  risk?: "HIGH" | "MEDIUM";
  mentionCount?: number;
  linkedEvidenceIds?: string[];
  bridgeScore?: number;
  source_type?: SourceType;
  provenance?: Provenance;
}

export type EvidenceKind = "DOC" | "IMAGE" | "DATA" | "COMMS";
export type EvidenceStatus = "VERIFIED" | "ANALYZED" | "UNVERIFIED" | "PROCESSING";

export interface Evidence {
  id: string;
  label: string;
  kind: EvidenceKind;
  meta: string;
  status: EvidenceStatus;
  imageUrl?: string;
  user?: boolean;
  addedAt?: number;
  sha256?: string;
  notes?: string;
  source_type?: SourceType;
  provenance?: Provenance;
  parent_evidence_id?: string | null;
  version_number?: number;
  version_status?: "original" | "variant" | "superseded" | string;
  fingerprint_hash?: string;
  variant_details?: Record<string, any>;
  is_variant?: boolean;
  variant_note?: string | null;
}

export interface CaseEvent {
  id: string;
  date: string;
  ts: string;
  kind: "COMMUNICATION" | "TRANSACTION" | "LOCATION" | "DEVICE";
  label: string;
  entityIds: string[];
  evidenceIds: string[];
  source_type?: SourceType;
  /** Event-time normalization state: OK | TIME_NORMALIZATION_REQUIRED | PARSE_ERROR */
  timeStatus?: "OK" | "TIME_NORMALIZATION_REQUIRED" | "PARSE_ERROR" | string;
  /** When NETRA ingested the parent artifact (distinct from event time). */
  ingestedAt?: string | null;
  /** Routine/low-signal event (collapsed by the timeline by default). */
  isRoutine?: boolean;
}

export interface Connection {
  id: string;
  a: string;
  b: string;
  reason: string;
  confidence: number;
  type?: string;
  directed?: number;
  findingId?: string;
  evidenceIds?: string[];
  is_hidden?: boolean;
  score?: number;
  threshold?: number;
  component_scores?: Record<string, number>;
  // Semantic + epistemic provenance from the unified case graph.
  relationship_type?: string;
  epistemic_status?: "OBSERVED" | "INFERRED";
  direction?: string;
  evidence_refs?: string[];
  event_refs?: string[];
  has_provenance?: boolean;
  source_type?: SourceType;
}

export interface Finding {
  id: string;
  title: string;
  when: string;
  confidence: string;
  body: string;
  evidenceIds: string[];
  scope?: string;
  source_type?: SourceType;
}
