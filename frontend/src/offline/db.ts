/**
 * CyberDrishti AI / NETRA V5 — Client Offline Projection Store
 * Stores downloaded case bundles, entity graphs, and state versions locally
 * so investigators can operate completely disconnected in field conditions.
 */

import type { OfflineBundleResponse, SyncProjectionDelta } from '../types/sync';

const DEVICE_ID_KEY = 'netra_offline_device_id';
const BUNDLE_KEY_PREFIX = 'netra_offline_bundle_';
const VERSION_KEY_PREFIX = 'netra_offline_ver_';

/**
 * Get or generate a persistent unique Device ID for this client.
 */
export function getDeviceId(): string {
  let devId = localStorage.getItem(DEVICE_ID_KEY);
  if (!devId) {
    const randomHex = Math.random().toString(36).substring(2, 10).toUpperCase();
    devId = `FIELD-DEV-${randomHex}`;
    localStorage.setItem(DEVICE_ID_KEY, devId);
  }
  return devId;
}

/**
 * Check whether a case is cached locally for offline investigation.
 */
export function isCaseCachedOffline(caseId: string): boolean {
  return !!localStorage.getItem(`${BUNDLE_KEY_PREFIX}${caseId}`);
}

/**
 * Get current client state version for a case.
 */
export function getClientStateVersion(caseId: string): number {
  const verStr = localStorage.getItem(`${VERSION_KEY_PREFIX}${caseId}`);
  return verStr ? parseInt(verStr, 10) : 1;
}

/**
 * Update local client state version for a case.
 */
export function setClientStateVersion(caseId: string, version: number): void {
  localStorage.setItem(`${VERSION_KEY_PREFIX}${caseId}`, version.toString());
}

/**
 * Persist downloaded offline bundle into local projection store.
 */
export async function storeOfflineBundle(
  caseId: string,
  bundle: OfflineBundleResponse
): Promise<void> {
  try {
    localStorage.setItem(`${BUNDLE_KEY_PREFIX}${caseId}`, JSON.stringify(bundle));
    setClientStateVersion(caseId, bundle.server_state_version);
  } catch (err) {
    console.warn('[OfflineStore] Failed to store bundle in localStorage:', err);
  }
}

/**
 * Retrieve cached offline bundle for a case.
 */
export async function getCachedOfflineBundle(
  caseId: string
): Promise<OfflineBundleResponse | null> {
  try {
    const raw = localStorage.getItem(`${BUNDLE_KEY_PREFIX}${caseId}`);
    if (!raw) return null;
    return JSON.parse(raw) as OfflineBundleResponse;
  } catch (err) {
    console.error('[OfflineStore] Error parsing cached bundle:', err);
    return null;
  }
}

/**
 * Apply server projection delta directly onto local cached bundle.
 */
export async function applyProjectionDelta(
  caseId: string,
  delta: SyncProjectionDelta
): Promise<void> {
  const bundle = await getCachedOfflineBundle(caseId);
  if (!bundle) return;

  // Merge updated relationships
  if (delta.relationships && delta.relationships.length > 0) {
    const relMap = new Map(bundle.relationships.map((r: any) => [r.id, r]));
    for (const r of delta.relationships) {
      relMap.set(r.id, { ...relMap.get(r.id), ...r });
    }
    bundle.relationships = Array.from(relMap.values());
  }

  // Merge updated identity candidates
  if (delta.identity_candidates && delta.identity_candidates.length > 0) {
    const candMap = new Map(bundle.identity_candidates.map((c: any) => [c.id, c]));
    for (const c of delta.identity_candidates) {
      candMap.set(c.id, { ...candMap.get(c.id), ...c });
    }
    bundle.identity_candidates = Array.from(candMap.values());
  }

  // Merge findings
  if (delta.findings && delta.findings.length > 0) {
    const findMap = new Map(bundle.findings.map((f: any) => [f.id, f]));
    for (const f of delta.findings) {
      findMap.set(f.id, { ...findMap.get(f.id), ...f });
    }
    bundle.findings = Array.from(findMap.values());
  }

  // Prepend recent activities
  if (delta.activities && delta.activities.length > 0) {
    const actIds = new Set(bundle.activities.map((a: any) => a.id));
    for (const a of delta.activities) {
      if (!actIds.has(a.id)) {
        bundle.activities.unshift(a);
      }
    }
  }

  bundle.server_state_version = delta.to_version;
  await storeOfflineBundle(caseId, bundle);
  setClientStateVersion(caseId, delta.to_version);
}

/**
 * Clear offline storage for a given case.
 */
export function clearOfflineCase(caseId: string): void {
  localStorage.removeItem(`${BUNDLE_KEY_PREFIX}${caseId}`);
  localStorage.removeItem(`${VERSION_KEY_PREFIX}${caseId}`);
}
