import { apiClient } from "./client";

export interface Citation {
  rank: number;
  file: string;
  line: string;
  page: string;
  text: string;
  verified: boolean;
  epistemic_status?: string;
}

export interface RetrievedSnippet {
  id: string;
  rank: number;
  text: string;
  file: string;
  line: string;
  score: number;
}

export interface CopilotResponse {
  answer: string;
  raw_answer?: string;
  citations: Citation[];
  observed_facts?: string[];
  inferred_facts?: string[];
  retrieved_snippets?: RetrievedSnippet[];
  model_used: string;
  provider?: string;
  is_generated?: boolean;
  fallback_used?: boolean;
  abstained?: boolean;
  grounded_ratio?: number;
  grounded_claim_ratio?: number;
  citation_count?: number;
  latency_ms?: number;
  stage_latencies?: {
    retrieval_ms: number;
    context_ms: number;
    generation_ms: number;
    verification_ms: number;
    total_ms: number;
  };
  status?: string;
  warning?: string | null;
  verification?: {
    passed: boolean;
    abstained: boolean;
    grounded_ratio: number;
    flags: Array<{ severity: string; check: string; message: string }>;
  };
  diagnostics?: {
    intent?: string;
    target_modalities?: string[];
    retrieval?: any;
  };
}

export const copilotApi = {
  ask: (caseId: string, question: string, topK = 10): Promise<CopilotResponse> =>
    apiClient.post<CopilotResponse>(`/copilot/${caseId}`, { question, top_k: topK }),

  status: () =>
    apiClient.get<{
      ollama_online: boolean;
      available_models?: string[];
      status?: string;
      model_used: string;
      provider?: string;
    }>("/copilot/status"),
};
