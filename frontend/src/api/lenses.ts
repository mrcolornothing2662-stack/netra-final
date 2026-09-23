/**
 * CyberDrishti AI / NETRA V5 — Forensic Lenses API Client
 * Provides strictly read-only access to Money Trail, Communications,
 * and Travel/Geographic lenses over the Investigation Brain.
 */

import { apiClient } from './client';
import type {
  ForensicLensResponse,
  LensOverviewResponse,
  ForensicLensType,
} from '../types/lenses';

export interface LensQueryOptions {
  entityId?: string;
  startTime?: string;
  endTime?: string;
  stateVersion?: number;
}

/**
 * Fetch overview summary across all three forensic lenses.
 */
export async function getLensesOverview(caseId: string): Promise<LensOverviewResponse> {
  return apiClient.get<LensOverviewResponse>(`/cases/${caseId}/lenses`);
}

/**
 * Fetch domain-specific lens projection (MONEY, COMMUNICATION, GEOGRAPHIC).
 */
export async function getForensicLens(
  caseId: string,
  lensType: ForensicLensType,
  options: LensQueryOptions = {}
): Promise<ForensicLensResponse> {
  const endpointMap: Record<ForensicLensType, string> = {
    MONEY: 'money',
    COMMUNICATION: 'communications',
    GEOGRAPHIC: 'geographic',
  };

  const endpoint = endpointMap[lensType] || lensType.toLowerCase();
  const params = new URLSearchParams();

  if (options.entityId) params.set('entity_id', options.entityId);
  if (options.startTime) params.set('start_time', options.startTime);
  if (options.endTime) params.set('end_time', options.endTime);
  if (options.stateVersion !== undefined && options.stateVersion !== null) {
    params.set('state_version', String(options.stateVersion));
  }

  const queryStr = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<ForensicLensResponse>(`/cases/${caseId}/lenses/${endpoint}${queryStr}`);
}

/**
 * Fetch entity-focused lens projection.
 */
export async function getEntityFocusedLens(
  caseId: string,
  lensType: ForensicLensType,
  entityId: string,
  options: Omit<LensQueryOptions, 'entityId'> = {}
): Promise<ForensicLensResponse> {
  const params = new URLSearchParams();
  if (options.startTime) params.set('start_time', options.startTime);
  if (options.endTime) params.set('end_time', options.endTime);
  if (options.stateVersion !== undefined && options.stateVersion !== null) {
    params.set('state_version', String(options.stateVersion));
  }

  const queryStr = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<ForensicLensResponse>(
    `/cases/${caseId}/lenses/${lensType.toLowerCase()}/entity/${encodeURIComponent(entityId)}${queryStr}`
  );
}
