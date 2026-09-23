import React, { useState, useEffect, useCallback } from "react";
import { entities as fallbackEntities } from "../../../data/entities";
import { useLiveStore } from "../../../state/useLiveStore";
import { entitiesApi } from "../../../api/entities";
import type {
  EntitySummary,
  IdentityCandidateQueueItem,
} from "../../../types/entities";
import { EntityExplorer } from "./EntityExplorer";
import { IdentityConflictPanel } from "./IdentityConflictPanel";
import { Icon } from "../../../components/icons";
import { Button } from "../../../components/primitives/Button";
import s from "./EntityExplorer.module.css";

const ENTITY_TYPES = ["ALL", "PER", "PHONE", "ACCOUNT", "UPI", "DEVICE", "ORG", "EMAIL"];

export function EntitiesTab({ onOpenEvidence }: { onOpenEvidence: () => void }) {
  const { activeCase } = useLiveStore();
  const caseId = activeCase?.uuid || activeCase?.id || "";

  // State
  const [viewMode, setViewMode] = useState<"entities" | "conflicts">("entities");
  const [search, setSearch] = useState("");
  const [selectedType, setSelectedType] = useState("ALL");
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  // Live Backend Data
  const [entities, setEntities] = useState<EntitySummary[]>([]);
  const [candidates, setCandidates] = useState<IdentityCandidateQueueItem[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [canResolve, setCanResolve] = useState(true);
  const [caseStateVersion, setCaseStateVersion] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch Entities & Candidates from API
  const fetchData = useCallback(async () => {
    if (!caseId) {
      setEntities([]);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      // 1. Fetch entities
      const entRes = await entitiesApi.listEntities(caseId, {
        search: search.trim() || undefined,
        entity_type: selectedType !== "ALL" ? selectedType : undefined,
      });
      setEntities(entRes.entities);
      setCaseStateVersion(entRes.case_state_version);

      // 2. Fetch identity candidate queue
      const candRes = await entitiesApi.listIdentityCandidates(caseId, "ALL");
      setCandidates(candRes.candidates);
      setPendingCount(candRes.pending_count);
      setCanResolve(candRes.capabilities?.can_resolve ?? true);
    } catch (err: unknown) {
      console.warn("Could not fetch entities from backend:", err);
      // If backend call fails, fallback to store or fallbackEntities
      if (fallbackEntities.length > 0) {
        setEntities(
          fallbackEntities.map((e) => ({
            id: e.id,
            canonical_value: e.name,
            entity_type: e.kind,
            epistemic_status: "OBSERVED",
            first_seen: null,
            last_seen: null,
            mention_count: e.mentionCount || 1,
            relationship_count: 1,
            degree_centrality: 0.1,
            bridge_score: 0.05,
            has_candidate_conflict: false,
            aliases: [],
          }))
        );
      }
      setError("Note: Operating in local offline mode or failed to reach live case server.");
    } finally {
      setLoading(false);
    }
  }, [caseId, search, selectedType]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Candidate resolved callback
  const handleCandidateResolved = () => {
    fetchData();
  };

  const displayedEntities = entities;

  return (
    <div className={s.container}>
      {/* View Switcher & Toolbar */}
      <div className={s.toolbar}>
        <div style={{ display: "flex", gap: "var(--space-4)", alignItems: "center", flexWrap: "wrap" }}>
          {/* View Mode Switcher */}
          <div className={s.viewSwitcher}>
            <button
              type="button"
              className={`${s.viewBtn} ${viewMode === "entities" ? s.viewBtnActive : ""}`}
              onClick={() => setViewMode("entities")}
            >
              <span>All Entities</span>
              <span className="t-mono-xs" style={{ opacity: 0.7 }}>
                ({displayedEntities.length})
              </span>
            </button>
            <button
              type="button"
              className={`${s.viewBtn} ${viewMode === "conflicts" ? s.viewBtnActive : ""}`}
              onClick={() => setViewMode("conflicts")}
            >
              <span>Identity Conflicts</span>
              {pendingCount > 0 && (
                <span className={s.badgePending}>{pendingCount}</span>
              )}
            </button>
          </div>

          {/* Search Box (in entities mode) */}
          {viewMode === "entities" && (
            <div className={s.searchBox}>
              <Icon name="search" size={14} />
              <input
                type="text"
                placeholder="Search canonical identity or alias..."
                className={s.searchInput}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          )}
        </div>

        {/* Action Button */}
        <div>
          <Button variant="secondary" icon="plus" onClick={onOpenEvidence}>
            Ingest Evidence Artifact
          </Button>
        </div>
      </div>

      {/* KPI Overview Banner */}
      <div className={s.kpiGrid}>
        <div className={s.kpiCard}>
          <span className={s.kpiLabel}>Identified Entities</span>
          <span className={s.kpiValue}>{entities.length}</span>
          <span className={s.kpiSub}>Tracked across case corpus</span>
        </div>
        <div className={s.kpiCard}>
          <span className={s.kpiLabel}>Identity Conflicts</span>
          <span className={s.kpiValue} style={{ color: pendingCount > 0 ? "var(--warning)" : "var(--verified)" }}>
            {pendingCount}
          </span>
          <span className={s.kpiSub}>
            {pendingCount > 0 ? "Require investigator review" : "All candidates adjudicated"}
          </span>
        </div>
        <div className={s.kpiCard}>
          <span className={s.kpiLabel}>Epistemic Invariant</span>
          <span className={s.kpiValue} style={{ fontSize: "16px", color: "var(--intel)", marginTop: "4px" }}>
            Candidate ≠ Confirmed
          </span>
          <span className={s.kpiSub}>No automatic similarity merges</span>
        </div>
      </div>

      {/* VIEW 1: All Entities Grid */}
      {viewMode === "entities" && (
        <>
          {/* Entity Type Filter Chips */}
          <div className={s.filterChips}>
            <span className="t-mono-xs" style={{ color: "var(--text-muted)", marginRight: "var(--space-2)" }}>
              TYPE:
            </span>
            {ENTITY_TYPES.map((type) => (
              <button
                key={type}
                type="button"
                className={`${s.chip} ${selectedType === type ? s.chipActive : ""}`}
                onClick={() => setSelectedType(type)}
              >
                {type}
              </button>
            ))}
          </div>

          {loading && (
            <div style={{ padding: "var(--space-12)", textAlign: "center", color: "var(--text-muted)" }}>
              Loading case entities...
            </div>
          )}

          {!loading && displayedEntities.length === 0 && (
            <div
              style={{
                padding: "var(--space-12) var(--space-6)",
                textAlign: "center",
                background: "var(--surface-1)",
                border: "1px dashed var(--line-strong)",
                borderRadius: "var(--radius-card)",
              }}
            >
              <div
                style={{
                  font: "var(--type-mono-xs)",
                  color: "var(--intel)",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  marginBottom: "var(--space-2)",
                }}
              >
                Entity Intelligence Pipeline
              </div>
              <h3 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
                No Entities Found
              </h3>
              <p
                className="measure"
                style={{
                  color: "var(--text-secondary)",
                  font: "var(--type-body-sm)",
                  margin: "0 auto var(--space-6) auto",
                }}
              >
                {search || selectedType !== "ALL"
                  ? "No entities match the current search or type filter criteria."
                  : "Entities (suspect persons, phone numbers, bank accounts, UPI VPAs, and devices) are automatically extracted when evidence files are ingested."}
              </p>
              <Button variant="primary" icon="plus" onClick={onOpenEvidence}>
                Ingest Evidence to Extract Entities
              </Button>
            </div>
          )}

          {!loading && displayedEntities.length > 0 && (
            <div className={s.entityGrid}>
              {displayedEntities.map((e) => (
                <div
                  key={e.id}
                  className={`${s.entityCard} ${e.has_candidate_conflict ? s.entityCardConflict : ""}`}
                  onClick={() => setSelectedEntityId(e.id)}
                >
                  <div className={s.cardHead}>
                    <span className={s.typeBadge}>{e.entity_type}</span>
                    <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                      {e.has_candidate_conflict && (
                        <span
                          className={s.badgePending}
                          title="Open Identity Conflict pending adjudication"
                        >
                          CONFLICT
                        </span>
                      )}
                      <span className={`${s.epistemicBadge} ${s[`epistemic${e.epistemic_status}`] || ""}`}>
                        {e.epistemic_status}
                      </span>
                    </div>
                  </div>

                  <div className={s.cardTitle}>{e.canonical_value}</div>

                  {e.aliases && e.aliases.length > 0 && (
                    <div className={s.aliasList}>
                      {e.aliases.map((al, idx) => (
                        <span key={idx} className={s.aliasChip}>
                          aka {al}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className={s.cardStats}>
                    <span>{e.mention_count} mentions</span>
                    <span>{e.relationship_count} links</span>
                    <span>Centrality: {(e.degree_centrality * 100).toFixed(0)}%</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {/* VIEW 2: Identity Conflict Review Queue */}
      {viewMode === "conflicts" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <div
            style={{
              padding: "var(--space-4)",
              background: "var(--surface-1)",
              border: "1px solid var(--line)",
              borderRadius: "6px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "var(--space-3)",
            }}
          >
            <div>
              <h4 style={{ font: "600 15px var(--font-sans)", color: "var(--text-primary)", marginBottom: "4px" }}>
                Identity Conflict Adjudication Queue
              </h4>
              <p style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)", margin: 0 }}>
                Review ambiguous entity extractions and cognitive similarity candidates. Human adjudication preserves strict audit integrity.
              </p>
            </div>
            <div className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
              Pending: {pendingCount} | Total Candidates: {candidates.length}
            </div>
          </div>

          {candidates.length === 0 ? (
            <div
              style={{
                padding: "var(--space-12)",
                textAlign: "center",
                background: "var(--surface-1)",
                border: "1px dashed var(--line)",
                borderRadius: "var(--radius-card)",
              }}
            >
              <div style={{ fontSize: "28px", marginBottom: "var(--space-2)" }}>✓</div>
              <h4 style={{ font: "var(--type-title-3)", color: "var(--text-primary)", marginBottom: "var(--space-2)" }}>
                Zero Identity Conflicts Pending
              </h4>
              <p style={{ color: "var(--text-secondary)", font: "var(--type-body-sm)", maxWidth: "480px", margin: "0 auto" }}>
                All extracted entities have either distinct authoritative canonical identities or have already been adjudicated by an investigator.
              </p>
            </div>
          ) : (
            candidates.map((cand) => (
              <IdentityConflictPanel
                key={cand.id}
                candidate={cand}
                caseId={caseId}
                caseStateVersion={caseStateVersion}
                canResolve={canResolve}
                onResolved={handleCandidateResolved}
                onSelectEntity={(id) => setSelectedEntityId(id)}
              />
            ))
          )}
        </div>
      )}

      {/* Slide-over Deep Entity Dossier Drawer */}
      {selectedEntityId && (
        <EntityExplorer
          caseId={caseId}
          entityId={selectedEntityId}
          onClose={() => setSelectedEntityId(null)}
          onSelectEntity={(id) => setSelectedEntityId(id)}
          onOpenEvidence={onOpenEvidence}
          onCandidateResolved={handleCandidateResolved}
        />
      )}
    </div>
  );
}
