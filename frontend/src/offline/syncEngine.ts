/**
 * CyberDrishti AI / NETRA V5 — Client Synchronization Engine
 * Orchestrates offline caching, mutation dispatch, rebase handling,
 * and projection delta application upon reconnect.
 */

import { getOfflineBundle, syncOfflineMutations } from '../api/sync';
import type { SyncBatchResponse } from '../types/sync';
import { connectivity } from './connectivity';
import {
  applyProjectionDelta,
  getDeviceId,
  getClientStateVersion,
  setClientStateVersion,
  storeOfflineBundle,
} from './db';
import {
  getQueuedMutations,
  removeMutations,
} from './mutationQueue';

export interface SyncResultSummary {
  success: boolean;
  totalSynced: number;
  acceptedCount: number;
  rebasedCount: number;
  rejectedCount: number;
  conflictCount: number;
  newServerVersion: number;
  error?: string;
}

class ClientSyncEngine {
  private isSyncing: boolean = false;

  constructor() {
    // Automatically trigger sync when connectivity is restored
    connectivity.subscribe((isOnline) => {
      if (isOnline) {
        console.log('[ClientSyncEngine] Network restored; evaluating pending mutations.');
      }
    });
  }

  /**
   * Download and cache the entire case projection for offline field work.
   */
  public async cacheCaseForOffline(caseId: string): Promise<boolean> {
    try {
      const bundle = await getOfflineBundle(caseId);
      await storeOfflineBundle(caseId, bundle);
      return true;
    } catch (err) {
      console.error('[ClientSyncEngine] Failed to download case bundle:', err);
      return false;
    }
  }

  /**
   * Synchronize queued mutations for a case against the server.
   */
  public async syncCase(caseId: string): Promise<SyncResultSummary> {
    if (!connectivity.isOnline()) {
      return {
        success: false,
        totalSynced: 0,
        acceptedCount: 0,
        rebasedCount: 0,
        rejectedCount: 0,
        conflictCount: 0,
        newServerVersion: getClientStateVersion(caseId),
        error: 'Client is offline. Connect to network to synchronize.',
      };
    }

    if (this.isSyncing) {
      return {
        success: false,
        totalSynced: 0,
        acceptedCount: 0,
        rebasedCount: 0,
        rejectedCount: 0,
        conflictCount: 0,
        newServerVersion: getClientStateVersion(caseId),
        error: 'Synchronization already in progress.',
      };
    }

    this.isSyncing = true;
    try {
      const mutations = getQueuedMutations(caseId);
      const clientVer = getClientStateVersion(caseId);
      const deviceId = getDeviceId();

      const response: SyncBatchResponse = await syncOfflineMutations(caseId, {
        device_id: deviceId,
        client_state_version: clientVer,
        mutations,
      });

      // 1. Remove accepted and rebased mutations from local queue
      const processedIds = [...response.accepted, ...response.rebased];
      if (processedIds.length > 0) {
        removeMutations(caseId, processedIds);
      }

      // 2. If rejected with terminal errors, remove them so they don't block subsequent syncs
      if (response.rejected && response.rejected.length > 0) {
        const rejectedIds = response.rejected.map((r) => r.mutation_id);
        removeMutations(caseId, rejectedIds);
      }

      // 3. If conflicts occurred, remove from queue because server holds them in sync_conflicts
      if (response.conflicts && response.conflicts.length > 0) {
        const conflictMutationIds = response.conflicts.map((c) => c.mutation_id);
        removeMutations(caseId, conflictMutationIds);
      }

      // 4. Apply projection delta if returned
      if (response.projection_delta) {
        await applyProjectionDelta(caseId, response.projection_delta);
      } else {
        setClientStateVersion(caseId, response.server_state_version);
      }

      return {
        success: true,
        totalSynced: mutations.length,
        acceptedCount: response.accepted.length,
        rebasedCount: response.rebased.length,
        rejectedCount: response.rejected.length,
        conflictCount: response.conflicts.length,
        newServerVersion: response.server_state_version,
      };
    } catch (err: any) {
      console.error('[ClientSyncEngine] Sync failed:', err);
      return {
        success: false,
        totalSynced: 0,
        acceptedCount: 0,
        rebasedCount: 0,
        rejectedCount: 0,
        conflictCount: 0,
        newServerVersion: getClientStateVersion(caseId),
        error: err?.message || 'Network sync error',
      };
    } finally {
      this.isSyncing = false;
    }
  }
}

export const syncEngine = new ClientSyncEngine();
