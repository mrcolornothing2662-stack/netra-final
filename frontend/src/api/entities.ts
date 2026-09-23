/**
 * CyberDrishti AI — Entity Explorer & Identity Resolution API (V5 Milestone 3)
 */
import { apiClient } from "./client";
import type {
  EntityListResponse,
  EntityDossierResponse,
  IdentityCandidatesQueueResponse,
  CandidateResolutionPayload,
  CandidateResolutionResponse,
} from "../types/entities";

export interface ListEntitiesParams {
  search?: string;
  entity_type?: string;
  epistemic_status?: "OBSERVED" | "INFERRED" | "INVESTIGATOR_ADDED";
  limit?: number;
  offset?: number;
}

export const entitiesApi = {
  /**
   * Search and filter entities for a case with mention counts, relationships, and conflict flags.
   */
  listEntities: (caseId: string, params?: ListEntitiesParams): Promise<EntityListResponse> => {
    const searchParams = new URLSearchParams();
    if (params?.search) searchParams.set("search", params.search);
    if (params?.entity_type) searchParams.set("entity_type", params.entity_type);
    if (params?.epistemic_status) searchParams.set("epistemic_status", params.epistemic_status);
    if (params?.limit !== undefined) searchParams.set("limit", String(params.limit));
    if (params?.offset !== undefined) searchParams.set("offset", String(params.offset));

    const qs = searchParams.toString();
    return apiClient.get<EntityListResponse>(`/cases/${caseId}/entities${qs ? `?${qs}` : ""}`);
  },

  /**
   * Deep entity dossier: identity header, provenance, mentions with page/line citations,
   * chronological events, canonical & analytical relationships, and candidate conflicts.
   */
  getEntityDossier: (caseId: string, entityId: string): Promise<EntityDossierResponse> => {
    return apiClient.get<EntityDossierResponse>(`/cases/${caseId}/entities/${entityId}`);
  },

  /**
   * Identity conflict review queue with structured match and conflicting signals.
   */
  listIdentityCandidates: (
    caseId: string,
    resolutionStatus: "ALL" | "UNRESOLVED" | "CONFIRMED_SAME" | "CONFIRMED_DIFFERENT" | "REJECTED" = "ALL"
  ): Promise<IdentityCandidatesQueueResponse> => {
    return apiClient.get<IdentityCandidatesQueueResponse>(
      `/cases/${caseId}/identity-candidates?resolution_status=${resolutionStatus}`
    );
  },

  /**
   * Resolve an identity candidate (CONFIRMED_SAME / CONFIRMED_DIFFERENT / REJECTED)
   * Dispatched through the Investigation Brain Command Gateway.
   */
  resolveIdentityCandidate: (
    caseId: string,
    candidateId: string,
    payload: CandidateResolutionPayload
  ): Promise<CandidateResolutionResponse> => {
    return apiClient.post<CandidateResolutionResponse>(
      `/cases/${caseId}/identity-candidates/${candidateId}/resolve`,
      payload
    );
  },
};
