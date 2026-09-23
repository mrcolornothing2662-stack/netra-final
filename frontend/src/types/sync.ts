export interface OfflineMutationEnvelope {
  mutation_id: string;
  device_id: string;
  actor_id: string;
  case_id: string;
  base_state_version: number;
  client_created_at: string;
  command_type: string;
  payload: Record<string, any>;
  local_sequence: number;
}

export interface SyncConflict {
  conflict_id: string;
  mutation_id: string;
  command_type: string;
  conflict_type: string;
  client_payload: Record<string, any>;
  server_current_state: Record<string, any>;
  base_state_version: number;
  server_state_version: number;
  status: 'PENDING_REVIEW' | 'RESOLVED_KEEP_SERVER' | 'RESOLVED_APPLY_OFFLINE' | 'DISCARDED';
  created_at?: string;
  resolved_at?: string;
  resolution_rationale?: string;
}

export interface SyncRejection {
  mutation_id: string;
  error_code: string;
  detail: string;
}

export interface SyncProjectionDelta {
  from_version: number;
  to_version: number;
  relationships: any[];
  identity_candidates: any[];
  findings: any[];
  activities: any[];
}

export interface SyncBatchRequest {
  device_id: string;
  client_state_version: number;
  mutations: OfflineMutationEnvelope[];
}

export interface SyncBatchResponse {
  device_id: string;
  accepted: string[];
  rebased: string[];
  rejected: SyncRejection[];
  conflicts: SyncConflict[];
  server_state_version: number;
  projection_delta?: SyncProjectionDelta;
}

export interface OfflineBundleResponse {
  case: any;
  server_state_version: number;
  entities: any[];
  relationships: any[];
  evidence_metadata: any[];
  evidence_events: any[];
  findings: any[];
  hypotheses: any[];
  activities: any[];
  identity_candidates: any[];
  state_replay_index: any[];
  exported_at: string;
}

export interface ConflictResolutionRequest {
  resolution: 'KEEP_SERVER' | 'APPLY_OFFLINE' | 'CREATE_NEW_REVIEW';
  rationale: string;
}

export interface ConflictResolutionResponse {
  success: boolean;
  conflict_id: string;
  status: string;
  server_state_version: number;
  message: string;
}
