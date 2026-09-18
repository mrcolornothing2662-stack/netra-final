/**
 * CyberDrishti AI — Cognitive Forensic Intelligence API Client
 *
 * Frontend API layer for all 11 cognitive engine endpoints.
 * Uses the same authenticated apiClient pattern as the rest of the app.
 */
import { apiClient } from "./client";

/* ── Response Types ─────────────────────────────────────────────────────── */

export interface LedgerFinding {
  kind: string;
  row_index: number;
  expected_balance: number;
  reported_balance: number;
  discrepancy: number;
  explanation: string;
  epistemic_status: string;
}

export interface TravelFinding {
  kind: string;
  entity: string;
  location_a: string;
  location_b: string;
  distance_km: number;
  time_gap_s: number;
  velocity_kmh: number;
  explanation: string;
  epistemic_status: string;
}

export interface EntityProfile {
  entity: string;
  entity_type: string;
  total_events: number;
  txn_count: number;
  total_volume: number;
  mean_amount: number;
  stdev_amount: number;
  median_amount: number;
  mad_amount: number;
  min_amount: number;
  max_amount: number;
  baseline_status: string;
  total_active_hours: number;
  off_hours_count: number;
  daytime_count: number;
  off_hours_ratio: number;
  pass_through_count: number;
  min_pass_through_min: number | null;
  locations_seen: string[];
}

export interface BehavioralAnomaly {
  anomaly_type: string;
  entity: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  title: string;
  description: string;
  confidence: number;
  epistemic_status: string;
  component_scores: Record<string, any>;
  reason_codes: string[];
  reasoning: string;
  event_refs: string[];
  evidence_refs: string[];
  citations: Array<Record<string, any>>;
}

export interface AnomaliesResponse {
  case_id: string;
  profiles: Record<string, EntityProfile>;
  findings: BehavioralAnomaly[];
  summary: {
    total_entities_profiled: number;
    established_baselines: number;
    total_anomalies: number;
    by_severity: {
      CRITICAL: number;
      HIGH: number;
      MEDIUM: number;
      LOW: number;
    };
  };
}

export interface ContradictionsResponse {
  case_id: string;
  ledger_audit: {
    input_rows: number;
    findings: LedgerFinding[];
  };
  impossible_travel: {
    input_events: number;
    findings: TravelFinding[];
  };
  entity_profiles?: Record<string, EntityProfile>;
  behavioral_anomalies?: BehavioralAnomaly[];
  anomaly_summary?: {
    total_entities_profiled: number;
    established_baselines: number;
    total_anomalies: number;
    by_severity: Record<string, number>;
  };
}

export interface SuspectCandidate {
  id: string;
  value: string;
  entity_type: string;
  degree: number;
  role_hint: string;
}

export interface RefutingEvidence {
  indicator: string;
  bucket: string;
  likelihood: number;
  likelihood_under_this_hypothesis?: number;
  diagnosticity: number;
  why: string;
  provenance?: {
    source_file?: string;
    source_line?: number;
    event_type?: string;
    sample_text?: string;
  };
}

export interface SupportingEvidence {
  indicator: string;
  bucket: string;
  likelihood: number;
  diagnosticity: number;
  why: string;
  provenance?: {
    source_file?: string;
    source_line?: number;
    event_type?: string;
    sample_text?: string;
  };
}

export interface ACHHypothesisItem {
  rank: number;
  label: string;
  description: string;
  posterior: number | null;
  classification?: string;
  inconsistency_score?: number;
  refuting_evidence?: RefutingEvidence | null;
  supporting_evidence?: SupportingEvidence | null;
}

export interface ACHEvidenceMatrixRow {
  indicator: string;
  observation_key: string;
  observed_value: number;
  bucket: string;
  likelihoods: Record<string, number>;
  diagnosticity: number;
  consistent_hypotheses: string[];
  inconsistent_hypotheses: string[];
  note: string;
  provenance?: {
    source_file?: string;
    source_line?: number;
    event_type?: string;
    sample_text?: string;
  };
}

export interface UnobservedIndicatorDetail {
  indicator: string;
  observation_key: string;
  required_evidence: string;
  potential_impact: string;
  note?: string;
}

export interface HypothesesResponse {
  case_id: string;
  case_number?: string;
  case_title?: string;
  police_station?: string;
  target_entity: string | null;
  candidates?: SuspectCandidate[];
  assessment_type: string;
  ranked_labels: string[];
  display_label: string | null;
  epistemic_notice?: string;
  hypotheses: ACHHypothesisItem[];
  evidence_matrix: ACHEvidenceMatrixRow[];
  unobserved_indicators: string[];
  unobserved_details?: UnobservedIndicatorDetail[];
  observations?: Record<string, number>;
}

