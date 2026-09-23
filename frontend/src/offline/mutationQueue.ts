/**
 * CyberDrishti AI / NETRA V5 — Client Offline Mutation Queue
 * Manages queued offline command envelopes awaiting server synchronization.
 * Invariant: Offline commands, not offline truth.
 */

import type { OfflineMutationEnvelope } from '../types/sync';
import { getDeviceId, getClientStateVersion } from './db';

const QUEUE_KEY_PREFIX = 'netra_offline_mut_queue_';

/**
 * Retrieve all pending mutations for a case, sorted by local sequence.
 */
export function getQueuedMutations(caseId: string): OfflineMutationEnvelope[] {
  try {
    const raw = localStorage.getItem(`${QUEUE_KEY_PREFIX}${caseId}`);
    if (!raw) return [];
    const list: OfflineMutationEnvelope[] = JSON.parse(raw);
    return list.sort((a, b) => a.local_sequence - b.local_sequence);
  } catch (err) {
    console.error('[MutationQueue] Error reading queue:', err);
    return [];
  }
}

/**
 * Enqueue a new strongly-typed mutation envelope.
 */
export function enqueueMutation(
  caseId: string,
  actorId: string,
  commandType: string,
  payload: Record<string, any>
): OfflineMutationEnvelope {
  const currentQueue = getQueuedMutations(caseId);
  const nextSeq = currentQueue.length > 0 ? Math.max(...currentQueue.map((m) => m.local_sequence)) + 1 : 1;
  const currentBaseVersion = getClientStateVersion(caseId);

  const envelope: OfflineMutationEnvelope = {
    mutation_id: `mut_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`,
    device_id: getDeviceId(),
    actor_id: actorId,
    case_id: caseId,
    base_state_version: currentBaseVersion,
    client_created_at: new Date().toISOString(),
    command_type: commandType,
    payload,
    local_sequence: nextSeq,
  };

  currentQueue.push(envelope);
  localStorage.setItem(`${QUEUE_KEY_PREFIX}${caseId}`, JSON.stringify(currentQueue));
  return envelope;
}

/**
 * Remove successfully accepted or rebased mutations from queue.
 */
export function removeMutations(caseId: string, mutationIdsToRemove: string[]): void {
  const set = new Set(mutationIdsToRemove);
  const remaining = getQueuedMutations(caseId).filter((m) => !set.has(m.mutation_id));
  localStorage.setItem(`${QUEUE_KEY_PREFIX}${caseId}`, JSON.stringify(remaining));
}

/**
 * Get count of pending offline mutations for a case.
 */
export function getQueuedMutationCount(caseId: string): number {
  return getQueuedMutations(caseId).length;
}

/**
 * Clear all pending mutations for a case.
 */
export function clearMutationQueue(caseId: string): void {
  localStorage.removeItem(`${QUEUE_KEY_PREFIX}${caseId}`);
}
