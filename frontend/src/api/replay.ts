/**
 * Investigation Replay API Client.
 * Strictly read-only calls for time-travel state reconstruction.
 */

import { apiClient } from './client';
import type { ReplayIndexResponse, HistoricalStateProjection } from '../types/timeline';

export async function getReplayIndex(caseId: string): Promise<ReplayIndexResponse> {
  return apiClient.get<ReplayIndexResponse>(`/cases/${caseId}/replay`);
}

export async function getHistoricalState(
  caseId: string,
  version: number
): Promise<HistoricalStateProjection> {
  return apiClient.get<HistoricalStateProjection>(`/cases/${caseId}/replay/${version}`);
}
