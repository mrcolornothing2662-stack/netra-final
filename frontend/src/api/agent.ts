/**
 * CyberDrishti AI — Agent / ArmorIQ API Client
 *
 * Typed wrappers for the autonomous investigation endpoints.
 */
import { apiClient } from "./client";

/* ── Response Types ─────────────────────────────────────────────────────── */

export interface AgentLaunchResponse {
  session_id: string;
  case_id: string;
  case_number?: string;
  status: string;
  message: string;
  poll_url: string;
}

export interface AgentHoldInfo {
  hold_id: string;
  action: string;
  description: string;
  ai_reasoning: string;
  authorization_boundary: string;
  risk_level: string;
  affected_resource: Record<string, unknown> | null;
  armoriq_reason?: string;
  /** blocked_by_design → a governance decision, not a failure. */
  governance_outcome?: string;
  status: string;
  requested_at: string | null;
}

export interface AgentPlanStep {
  id: number;
  objective: string;
  status: string;
}

export interface AgentCaseSnapshot {
  evidence: number;
  events: number;
  entities: number;
  relationships: number;
  observed_relationships: number;
  inferred_relationships: number;
  findings: number;
  high_priority: number;
}

export interface AgentFinalReport {
  case_id: string;
  observed: string[];
  analytical_findings: Array<{ title: string; severity: string; type: string }>;
  unresolved: string[];
  recommended_next_actions: string[];
  governance: {
    high_impact_actions_executed: number;
    blocked_actions: number;
    pending_approvals: number;
    analytical_actions_executed: number;
  };
  investigation_plan?: AgentPlanStep[];
}

export interface AgentStatusResponse {
  session_id: string | null;
  case_id: string;
  status: string;
  actions: Array<Record<string, unknown>>;
  pending_hold: AgentHoldInfo | null;
  action_count: number;
  started_at?: string | null;
  completed_at?: string | null;
  message?: string;
  case_snapshot?: AgentCaseSnapshot | null;
  investigation_plan?: AgentPlanStep[];
  final_report?: AgentFinalReport | null;
}

export interface AgentActionItem {
  id: string;
  action_type: string;
  description: string;
  status: string;
  details: Record<string, unknown> | null;
  timestamp: string | null;
}

export interface AgentActionsResponse {
  case_id: string;
  actions: AgentActionItem[];
  total: number;
  executed: number;
  blocked: number;
  approved: number;
  rejected: number;
}

export interface HoldDecisionResponse {
  hold_id: string;
  status: string;
  approved_by?: string;
  rejected_by?: string;
  reason?: string;
  message: string;
}

export interface PendingHoldsResponse {
  pending_holds: AgentHoldInfo[];
  total: number;
}

export interface AuditChainEntry {
  id: number;
  action: string;
  entry_hash: string;
  prev_hash: string;
  details: Record<string, unknown> | null;
  timestamp: string | null;
  source: string;
}

export interface AgentAuditTrailResponse {
  case_id: string;
  agent_actions: Array<AgentActionItem & { source: string }>;
  sha256_chain_entries: AuditChainEntry[];
  totals: {
    agent_actions: number;
    sha256_chain_entries: number;
    executed: number;
    blocked: number;
    approved: number;
    rejected: number;
  };
}

export interface SandboxRule {
  id: string;
  rule_name: string;
  action_pattern: string;
  decision: string;
  priority: number;
  [key: string]: unknown;
}

export interface SandboxRulesResponse {
  rules: SandboxRule[];
  note: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export const agentApi = {
  /** Launch autonomous investigation for a case. */
  run: (caseId: string) =>
    apiClient.post<AgentLaunchResponse>(`/agent/${caseId}/run`),

  /** Get current agent status (poll during investigation). */
  status: (caseId: string, sessionId?: string) => {
    const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    return apiClient.get<AgentStatusResponse>(`/agent/${caseId}/status${q}`);
  },

  /** List all agent actions for a case. */
  actions: (caseId: string) =>
    apiClient.get<AgentActionsResponse>(`/agent/${caseId}/actions`),

  /** Approve a blocked hold. */
  approveHold: (holdId: string, reason?: string) =>
    apiClient.post<HoldDecisionResponse>(`/agent/holds/${holdId}/approve`, {
      reason: reason || "Human authorized",
    }),

  /** Reject a blocked hold. */
  rejectHold: (holdId: string, reason?: string) =>
    apiClient.post<HoldDecisionResponse>(`/agent/holds/${holdId}/reject`, {
      reason: reason || "Rejected by human reviewer",
    }),

  /** List all pending holds across all cases. */
  pendingHolds: () =>
    apiClient.get<PendingHoldsResponse>("/agent/holds"),

  /** Get ArmorIQ-enhanced audit trail for a case. */
  auditTrail: (caseId: string) =>
    apiClient.get<AgentAuditTrailResponse>(`/agent/${caseId}/audit-trail`),

  /** Get sandbox firewall rules. */
  sandboxRules: () =>
    apiClient.get<SandboxRulesResponse>("/agent/sandbox/rules"),
};