export interface HypothesisReportResponse {
  case_id: string;
  case_number: string;
  target_entity: string;
  leading_hypothesis: string;
  report_title: string;
  report_text: string;
  statutory_basis: string;
}

export interface RankedAction {
  action_code: string;
  title?: string;
  description: string;
  category: string;
  statutory_basis?: string;
  target?: Record<string, any>;
  status: "ready" | "blocked_missing_fields";
  missing_fields?: string[];
  urgency_factor?: number;
  decay_half_life_hours?: number;
  time_remaining_hours?: number;
  window_phase?: string;
  latency_hours?: number;
  friction_cost?: number;
  utility_score?: number;
  draft?: string | null;
  banner?: string;
  gap?: string;
  why?: string;
  resolves?: string;
  information_value?: string;
  severity?: string;
  entity_refs?: string[];
  event_refs?: string[];
  evidence_refs?: string[];
  components?: Record<string, number>;
  // Backwards compatibility aliases
  action?: string;
  instructions?: string;
  urgency_score?: number;
}

export interface NextBestActionsResponse {
  case_id: string;
  elapsed_hours: number;
  golden_hours: number;
  window_phase?: string;
  urgency_factor: number;
  financial_exposure?: number;
  summary?: {
    total_actions: number;
    ready_count: number;
    blocked_count: number;
    gaps_count: number;
    window_phase: string;
    financial_exposure: number;
  };
  evidence_gaps_summary?: string[];
  ranked_actions: RankedAction[];
}

export interface ActionDraftResponse {
  action_code: string;
  statute: string;
  banner: string;
  notice_text: string;
  generated_at: string;
}

export interface MOStageEvidenceItem {
  event_id?: string;
  evidence_file_id?: string;
  filename?: string;
  timestamp?: string;
  source_type?: string;
  sender?: string;
  matched_text?: string;
  line_no?: number;
}

export interface MOStageAlignment {
  stage: string;
  in_playbook: boolean;
  expected_position: number | null;
  observed_position: number | null;
  status: "MATCHED_IN_ORDER" | "MATCHED_OUT_OF_ORDER" | "MISSING" | "UNEXPECTED_STAGE";
  evidence_count: number;
  supporting_evidence?: MOStageEvidenceItem[];
}

export interface MOCalculationBreakdown {
  formula: string;
  levenshtein_distance: number;
  observed_length: number;
  expected_length: number;
  coverage_ratio: number;
  raw_similarity: number;
  threshold: number;
  is_confident: boolean;
}

export interface MOMatch {
  playbook: string;
  description?: string;
  source: string;
  similarity: number;
  levenshtein_distance?: number;
  coverage_ratio?: number;
  observed_sequence?: string[];
  expected_sequence?: string[];
  alignment: MOStageAlignment[];
  stage_evidence?: Record<string, MOStageEvidenceItem[]>;
  calculation_breakdown?: MOCalculationBreakdown;
  epistemic_status: string;
  is_confident?: boolean;
}

export interface MOPlaybookSummary {
  name: string;
  description?: string;
  source?: string;
  stages?: string[];
  stages_count?: number;
  stage_count?: number;
  detector_stages?: string[];
}

export interface MOFingerprintResponse {
  case_id: string;
  case_number?: string;
  verdict: string;
  threshold?: number;
  observed_sequence: string[];
  observed_stages_count?: number;
  matches: MOMatch[];
  best_match: MOMatch | null;
  candidate_best?: MOMatch | null;
  trace_evidence: Array<Record<string, unknown>>;
  all_stage_evidence?: Record<string, Record<string, MOStageEvidenceItem[]>>;
  judicial_notice?: {
    statutory_standard: string;
    epistemic_tier: string;
    disclaimer: string;
    r_v_t_compliance: string;
    corroboration_required: boolean;
  };
  available_playbooks?: MOPlaybookSummary[];
  note: string;
}

export interface PlaybooksCatalogResponse {
  total_playbooks: number;
  playbooks: MOPlaybookSummary[];
  judicial_notice?: Record<string, unknown>;
}

export interface CounterfactualCandidate {
  account: string;
  total_inbound: number;
  total_outbound: number;
  total_volume: number;
  txn_count: number;
  first_seen: string;
  last_seen: string;
  suggested_freeze_time: string;
}

