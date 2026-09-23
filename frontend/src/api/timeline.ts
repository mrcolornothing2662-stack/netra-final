/**
 * Timeline API Client for unified incident and investigation streams.
 */

import { apiClient } from './client';
import type { TimelineResponse, TimelineMode } from '../types/timeline';

export interface TimelineQueryOptions {
  mode?: TimelineMode;
  category?: string;
  limit?: number;
  offset?: number;
}

export async function getUnifiedTimeline(
  caseId: string,
  options: TimelineQueryOptions = {}
): Promise<TimelineResponse> {
  const params = new URLSearchParams();
  if (options.mode) params.set('mode', options.mode);
  if (options.category && options.category !== 'ALL') params.set('category', options.category);
  if (options.limit) params.set('limit', String(options.limit));
  if (options.offset) params.set('offset', String(options.offset));

  const queryStr = params.toString() ? `?${params.toString()}` : '';
  return apiClient.get<TimelineResponse>(`/cases/${caseId}/timeline${queryStr}`);
}

export async function getCaseActivity(caseId: string, limit: number = 50) {
  return apiClient.get<{ case_id: string; total: number; activities: any[] }>(
    `/cases/${caseId}/activity?limit=${limit}`
  );
}
