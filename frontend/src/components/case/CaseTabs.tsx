import { useRef } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { EASE_OUT } from "../../lib/motion";
import s from "./case.module.css";

export const CASE_TABS = [
  { id: "overview", label: "Overview" },
  { id: "notes", label: "Notes" },
  { id: "evidence", label: "Evidence" },
  { id: "entities", label: "Entities" },
  { id: "network", label: "Network" },
  { id: "timeline", label: "Timeline" },
  { id: "analysis", label: "Copilot" },
  { id: "cognitive", label: "Cognitive" },
  { id: "agent", label: "Agent" },
  { id: "report", label: "Report" },
] as const;
export type CaseTabId = (typeof CASE_TABS)[number]["id"];

export function CaseTabs({ caseId, active }: { caseId: string; active: CaseTabId }) {
  const navigate = useNavigate();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    let nextIndex = index;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      nextIndex = (index + 1) % CASE_TABS.length;
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      nextIndex = (index - 1 + CASE_TABS.length) % CASE_TABS.length;
    } else if (e.key === "Home") {
      e.preventDefault();
      nextIndex = 0;
    } else if (e.key === "End") {
      e.preventDefault();
      nextIndex = CASE_TABS.length - 1;
    }

    if (nextIndex !== index) {
      tabRefs.current[nextIndex]?.focus();
      const viewEl = document.querySelector("main");
      if (viewEl) viewEl.scrollTop = 0;
      navigate(`/investigations/${caseId}/${CASE_TABS[nextIndex].id}`);
    }
  };

  const handleSelectTab = (tabId: string) => {
    const viewEl = document.querySelector("main");
    if (viewEl) viewEl.scrollTop = 0;
    navigate(`/investigations/${caseId}/${tabId}`);
  };

  return (
    <nav className={s.ctabs} role="tablist" aria-label="Investigation sections">
      {CASE_TABS.map((t, i) => {
        const isSelected = t.id === active;
        return (
          <button
            key={t.id}
            ref={el => { tabRefs.current[i] = el; }}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={isSelected}
            aria-controls={`panel-${t.id}`}
            tabIndex={isSelected ? 0 : -1}
            className={isSelected ? `${s.ctab} ${s.ctabOn}` : s.ctab}
            onClick={() => handleSelectTab(t.id)}
            onKeyDown={e => handleKeyDown(e, i)}
          >
            {t.label}
            {isSelected && (
              <motion.span
                layoutId="case-tab-line"
                className={s.ctabLine}
                transition={{ duration: 0.24, ease: EASE_OUT }}
              />
            )}
          </button>
        );
      })}
    </nav>
  );
}