export interface CounterfactualCandidatesResponse {
  case_id: string;
  total_candidates: number;
  candidates: CounterfactualCandidate[];
}

export interface TimelinessSweepStep {
  offset_minutes: number;
  offset_label: string;
  freeze_time: string;
  preserved_total: number;
  preservation_ratio: number;
  preservation_percentage: number;
  blocked_debits: number;
  stopped_credits: number;
  starved_attempts: number;
  status: "CRITICAL" | "EXTENDED" | "DECAYED";
}

export interface CounterfactualTransferEvent {
  from: string;
  to: string;
  amount: number;
  timestamp: string;
  reason?: string;
  status?: string;
  preserved?: boolean;
}

export interface CounterfactualResponse {
  case_id: string;
  intervention: {
    account?: string | string[];
    freeze_time?: string;
  };
  preserved_total: number;
  assessment_type: string;
  blocked_debits: number;
  stopped_credits: number;
  completed_transfers: number;
  blocked_out_events: CounterfactualTransferEvent[];
  stopped_in_events: CounterfactualTransferEvent[];
  unfunded_attempts?: CounterfactualTransferEvent[];
  stage_1_observed?: {
    total_observed_volume: number;
    total_transfers_count: number;
    active_accounts_count: number;
    first_transfer_time: string | null;
    last_transfer_time: string | null;
    duration_hours: number;
  };
  stage_2_intervention?: {
    target_accounts: string[];
    freeze_time: string;
    freeze_time_ist: string;
    statutory_basis: string;
    intervention_type: string;
    epistemic_status: string;
  };
  stage_3_simulated?: {
    blocked_out_events: CounterfactualTransferEvent[];
    stopped_in_events: CounterfactualTransferEvent[];
    unfunded_attempts: CounterfactualTransferEvent[];
    completed_transfers_count: number;
    simulated_balances: Record<string, number>;
    node_classifications: Record<string, string>;
  };
  stage_4_comparison?: {
    preserved_total: number;
    dissipated_total: number;
    preservation_ratio: number;
    preservation_percentage: number;
    blocked_debits_count: number;
    stopped_credits_count: number;
    starved_attempts_count: number;
    starved_accounts: string[];
    completed_count: number;
    capital_delta_preserved: number;
    capital_delta_lost: number;
  };
  node_classifications?: Record<string, string>;
  timeliness_sweep?: TimelinessSweepStep[];
  frames?: any[];
  caveats?: string[];
  epistemic_notice?: string;
}

export interface ReplayEdge {
  id: string;
  u: string;
  v: string;
  age_s?: number;
  opacity: number;
  rel_type?: string;
  amount?: number | null;
  event_id?: string;
  evidence_file_id?: string;
  source_doc?: string;
  source_line?: number;
  source_page?: number;
  text?: string;
  w?: number;
  event_type?: string;
}

export interface ReplayFrameEvent {
  event_id?: string;
  timestamp: string;
  u?: string;
  v?: string;
  node?: string;
  event_type?: string;
  rel_type?: string;
  amount?: number | null;
  source_doc?: string;
  source_line?: number;
  text?: string;
}

export interface ReplayFrame {
  t?: string;
  t_start: string;
  t_end: string;
  nodes: string[];
  edges: ReplayEdge[];
  burst?: boolean;
  new_events?: ReplayFrameEvent[];
  summary: {
    burst?: boolean;
    active_nodes?: number;
    active_edges?: number;
    new_events_count?: number;
    [key: string]: unknown;
  };
}

export interface NetworkReplayResponse {
  case_id: string;
  total_events: number;
  total_frames: number;
  frames: ReplayFrame[];
}

export interface SyndicateMemberCase {
  case_id: string;
  case_number: string;
  case_title: string;
  crime_type: string;
  police_station: string;
}

export interface SyndicateSharedToken {
  blind_token: string;
  entity_type: string;
  case_count: number;
  syndicate_score: number;
}

export interface SyndicateCluster {
  cluster_id: string;
  name: string;
  risk_level: "CRITICAL" | "ELEVATED" | "MONITORED";
  total_score: number;
  cohesion_score: number;
  case_count: number;
  token_count: number;
  threat_indicators: string[];
  cases: SyndicateMemberCase[];
  shared_tokens: SyndicateSharedToken[];
}

