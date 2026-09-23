/**
 * CyberDrishti AI / NETRA V5 — Offline Synchronization API Client
 * Manages downloading complete case snapshots, batching offline mutations,
 * and resolving conflicting offline adjudications.
 */

import { apiClient } from './client';
import type {
  OfflineBundleResponse,
  SyncBatchRequest,
  SyncBatchResponse,
  SyncConflict,
  ConflictResolutionRequest,
  ConflictResolutionResponse,
} from '../types/sync';

/**
 * Fetch full case snapshot bundle for offline client initialization.
 * Strictly read-only on server (Invariant 2).
 */
export async function getOfflineBundle(caseId: string): Promise<OfflineBundleResponse> {
  return apiClient.get<OfflineBundleResponse>(`/cases/${caseId}/offline-bundle`);
}

/**
 * Push offline mutation batch to server for evaluation, rebase, or conflict detection.
 */
export async function syncOfflineMutations(
  caseId: string,
  payload: SyncBatchRequest
): Promise<SyncBatchResponse> {
  return apiClient.post<SyncBatchResponse>(`/cases/${caseId}/sync`, payload);
}

/**
 * List pending synchronization conflicts requiring investigator adjudication.
 */
export async function getPendingConflicts(caseId: string): Promise<SyncConflict[]> {
  return apiClient.get<SyncConflict[]>(`/cases/${caseId}/conflicts`);
}

/**
 * Adjudicate a synchronization conflict (KEEP_SERVER, APPLY_OFFLINE, CREATE_NEW_REVIEW).
 */
export async function resolveSyncConflict(
  caseId: string,
  conflictId: string,
  payload: ConflictResolutionRequest
): Promise<ConflictResolutionResponse> {
  return apiClient.post<ConflictResolutionResponse>(
    `/cases/${caseId}/conflicts/${conflictId}/resolve`,
    payload
  );
}
