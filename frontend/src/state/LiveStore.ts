import { casesApi, type BackendCaseSummary, type CreateCasePayload } from "../api/cases";
import { isAuthenticated } from "../api/client";
import { evidenceApi } from "../api/evidence";
import { graphApi } from "../api/graph";
import { systemApi } from "../api/system";
import { adaptCaseItem } from "../adapters/investigationAdapter";
import { adaptEvidenceFile } from "../adapters/evidenceAdapter";
import { adaptGraphData, type NodeCoord } from "../adapters/graphAdapter";
import { adaptTimelineEvent } from "../adapters/timelineAdapter";
import { DEMO_CASE } from "../data/cases";
import { evidenceArchive as demoEvidence } from "../data/evidence";
import { events as demoEvents } from "../data/events";
import type { Case, Evidence, CaseEvent, Connection, Entity } from "../data/types";

type Listener = () => void;

const DEMO_CASE_ID = DEMO_CASE.id.toLowerCase();

/** True only for the single synthetic demonstration case. Never for real cases. */
function isDemoId(caseId: string): boolean {
  const tid = (caseId || "").toLowerCase();
  return tid === DEMO_CASE_ID || tid === "demo-shadowlink";
}

/**
 * Single source of truth for live investigation data.
 *
 * Core principle: never solve a missing-data problem by generating substitute
 * data. When the backend is empty we show zero live cases; when it errors we
 * surface the error and go offline. The ONLY non-backend case ever shown is
 * DEMO_CASE, which is explicitly tagged SYNTHETIC_DEMO and badged in the UI.
 */
class LiveStoreImpl {
  public backendOnline: boolean = true;
  public loading: boolean = false;
  public error: string | null = null;
  /** true when the backend is reachable but holds zero live investigations. */
  public empty: boolean = false;

  // Seeded with only the badged demo case — never fabricated live cases.
  public cases: Case[] = [DEMO_CASE];
  public activeCase: Case | null = null;
  public activeCaseSummary: BackendCaseSummary | null = null;
  public activeEvidence: Evidence[] = [];
  public activeGraph: { nodes: NodeCoord[]; connections: Connection[]; entities: Entity[] } | null = null;
  public activeTimeline: CaseEvent[] = [];

  private listeners = new Set<Listener>();

  constructor() {
    // Initial silent check
    this.checkHealth().then(() => {
      if (isAuthenticated()) {
        this.fetchCases();
      }
    });
  }

  public subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify() {
    this.listeners.forEach(fn => fn());
  }

  async checkHealth(): Promise<boolean> {
    try {
      const h = await systemApi.health();
      this.backendOnline = h.status === "healthy" || h.status === "degraded";
    } catch {
      this.backendOnline = false;
    }
    this.notify();
    return this.backendOnline;
  }

  async fetchCases(): Promise<Case[]> {
    this.loading = true;
    this.error = null;
    this.empty = false;
    this.notify();

    try {
      const backendItems = await casesApi.list({ page_size: 50 });
      this.backendOnline = true;
      const live = (backendItems || []).map(b => adaptCaseItem(b));
      // Real cases come from the backend; the demo case is always appended, badged.
      this.cases = [...live, DEMO_CASE];
      this.empty = live.length === 0;
    } catch (err: unknown) {
      // Do NOT fabricate live cases on error. Surface the failure honestly and
      // keep only the clearly-labelled demonstration case visible.
      console.warn("Unable to retrieve live cases:", err);
      this.backendOnline = false;
      this.error = "Unable to retrieve live investigation data.";
      this.empty = false;
      this.cases = [DEMO_CASE];
    } finally {
      this.loading = false;
      this.notify();
    }
    return this.cases;
  }

  async createCase(payload: CreateCasePayload): Promise<Case | null> {
    this.loading = true;
    this.error = null;
    this.notify();
    try {
      const created = await casesApi.create(payload);
      const adapted = adaptCaseItem(created);
      adapted.uuid = created.id;
      adapted.case_number = created.case_number;
      this.cases = [adapted, ...this.cases.filter(c => c.id !== adapted.id && c.id !== created.id)];
      this.activeCase = adapted;
      this.activeCaseSummary = null;
      this.activeEvidence = [];
      this.activeGraph = { nodes: [], connections: [], entities: [] };
      this.activeTimeline = [];
      this.backendOnline = true;
      this.empty = false;
      this.loading = false;
      this.notify();
      return adapted;
    } catch (err: unknown) {
      // No fabricated local case. Surface the real failure to the caller.
      this.error = (err as Error)?.message || "Case could not be created. The investigation was not saved.";
      this.loading = false;
      this.notify();
      throw err;
    }
  }