export interface RadarBlip {
  id: string;
  label: string;
  blip_type: "SYNDICATE_CLUSTER" | "COLLIDING_ENTITY";
  r: number;
  theta: number;
  risk_level: "CRITICAL" | "ELEVATED" | "MONITORED";
  entity_type?: string;
  case_count: number;
  score: number;
  touches_target: boolean;
  name?: string;
  threat_indicators?: string[];
  blind_token?: string;
}

export interface ForeignCaseMatch {
  case_id: string;
  case_number: string;
  case_title: string;
  crime_type: string;
  police_station: string;
  degree: number;
  redacted_value: string;
}

export interface LocalAnchor {
  has_local_anchor: boolean;
  plaintext_value: string;
  entity_id?: string | null;
  provenance: {
    source_file?: string;
    file_id?: string | null;
    source_page?: number | null;
    source_line?: number | null;
    event_type?: string;
    event_timestamp?: string | null;
  };
  first_seen?: string | null;
  last_seen?: string | null;
}

export interface SyndicateCollisionItem {
  blind_token: string;
  entity_type: string;
  case_count: number;
  syndicate_score: number;
  local_anchor: LocalAnchor;
  foreign_cases: ForeignCaseMatch[];
  note: string;
}

export interface SyndicateRadarResponse {
  case_id: string;
  case_number?: string;
  case_title?: string;
  crime_type?: string;
  police_station?: string;
  total_entities_screened: number;
  total_collisions: number;
  total_syndicate_clusters: number;
  max_syndicate_score: number;
  overall_threat_level: "CRITICAL" | "ELEVATED" | "CLEAR";
  syndicates: SyndicateCluster[];
  collisions: SyndicateCollisionItem[];
  radar_blips: RadarBlip[];
  privacy_boundary: {
    status: string;
    statutory_basis: string;
    description: string;
  };
  epistemic_notice: string;
}

export interface CrossCaseCollision {
  entity_type: string;
  blind_token: string;
  cases: string[];
  case_ids?: string[];
  case_count?: number;
  degree_sum?: number;
  syndicate_score?: number;
}

export interface CrossCaseResponse {
  total_entities_indexed: number;
  total_collisions: number;
  total_syndicates?: number;
  collisions: CrossCaseCollision[];
  syndicates?: SyndicateCluster[];
  note: string;
}

export interface LegalCitationSpan {
  raw_span: string;
  span_start: number;
  span_end: number;
  section: string;
  base_section: string;
  subsection?: string | null;
  act?: string | null;
  status: "in_force" | "pre_transition_act" | "struck_down" | "unknown_section" | "ambiguous_reference";
  title?: string | null;
  replaces?: string | null;
  replacement?: string | null;
  judicial_authority?: string | null;
  mandatory_notes?: string | null;
}

export interface GroundedSpan {
  claim_type: string;
  raw_value: string;
  normalized_value: string;
  span_start: number;
  span_end: number;
  grounded: boolean;
  detail?: string;
}

export interface EvidenceIntegrityAudit {
  total_files: number;
  hashed_files: number;
  unhashed_files: number;
  processed_files: number;
  has_custody_memo: boolean;
  integrity_score: number;
  status: "VERIFIED_INTEGRITY" | "DEFICIENT_INTEGRITY";
  warnings: string[];
  custody_memo_details?: {
    file_id?: string;
    original_name?: string;
    sha256_hash?: string;
  } | null;
}

export interface CaseComplianceShieldResponse {
  case_id: string;
  case_number: string;
  overall_status: "COMPLIANT" | "NEEDS_REVIEW" | "GOVERNANCE_BLOCKED";
  admissibility_disclaimer: string;
  evidence_integrity: EvidenceIntegrityAudit | null;
  statutory_compliance: {
    statutory_framework: string;
    transition_date: string;
    total_citations_audited: number;
    in_force_count: number;
    legacy_citations_count: number;
    struck_down_citations_count: number;
    citations: LegalCitationSpan[];
  };
  governance_posture: {
    verdict: string;
    active_blocks: number;
    active_warnings: number;
    reasons: string[];
  };
}

export interface VerificationFlag {
  check: string;
  severity: string;
  message: string;
}

export interface VerifyDraftResponse {
  passed: boolean;
  governance_verdict?: "COMPLIANT" | "NEEDS_REVIEW" | "GOVERNANCE_BLOCKED";
  governance_reasons?: string[];
  flags?: VerificationFlag[];
  citations?: LegalCitationSpan[];
  grounded_spans?: GroundedSpan[];
  grounding_failures?: Array<{ claim_type: string; value: string; detail?: string; span_start?: number; span_end?: number }>;
  statutory_violations?: Array<{ section: string; act?: string; reason: string; detail?: string; replacement?: string }>;
  canned_detections?: Array<{ similarity: number; detail?: string }>;
  evidence_integrity?: EvidenceIntegrityAudit | null;
  admissibility_disclaimer?: string;
  correction_instructions?: string;
  checked_items?: number;
  summary?: string;
}

