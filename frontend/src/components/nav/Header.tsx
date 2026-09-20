import { useLocation, useOutletContext } from "react-router-dom";
import { Icon } from "../icons";
import { ThemeToggle } from "../common/ThemeToggle";
import { getStoredUser, logout } from "../../api/client";
import { useLiveStore } from "../../state/useLiveStore";
import s from "./nav.module.css";

const TITLES: Record<string, string> = {
  "/command": "Command Center",
  "/investigations": "Investigations",
  "/intelligence": "Intelligence",
  "/settings": "Settings",
};

function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function Header() {
  const context = useOutletContext<{ openPalette?: () => void }>();
  const openPalette = context?.openPalette;
  const { pathname } = useLocation();
  const { cases, backendOnline } = useLiveStore();

  const user = getStoredUser();
  const displayName = user?.full_name?.trim() || user?.username || "Investigator";
  const role = (user?.role || "").toUpperCase();

  const caseMatch = pathname.match(/^\/investigations\/([^/]+)/) || pathname.match(/^\/case\/([^/]+)/);
  const matchedId = caseMatch ? caseMatch[1] : undefined;
  // Resolve the active case from live store data only — never from a demo corpus.
  const activeCase = matchedId
    ? cases.find(c => {
        const cid = (c.id || "").toLowerCase();
        const mid = matchedId.toLowerCase();
        const cnum = (((c as any).case_number as string) || "").toLowerCase();
        return cid === mid || cnum === mid || (cid.length > 3 && mid.includes(cid)) || (mid.length > 3 && cid.includes(mid));
      })
    : undefined;

  return (
    <header className={s.header}>
      <div className={s.brand}>
        <span className={s.wordmark}>CYBERDRISHTI</span>
        <span className={s.sep}>/</span>
        <span className={s.context}>
          {activeCase ? (
            <><span className={s.contextSub}>Investigations / </span>{activeCase.name}</>
          ) : (
            TITLES[pathname] ?? "Intelligence Workspace"
          )}
        </span>
      </div>
      <div className={s.hdrRight}>
        {/* Backend Connectivity Indicator */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "4px 8px",
            background: "var(--surface-1)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-pill)",
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            color: backendOnline ? "var(--verified)" : "var(--warning)",
          }}
          title={backendOnline ? "Connected to live investigation backend" : "Backend unavailable — no live intelligence is being displayed"}
        >
          <span
            style={{
              width: "6px",
              height: "6px",
              borderRadius: "50%",
              background: backendOnline ? "var(--verified)" : "var(--warning)",
              display: "inline-block",
              boxShadow: backendOnline ? "0 0 6px var(--verified)" : "none",
            }}
          />
          <span>{backendOnline ? "LIVE CORE" : "OFFLINE"}</span>
        </div>

        <button className={s.searchBtn} onClick={openPalette} aria-label="Open command palette">
          <Icon name="search" size={16} />
          <span className={s.searchPh}>Search intelligence…</span>
          <kbd>⌘K</kbd>
        </button>

        <ThemeToggle />

        <div className={s.userCluster}>
          <span className={s.avatarInit} aria-hidden="true">{initialsOf(displayName)}</span>
          <span className={s.userInfo}>
            <span className={s.userName} title={displayName}>{displayName}</span>
            {role && <span className={s.userRole}>{role}</span>}
          </span>
          <button className={s.signout} onClick={() => logout()} aria-label="Sign out">
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
