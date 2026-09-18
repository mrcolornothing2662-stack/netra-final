import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Block, tabSwap } from "../../app/transitions";
import { CaseTabs, type CaseTabId } from "../../components/case/CaseTabs";
import { StickyContextBar } from "../../components/case/StickyContextBar";
import { PriorityMark } from "../../components/primitives/PriorityMark";
import { Button } from "../../components/primitives/Button";
import { Overview } from "./tabs/Overview";
import { NotesTab } from "./tabs/NotesTab";
import { EvidenceTab } from "./tabs/EvidenceTab";
import { EntitiesTab } from "./tabs/EntitiesTab";
import { NetworkTab } from "./tabs/NetworkTab";
import { TimelineTab } from "./tabs/TimelineTab";
import { AnalysisTab } from "./tabs/AnalysisTab";
import { CognitiveTab } from "./tabs/CognitiveTab";
import { AgentTab } from "./tabs/AgentTab";
import { ReportTab } from "./tabs/ReportTab";
import { CaseEditModal } from "../../components/case/CaseEditModal";
import { caseById } from "../../data/corpus";
import { useFlipIn } from "../../lib/flip";
import { useLiveStore } from "../../state/useLiveStore";
import { DemoBadge } from "../../components/DemoBadge";
import type { Case } from "../../data/types";
import s from "../../components/case/case.module.css";

export function CaseScreen() {
  const { caseId, tab = "overview" } = useParams();
  const navigate = useNavigate();
  const titleRef = useRef<HTMLHeadingElement>(null);
  useFlipIn(titleRef);

  const { cases, activeCase, fetchCaseDetails } = useLiveStore();

  useEffect(() => {
    if (caseId) {
      fetchCaseDetails(caseId);
    }
  }, [caseId]);

  // Helper to match case by id or case_number case-insensitively
  const isMatch = (item?: Case | null, targetId?: string): boolean => {
    if (!item || !targetId) return false;
    const tid = targetId.toLowerCase();
    const itemId = (item.id || "").toLowerCase();
    const caseNum = (((item as any).case_number as string) || "").toLowerCase();
    return itemId === tid || caseNum === tid || (itemId.length > 3 && tid.includes(itemId)) || (tid.length > 3 && itemId.includes(tid));
  };

  const isDemo = caseId === "CYB-2026-042" || caseId === "demo-shadowlink";

  // No case selected — do not silently load the demonstration case.
  if (!caseId) {
    return (
      <div className="page">
        <Block>
          <div style={{
            padding: "var(--space-12) var(--space-6)", textAlign: "center",
            background: "var(--surface-1)", border: "1px dashed var(--line-strong)",
            borderRadius: "var(--radius-card)", marginTop: "var(--space-8)"
          }}>
            <h1 className="t-title-3" style={{ color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
              No investigation selected
            </h1>
            <p className="measure" style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", margin: "0 auto var(--space-6)" }}>
              Choose an investigation from the list, or open the clearly labelled synthetic demonstration case.
            </p>
            <Button variant="primary" onClick={() => navigate("/investigations")}>
              Go to investigations
            </Button>
          </div>
        </Block>
      </div>
    );
  }

  const defaultFallback: Case = {
    id: caseId,
    name: "Investigation Case",
    domain: "Cyber Investigation",
    entities: 0,
    evidence: 0,
    leads: 0,
    priority: "HIGH",
    status: "ACTIVE",
    updated: "Just now",
    brief: "Active digital investigation record.",
    latest: "Awaiting evidence ingestion.",
    user: false,
  };

  // Priority: activeCase (if matching) -> case from cases list -> demo corpus (demo only) -> honest empty shell
  const c = (activeCase && isMatch(activeCase, caseId))
    ? activeCase
    : cases.find(x => isMatch(x, caseId))
    ?? (isDemo ? caseById.get(caseId) : undefined)
    ?? (isDemo ? caseById.get("CYB-2026-042") : undefined)
    ?? defaultFallback;

  const showDemoBadge = isDemo || c.source_type === "SYNTHETIC_DEMO";

  const VALID_TABS: CaseTabId[] = ["overview", "notes", "evidence", "entities", "network", "timeline", "analysis", "cognitive", "agent", "report"];
  const activeTab: CaseTabId = VALID_TABS.includes(tab as CaseTabId) ? (tab as CaseTabId) : "overview";

  const [showEdit, setShowEdit] = useState(false);

  return (
    <div className="page">
      <StickyContextBar
        titleRef={titleRef}
        text={c.name}
        count={
          activeTab === "network" && (window as any).__netCounts
            ? `${(window as any).__netCounts.shown} of ${(window as any).__netCounts.total} entities`
            : `${c.evidence} items`
        }
        priority={c.priority}
        demo={showDemoBadge}
      />

      <Block>
        <div className={s.origin}>
          <div className={s.originMeta}>
            <span>{c.domain}</span>
            <span>{c.id}</span>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap" }}>
          <h1 ref={titleRef} className={`t-title-1 ${s.caseTitle}`} style={{ margin: 0 }}>{c.name}</h1>
          {showDemoBadge && <DemoBadge />}
          {!isDemo && (
            <button
              onClick={() => setShowEdit(true)}
              style={{ background: "none", border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "4px 10px", color: "var(--text-muted)", cursor: "pointer", font: "var(--type-mono-xs)", letterSpacing: "0.06em" }}
              title="Edit case details"
            >
              ✎ EDIT
            </button>
          )}
        </div>
        <div className={s.status}>
          <span className={s.dot} />
          <span>{c.status === "ACTIVE" ? "Active investigation" : c.status}</span>
          <span className={s.upd}>· Updated {c.updated}</span>
          <PriorityMark priority={c.priority} />
        </div>
      </Block>

      <CaseTabs caseId={c.id} active={activeTab} />

      <motion.div
        key={activeTab}
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
      >
        {activeTab === "overview" && <Overview caseData={c} />}
        {activeTab === "notes" && <NotesTab caseId={c.id} caseData={c} />}
        {activeTab === "evidence" && <EvidenceTab caseId={c.id} />}
        {activeTab === "entities" && <EntitiesTab onOpenEvidence={() => navigate(`/investigations/${c.id}/evidence`)} />}
        {activeTab === "network" && <NetworkTab caseId={c.id} />}
        {activeTab === "timeline" && <TimelineTab caseId={c.id} onOpenEvidence={() => navigate(`/investigations/${c.id}/evidence`)} />}
        {activeTab === "analysis" && <AnalysisTab caseId={c.id} onOpenEvidence={() => navigate(`/investigations/${c.id}/evidence`)} />}
        {activeTab === "cognitive" && <CognitiveTab caseId={c.id} />}
        {activeTab === "agent" && <AgentTab caseId={c.id} />}
        {activeTab === "report" && <ReportTab caseData={c} />}
      </motion.div>

      {showEdit && (
        <CaseEditModal
          caseId={c.id}
          current={{
            title: c.name,
            description: (c as any).description || (c as any).brief || "",
            status: c.status,
            priority: c.priority || undefined,
            crime_type: (c as any).crime_type || c.domain,
            fir_number: (c as any).fir_number || "",
            police_station: (c as any).police_station || "",
          }}
          onClose={() => setShowEdit(false)}
          onSaved={() => fetchCaseDetails(c.id)}
        />
      )}
    </div>
  );
}