export interface BenchmarkCase {
  case_id: string;
  db_case_id?: string;
  typology: string;
  entities_count: number;
  flow_edges_count: number;
  hidden_links_count: number;
  noise_entities_count: number;
  ground_truth: {
    typology: string;
    seed: number;
    entities: string[];
    hidden_links: Array<[string, string]>;
    key_account: string;
  };
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export const cognitiveApi = {
  /** Feature 02: Contradictions — ledger audit + impossible travel */
  contradictions: (caseId: string) =>
    apiClient.get<ContradictionsResponse>(`/cognitive/cases/${caseId}/contradictions`),

  /** Feature 02: Behavioral Anomalies & Entity Profiles */
  anomalies: (caseId: string) =>
    apiClient.get<AnomaliesResponse>(`/cognitive/cases/${caseId}/anomalies`),

  /** Feature 04: Hypotheses — ACH suspect role classification & Heuer matrix */
  hypotheses: (caseId: string, targetEntity?: string) => {
    const q = targetEntity ? `?target_entity=${encodeURIComponent(targetEntity)}` : "";
    return apiClient.get<HypothesesResponse>(`/cognitive/cases/${caseId}/hypotheses${q}`);
  },

  /** Feature 04: Hypothesis Investigation Board alias */
  hypothesisBoard: (caseId: string, targetEntity?: string) => {
    const q = targetEntity ? `?target_entity=${encodeURIComponent(targetEntity)}` : "";
    return apiClient.get<HypothesesResponse>(`/cognitive/cases/${caseId}/hypothesis-board${q}`);
  },

  /** Feature 04: Evaluate Hypothesis What-If Sandbox */
  evaluateHypothesisWhatIf: (
    caseId: string,
    payload: {
      target_entity?: string;
      observations: Record<string, number>;
      priors?: Record<string, number>;
    }
  ) =>
    apiClient.post<HypothesesResponse>(`/cognitive/cases/${caseId}/hypothesis-evaluate`, payload),

  /** Feature 04: Generate Section 193 BNSS Prosecution Hypothesis Memorandum */
  generateHypothesisReport: (
    caseId: string,
    payload: {
      target_entity?: string;
      leading_hypothesis?: string;
      officer_rank?: string;
      police_station?: string;
    }
  ) =>
    apiClient.post<HypothesisReportResponse>(`/cognitive/cases/${caseId}/hypothesis-report`, payload),

  /** Feature 06: Next-Best Actions & Golden Hours Action Center */
  nextBestActions: (caseId: string) =>
    apiClient.get<NextBestActionsResponse>(`/cognitive/cases/${caseId}/next-best-actions`),

  /** Feature 06: Generate Pre-filled Statutory Notice Draft */
  actionDraft: (caseId: string, actionCode: string, target: Record<string, any> = {}) =>
    apiClient.post<ActionDraftResponse>(`/cognitive/cases/${caseId}/actions/${actionCode}/draft`, { target }),

  /** Feature 07: MO Fingerprint — crime script playbook matching */
  moFingerprint: (caseId: string, threshold?: number, playbook?: string) => {
    const params = new URLSearchParams();
    if (threshold !== undefined && threshold !== null) params.append("threshold", String(threshold));
    if (playbook) params.append("playbook", playbook);
    const qs = params.toString() ? `?${params.toString()}` : "";
    return apiClient.get<MOFingerprintResponse>(`/cognitive/cases/${caseId}/mo-fingerprint${qs}`);
  },

  /** Feature 07: Get Playbooks Catalog */
  getPlaybooks: () =>
    apiClient.get<PlaybooksCatalogResponse>("/cognitive/playbooks"),

  /** Feature 07: Interactively classify ad-hoc transcript or text */
  classifyMoScript: (caseId: string, payload: { messages?: Array<Record<string, unknown>>; text_content?: string; threshold?: number; playbook?: string }) =>
    apiClient.post<MOFingerprintResponse>(`/cognitive/cases/${caseId}/mo-classify`, payload),

  /** Feature 08: What-If Freeze Sandbox — candidate accounts */
  counterfactualCandidates: (caseId: string) =>
    apiClient.get<CounterfactualCandidatesResponse>(`/cognitive/cases/${caseId}/counterfactual-candidates`),

  /** Feature 08: Counterfactual Freeze — 4-stage what-if simulation */
  counterfactualFreeze: (
    caseId: string,
    freezeAccount: string,
    freezeTime: string,
    additionalAccounts: string[] = [],
    includeSweep = true,
    includeFrames = false
  ) =>
    apiClient.post<CounterfactualResponse>(`/cognitive/cases/${caseId}/counterfactual-freeze`, {
      freeze_account: freezeAccount,
      freeze_time: freezeTime,
      additional_freeze_accounts: additionalAccounts,
      include_sweep: includeSweep,
      include_frames: includeFrames,
    }),

  /** Feature 10: Network Replay — CTDG animation frames */
  networkReplay: (caseId: string, stepSeconds = 300, tauSeconds = 1800) =>
    apiClient.get<NetworkReplayResponse>(
      `/cognitive/cases/${caseId}/network-replay?step_seconds=${stepSeconds}&tau_seconds=${tauSeconds}`
    ),

  /** Feature 03: Syndicate Radar — Cross-case blind index & criminal network detection */
  syndicateRadar: (caseId: string) =>
    apiClient.get<SyndicateRadarResponse>(`/cognitive/cases/${caseId}/syndicate-radar`),

  /** Feature 03: Cross-Case Collisions — zero-knowledge blind index */
  crossCaseCollisions: () =>
    apiClient.get<CrossCaseResponse>(`/cognitive/cross-case/collisions`),

  /** Feature 09: Legal Compliance Shield — Case Admissibility & Statutory Audit */
  complianceShield: (caseId: string) =>
    apiClient.get<CaseComplianceShieldResponse>(`/cognitive/cases/${caseId}/compliance-shield`),

  /** Feature 09: Verify Draft — deterministic output verifier */
  verifyDraft: (draftText: string, caseId?: string) =>
    apiClient.post<VerifyDraftResponse>(`/cognitive/verify-draft`, {
      draft_text: draftText,
      case_id: caseId,
    }),

  /** Feature 11: Benchmark Generator — synthetic test case */
  generateBenchmark: (typology = "DIGITAL_ARREST", seed = 42) =>
    apiClient.post<BenchmarkCase>(`/cognitive/benchmark/generate`, { typology, seed }),

  /** Feature 11: Training Simulator — List available training drill missions */
  listTrainingDrills: () =>
    apiClient.get<{ drills: TrainingDrillSummary[] }>(`/cognitive/training/drills`),

  /** Feature 11: Training Simulator — Start a new training session */
  startTrainingSession: (drillId?: string, seed?: number, difficulty?: string) =>
    apiClient.post<TrainingSessionResponse>(`/cognitive/training/start`, {
      drill_id: drillId,
      seed,
      difficulty,
    }),

  /** Feature 11: Training Simulator — Get active training session state */
  getTrainingSession: (sessionId: string) =>
    apiClient.get<TrainingSessionResponse>(`/cognitive/training/${sessionId}`),

  /** Feature 11: Training Simulator — Run NETRA cognitive engines for AI hints */
  getTrainingEngineHints: (sessionId: string) =>
    apiClient.post<TrainingEngineHintsResponse>(`/cognitive/training/${sessionId}/engine-hints`),

  /** Feature 11: Training Simulator — Submit answers for grading and debrief */
  submitTrainingAnswers: (sessionId: string, answers: Record<string, string>) =>
    apiClient.post<{ session_id: string; evaluation: TrainingEvaluation }>(
      `/cognitive/training/${sessionId}/submit`,
      { answers }
    ),

  /** Feature 11: Training Simulator — Get solution and full ground truth */
  getTrainingSolution: (sessionId: string) =>
    apiClient.get<TrainingSessionResponse>(`/cognitive/training/${sessionId}/solution`),

  /** Feature 11: Training Simulator — Export training case to database sandbox */
  exportTrainingCase: (sessionId: string) =>
    apiClient.post<{ message: string; case_id: string; case_number: string }>(
      `/cognitive/training/${sessionId}/export-case`
    ),

  /** Defence Bot: Adversarial Defensibility Audit */
  defenceAudit: (caseId: string) =>
    apiClient.get<DefenceAuditResponse>(`/cognitive/cases/${caseId}/defence-audit`),

  /** Defence Bot: On-demand cross-examination simulator */
  defenceStressTest: (caseId: string, claim: string, topK = 5) =>
    apiClient.post<DefenceStressTestResponse>(`/cognitive/cases/${caseId}/defence-stress-test`, {
      claim,
      top_k: topK,
    }),

  /** Feature 05: Confidence Meter & Evidentiary State Analyzer */
  confidenceMeter: (caseId: string, epsilon = 0.05, targetEntity?: string) => {
    const params = new URLSearchParams();
    params.set("epsilon", String(epsilon));
    if (targetEntity) params.set("target_entity", targetEntity);
    return apiClient.get<ConfidenceMeterResponse>(`/cognitive/cases/${caseId}/confidence-meter?${params.toString()}`);
  },

  /** Feature 05: Custom Conformal Prediction Set Evaluation */
  evaluateConfidence: (
    caseId: string,
    candidateScores: Record<string, number>,
    epsilon = 0.05,
    modelName = "ROLE_CLASSIFIER_CONFORMAL"
  ) =>
    apiClient.post<ConformalEvaluationResponse>(`/cognitive/cases/${caseId}/confidence-evaluate`, {
      model_name: modelName,
      candidate_scores: candidateScores,
      epsilon,
    }),

  /** Feature 05: List Conformal Calibrations */
  getCalibrations: () =>
    apiClient.get<{ calibrations: ConformalCalibrationItem[] }>(`/cognitive/conformal-calibrations`),
};

export interface DefenceChallenge {
  challenge_id: string;
  target_hypothesis: string;
  target_entity: string;
  defense_counter_hypothesis: string;
  reasonable_doubts: string[];
  missing_evidence: Array<{ item: string; reason: string; statutory_rule: string }>;
  statutory_vulnerabilities: Array<{ statute: string; issue: string; defense_challenge: string }>;
  rebuttal_strategy: Array<{ action_code: string; statute: string; recommendation: string }>;
  vulnerability_severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  epistemic_status: string;
  confidence: number;
  evidence_refs: string[];
  event_refs: string[];
  citations: any[];
  created_at: string;
}

export interface DefenceAuditResponse {
  case_id: string;
  defensibility_score: number;
  risk_level: "HIGH_RISK" | "MODERATE_RISK" | "LOW_RISK";
  total_hypotheses_tested: number;
  challenges: DefenceChallenge[];
  missing_evidence_summary: Array<{ item: string; reason: string; statutory_rule: string; severity: string; target_entity: string }>;
  bsa_compliance_status: {
    preservation_score: number;
    total_files: number;
    hashed_files: number;
    has_seizure_memo: boolean;
    compliant_with_bsa_63: boolean;
  };
  rebuttal_action_plan: Array<{ action_code: string; statute: string; recommendation: string }>;
  epistemic_notice: string;
}

export interface DefenceStressTestResponse {
  answer: string;
  citations: any[];
  retrieved_snippets: any[];
  model_used: string;
  is_generated: boolean;
  adversarial_posture: string;
  epistemic_notice: string;
  verification?: any;
}

export interface ConformalCoverageGuarantee {
  statement: string;
  valid_for_real_data: boolean;
  guarantee_status: "VALID_REAL" | "SYNTHETIC_BENCHMARK_ONLY";
}

export interface ConformalCalibrationItem {
  model_name: string;
  source: string;
  sample_size: number;
  quantile_threshold: number;
  epsilon: number;
  target_coverage: number;
  coverage_guarantee: ConformalCoverageGuarantee;
}

export interface FindingConfidenceBreakdown {
  finding_id: string;
  finding_type: string;
  title: string;
  severity: string;
  raw_score: number | null;
  score_type: string;
  epistemic_tier: "DIRECT_OBSERVATION" | "RULE_BASED" | "INFERRED" | "SCREENING" | "SIMULATION";
  tier_description: string;
  corroboration: {
    evidence_file_types: string[];
    evidence_count: number;
    distinct_source_types_count: number;
    is_multi_source: boolean;
  };
  contradiction_burden: {
    active_contradictions_count: number;
    has_contradiction_burden: boolean;
    penalty: number;
  };
  conformal_assessment: {
    applicable: boolean;
    model_name?: string;
    target_coverage?: number;
    prediction_set?: string[];
    verdict?: "SINGLE_LABEL" | "AMBIGUOUS_SET" | "OUT_OF_DISTRIBUTION";
    message?: string;
    valid_for_real_data?: boolean;
  };
}

export interface SuspectConformalSet {
  target_entity: string;
  prediction_set: string[];
  verdict: "SINGLE_LABEL" | "AMBIGUOUS_SET" | "OUT_OF_DISTRIBUTION";
  message: string;
  non_conformity_scores: Record<string, number>;
  quantile_threshold: number;
  epsilon: number;
  target_coverage: number;
  valid_for_real_data: boolean;
}

export interface ConfidenceMeterResponse {
  case_id: string;
  generated_at: string;
  overall_evidentiary_health_score: number;
  overall_verdict: "ROBUST_CORROBORATED" | "PROCEED_WITH_CAUTION" | "HIGH_UNCERTAINTY";
  findings_audit: {
    total_findings: number;
    multi_source_corroborated: number;
    contradiction_burdened: number;
    tier_distribution: Record<string, number>;
  };
  finding_breakdowns: FindingConfidenceBreakdown[];
  suspect_role_conformal_sets: SuspectConformalSet[];
  judicial_notices: {
    rvt_compliance: string;
    bnss_statutory_note: string;
    synthetic_calibration_warning: string;
  };
}

export interface ConformalEvaluationResponse {
  case_id: string;
  model_name: string;
  calibration: ConformalCalibrationItem;
  evaluation: {
    prediction_set: string[];
    verdict: "SINGLE_LABEL" | "AMBIGUOUS_SET" | "OUT_OF_DISTRIBUTION";
    message: string;
    epsilon: number;
    target_coverage: number;
    valid_for_real_data: boolean;
  };
}

/* ── Feature 11: Training Simulator Types ──────────────────────────────── */

export interface TrainingDrillSummary {
  id: string;
  title: string;
  typology: string;
  difficulty: "BEGINNER" | "INTERMEDIATE" | "ADVANCED";
  incident_brief: string;
  default_seed: number;
  tasks_count: number;
  planted_defects: string[];
}

export interface TrainingTaskOption {
  id: string;
  label: string;
}

export interface TrainingTask {
  task_id: string;
  pillar: "typology" | "hidden_links" | "legal_rigor" | "action_priority";
  prompt: string;
  points: number;
  options: TrainingTaskOption[];
}

export interface TrainingArtifactSummary {
  type: "text" | "table";
  length_chars?: number;
  lines_count?: number;
  rows_count?: number;
  preview?: any;
  raw?: any;
}

export interface TrainingTaskEvaluation {
  task_id: string;
  pillar: string;
  prompt: string;
  selected_option: string | null;
  selected_label: string;
  correct_option: string;
  correct_label: string;
  is_correct: boolean;
  points_earned: number;
  max_points: number;
  pedagogical_lesson: string;
  netra_engine_finding: string;
}

export interface TrainingPillarScore {
  earned: number;
  max: number;
}

export interface TrainingEvaluation {
  score_pct: number;
  total_points_earned: number;
  total_points_possible: number;
  readiness_tier: "MASTER_INVESTIGATOR" | "LEAD_CYBER_INVESTIGATOR" | "PROFICIENT_OFFICER" | "NOVICE_IN_TRAINING";
  tier_title: string;
  tier_badge: string;
  tier_description: string;
  pillar_breakdown: Record<string, TrainingPillarScore>;
  task_evaluations: TrainingTaskEvaluation[];
  statutory_recap: string[];
  evaluated_at: string;
}

export interface TrainingSessionResponse {
  session_id: string;
  drill_id: string;
  title: string;
  typology: string;
  difficulty: string;
  incident_brief: string;
  seed: number;
  created_at: string;
  has_hints: boolean;
  is_evaluated: boolean;
  tasks: TrainingTask[];
  artifacts: Record<string, TrainingArtifactSummary>;
  statutory_notice: string;
  evaluation?: TrainingEvaluation;
  ground_truth?: Record<string, any>;
  solution_tasks?: any[];
}

export interface TrainingEngineHintsResponse {
  session_id: string;
  hints: {
    mo_engine: {
      verdict: string;
      best_playbook: string | null;
      similarity: number;
      observed_stages: string[];
    };
    contradiction_engine: {
      ledger_anomalies_count: number;
      findings: any[];
    };
    defence_bot_engine: {
      defensibility_score: number;
      risk_level: string;
      bsa_status: any;
      challenges_count: number;
      top_challenge: {
        counter_hypothesis: string | null;
        target_entity: string | null;
      };
    };
    nextbest_engine: {
      top_action: string | null;
      statutory_basis: string | null;
    };
  };
}