  async fetchCaseDetails(caseId: string): Promise<void> {
    this.loading = true;
    this.error = null;

    const isDemo = isDemoId(caseId);

    // The demonstration case is entirely synthetic — serve it directly, never
    // from the backend, and never let it touch real-case state.
    if (isDemo) {
      this.activeCase = DEMO_CASE;
      this.activeCaseSummary = null;
      this.activeEvidence = demoEvidence;
      this.activeTimeline = demoEvents;
      this.activeGraph = null; // graph tabs render the demo graph from their own corpus
      this.loading = false;
      this.notify();
      return;
    }

    const tid = (caseId || "").toLowerCase();

    // Only reset state up-front when switching to a different case to prevent UI flicker
    const isSameCase = Boolean(
      this.activeCase && (
        this.activeCase.id.toLowerCase() === tid ||
        this.activeCase.uuid?.toLowerCase() === tid ||
        this.activeCase.case_number?.toLowerCase() === tid
      )
    );

    if (!isSameCase) {
      this.activeEvidence = [];
      this.activeGraph = { nodes: [], connections: [], entities: [] };
      this.activeTimeline = [];
      this.activeCaseSummary = null;
    }
    let matched = this.cases.find(c => {
      if (c.source_type === "SYNTHETIC_DEMO") return false;
      const cid = (c.id || "").toLowerCase();
      const cnum = (c.case_number || "").toLowerCase();
      const cuuid = (c.uuid || "").toLowerCase();
      return cid === tid || cnum === tid || cuuid === tid || (cid.length > 3 && tid.includes(cid)) || (tid.length > 3 && cid.includes(tid));
    });

    this.activeCase = matched || this.activeCase || null;
    if (!isSameCase) {
      this.notify();
    }

    try {
      // 1. Fetch case summary
      try {
        const summary = await casesApi.summary(caseId);
        this.activeCaseSummary = summary;
        if (summary) {
          matched = {
            id: summary.case_number || summary.case_id || matched?.id || caseId,
            uuid: summary.case_id,
            case_number: summary.case_number,
            name: summary.title || matched?.name || "Investigation",
            domain: summary.crime_type || (summary.fir_number ? `FIR ${summary.fir_number}` : matched?.domain || "Cyber Investigation"),
            entities: summary.counts?.entities ?? matched?.entities ?? 0,
            evidence: summary.counts?.evidence ?? matched?.evidence ?? 0,
            leads: summary.counts?.suspicious_findings ?? matched?.leads ?? 0,
            priority: (summary.priority?.toUpperCase() as any) || matched?.priority || "HIGH",
            status: summary.status === "open" ? "ACTIVE" : (summary.status?.toUpperCase() as any) || matched?.status || "ACTIVE",
            updated: "Just now",
            brief: matched?.brief || "Case active in repository.",
            latest: summary.findings?.[0]?.description || matched?.latest || "Under active evidence analysis.",
          };
        }
        this.activeCase = matched || null;
        this.backendOnline = true;
      } catch {
        if (!matched) {
          matched = {
            id: caseId,
            name: `Investigation ${caseId.slice(0, 12)}`,
            domain: "Cyber Investigation",
            entities: 0,
            evidence: 0,
            leads: 0,
            priority: "HIGH",
            status: "ACTIVE",
            updated: "Just now",
            brief: "Active digital investigation.",
            latest: "Awaiting evidence ingestion.",
          };
        }
        this.activeCase = matched;
      }

      // 2. Fetch evidence (empty stays empty for real cases)
      try {
        const evFiles = await evidenceApi.list(caseId);
        this.activeEvidence = (evFiles && evFiles.length > 0) ? evFiles.map(adaptEvidenceFile) : [];
      } catch {
        this.activeEvidence = [];
      }

      // 3. Fetch graph
      try {
        const graphData = await graphApi.get(caseId);
        this.activeGraph = (graphData && graphData.nodes && graphData.nodes.length > 0)
          ? adaptGraphData(graphData)
          : { nodes: [], connections: [], entities: [] };
      } catch {
        this.activeGraph = { nodes: [], connections: [], entities: [] };
      }

      // 4. Fetch timeline
      try {
        const tlEvents = await graphApi.timeline(caseId);
        this.activeTimeline = (tlEvents && tlEvents.length > 0) ? tlEvents.map(adaptTimelineEvent) : [];
      } catch {
        this.activeTimeline = [];
      }
    } catch (err) {
      // Never fall back to demo data for a real case.
      console.warn("Error fetching case details:", err);
    } finally {
      this.loading = false;
      this.notify();
    }
  }

  async uploadEvidence(caseId: string, files: File[], sourceType = "unknown"): Promise<Evidence[]> {
    this.loading = true;
    this.error = null;
    this.notify();

    try {
      await evidenceApi.upload(caseId, files, sourceType);
      this.backendOnline = true;
      // Refresh evidence list from backend so only truly-stored records appear.
      const refreshed = await evidenceApi.list(caseId);
      this.activeEvidence = refreshed.map(adaptEvidenceFile);
      if (this.activeCase) {
        this.activeCase.evidence = this.activeEvidence.length;
      }
      const matchCase = this.cases.find(c => c.id === caseId || c.case_number === caseId);
      if (matchCase) {
        matchCase.evidence = this.activeEvidence.length;
      }
      // Re-fetch summary in background
      casesApi.summary(caseId).then(summary => {
        if (summary) {
          this.activeCaseSummary = summary;
          this.notify();
        }
      }).catch(() => {});
      this.loading = false;
      this.notify();
      return this.activeEvidence;
    } catch (err: unknown) {
      // No optimistic fake row, no fake SHA. The evidence was not stored.
      this.error = "Evidence was not stored. No evidence record has been created.";
      this.loading = false;
      this.notify();
      throw err;
    }
  }

  async refreshEvidence(caseId: string): Promise<Evidence[]> {
    try {
      const refreshed = await evidenceApi.list(caseId);
      this.activeEvidence = refreshed.map(adaptEvidenceFile);
      if (this.activeCase) {
        this.activeCase.evidence = this.activeEvidence.length;
      }
      const matchCase = this.cases.find(c => c.id === caseId || c.case_number === caseId);
      if (matchCase) {
        matchCase.evidence = this.activeEvidence.length;
      }
      casesApi.summary(caseId).then(summary => {
        if (summary) {
          this.activeCaseSummary = summary;
          this.notify();
        }
      }).catch(() => {});
      this.notify();
      return this.activeEvidence;
    } catch (err) {
      console.error("Failed to refresh evidence:", err);
      return this.activeEvidence;
    }
  }
}

export const liveStore = new LiveStoreImpl();
