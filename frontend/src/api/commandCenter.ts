/**
 * CyberDrishti AI / NETRA V5 — Investigation Command Center API Client
 * Provides strictly read-only access to the consolidated Command Center projection.
 */

import { apiClient } from './client';
import type { CommandCenterProjection } from '../types/commandCenter';

/**
 * Fetch unified Command Center projection for an investigation.
 * Strictly read-only on the server.
 */
export async function getCommandCenter(caseId: string): Promise<CommandCenterProjection> {
  return apiClient.get<CommandCenterProjection>(`/cases/${caseId}/command-center`);
}
