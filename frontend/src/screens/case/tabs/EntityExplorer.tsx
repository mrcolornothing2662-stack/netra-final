import React, { useEffect, useState } from "react";
import type { EntityDossierResponse } from "../../../types/entities";
import { entitiesApi } from "../../../api/entities";
import { IdentityConflictPanel } from "./IdentityConflictPanel";
import { Icon } from "../../../components/icons";
import s from "./EntityExplorer.module.css";

interface EntityExplorerProps {
  caseId: string;
  entityId: string;
  onClose: () => void;
  onSelectEntity?: (entityId: string) => void;
  onOpenEvidence?: (fileId?: string) => void;
  onCandidateResolved?: (candidateId: string, verdict: string) => void;
}

type ExplorerTab = "overview" | "mentions" | "relationships" | "conflicts" | "timeline";

export function EntityExplorer({
  caseId,
  entityId,
  onClose,
  onSelectEntity,
  onOpenEvidence,
  onCandidateResolved,
}: EntityExplorerProps) {
  const [data, setData] = useState<EntityDossierResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ExplorerTab>("overview");

  const loadDossier = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await entitiesApi.getEntityDossier(caseId, entityId);
      setData(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load entity dossier";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDossier();
  }, [caseId, entityId]);

  // Close drawer on ESC key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const handleChildCandidateResolved = (candidateId: string, verdict: string) => {
    loadDossier();
    if (onCandidateResolved) {
      onCandidateResolved(candidateId, verdict);
    }
  };

  return (
    <>
      <div className={s.drawerOverlay} onClick={onClose} />
      <div className={s.drawer} role="dialog" aria-modal="true">
        {/* Top Header */}
        <div className={s.drawerHeader}>
          <div className={s.drawerTopRow}>
            <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
              <span className={s.typeBadge}>
                {data?.entity.entity_type || "ENTITY"}
              </span>
              {data && (
                <span className={`${s.epistemicBadge} ${s[`epistemic${data.entity.epistemic_status}`] || ""}`}>
                  {data.entity.epistemic_status}
                </span>
              )}
            </div>
            <button
              type="button"
              className={s.closeBtn}
              onClick={onClose}
              aria-label="Close entity dossier"
            >
              <Icon name="close" size={16} />
            </button>
          </div>

          <h2 className={s.drawerTitle}>
            {loading ? "Loading Dossier..." : data?.entity.canonical_value || "Entity Dossier"}
          </h2>

          {data && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-3)", alignItems: "center" }}>
              <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                ID: {data.entity.id}
              </span>
              {data.entity.aliases && data.entity.aliases.length > 0 && (
                <div className={s.aliasList}>
                  <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>Aliases:</span>
                  {data.entity.aliases.map((al, idx) => (
                    <span key={idx} className={s.aliasChip}>
                      {al}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {data && (
            <div style={{ display: "flex", gap: "var(--space-6)", font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: "4px" }}>
              <span>Centrality: {(data.entity.degree_centrality * 100).toFixed(1)}%</span>
              <span>Bridge: {(data.entity.bridge_score * 100).toFixed(1)}%</span>
              <span>Mentions: {data.provenance.mention_count}</span>
              <span>Connections: {data.relationships.canonical_count + data.relationships.analytical_count}</span>
            </div>
          )}
        </div>

        {/* Tab Navigation */}
        <div className={s.drawerTabs}>
          <button
            type="button"
            className={`${s.drawerTab} ${activeTab === "overview" ? s.drawerTabActive : ""}`}
            onClick={() => setActiveTab("overview")}
          >
            Overview & Provenance
          </button>
          <button
            type="button"
            className={`${s.drawerTab} ${activeTab === "mentions" ? s.drawerTabActive : ""}`}
            onClick={() => setActiveTab("mentions")}
          >
            Mentions ({data?.mentions.length ?? 0})
          </button>
          <button
            type="button"
            className={`${s.drawerTab} ${activeTab === "relationships" ? s.drawerTabActive : ""}`}
            onClick={() => setActiveTab("relationships")}
          >
            Relationships ({(data?.relationships.canonical_count ?? 0) + (data?.relationships.analytical_count ?? 0)})
          </button>
          <button
            type="button"
            className={`${s.drawerTab} ${activeTab === "conflicts" ? s.drawerTabActive : ""}`}
            onClick={() => setActiveTab("conflicts")}
          >
            Identity Conflicts ({data?.identity_candidates.length ?? 0})
          </button>
          <button
            type="button"
            className={`${s.drawerTab} ${activeTab === "timeline" ? s.drawerTabActive : ""}`}
            onClick={() => setActiveTab("timeline")}
          >
            Timeline ({data?.related_events.length ?? 0})
          </button>
        </div>

        {/* Tab Content Body */}
        <div className={s.drawerBody}>
          {loading && (
            <div style={{ padding: "var(--space-8)", textAlign: "center", color: "var(--text-muted)" }}>
              Loading entity intelligence dossier...
            </div>
          )}

          {error && (
            <div style={{ padding: "var(--space-4)", background: "rgba(239, 68, 68, 0.1)", border: "1px solid var(--critical)", borderRadius: "6px", color: "var(--critical)" }}>
              {error}
              <button
                type="button"
                onClick={loadDossier}
                style={{ marginLeft: "var(--space-3)", textDecoration: "underline", background: "none", border: "none", color: "var(--critical)", cursor: "pointer" }}
              >
                Retry
              </button>
            </div>
          )}

          {!loading && data && (
            <>
              {/* Tab 1: Overview & Provenance */}
              {activeTab === "overview" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
                  <div className={s.dossierSection}>
                    <span className={s.sectionTitle}>Observation Timestamps</span>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-3)" }}>
                      <div className={s.citationCard}>
                        <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>FIRST SEEN</span>
                        <span className="t-mono-sm" style={{ color: "var(--text-primary)" }}>
                          {data.entity.first_seen ? new Date(data.entity.first_seen).toLocaleString() : "Direct case record"}
                        </span>
                      </div>
                      <div className={s.citationCard}>
                        <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>LAST SEEN</span>
                        <span className="t-mono-sm" style={{ color: "var(--text-primary)" }}>
                          {data.entity.last_seen ? new Date(data.entity.last_seen).toLocaleString() : "Direct case record"}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className={s.dossierSection}>
                    <span className={s.sectionTitle}>Source Evidence Files ({data.provenance.source_evidence_files.length})</span>
                    {data.provenance.source_evidence_files.length === 0 ? (
                      <span className="t-body-sm" style={{ color: "var(--text-muted)" }}>
                        No direct evidence file links (asserted or inferred entity).
                      </span>
                    ) : (
                      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                        {data.provenance.source_evidence_files.map((file) => (
                          <div key={file.id} className={s.citationCard}>
                            <div className={s.citationHead}>
                              <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                                {file.filename}
                              </span>
                              <span>{file.file_type || "DOCUMENT"}</span>
                            </div>
                            {file.sha256_hash && (
                              <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                                SHA-256: {file.sha256_hash.slice(0, 24)}...
                              </span>
                            )}
                            {onOpenEvidence && (
                              <button
                                type="button"
                                onClick={() => onOpenEvidence(file.id)}
                                style={{
                                  alignSelf: "flex-start",
                                  marginTop: "4px",
                                  background: "none",
                                  border: "none",
                                  color: "var(--intel)",
                                  cursor: "pointer",
                                  fontSize: "12px",
                                  padding: 0,
                                  textDecoration: "underline",
                                }}
                              >
                                View Evidence Artifact →
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className={s.dossierSection}>
                    <span className={s.sectionTitle}>Extraction Engine & Provenance</span>
                    <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
                      {data.provenance.extractors.map((ext, idx) => (
                        <span key={idx} className={s.typeBadge}>
                          {ext}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Tab 2: Mentions & Citations */}
              {activeTab === "mentions" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                  {data.mentions.length === 0 ? (
                    <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "var(--space-6)" }}>
                      No textual mentions recorded.
                    </div>
                  ) : (
                    data.mentions.map((m) => (
                      <div key={m.id} className={s.citationCard}>
                        <div className={s.citationHead}>
                          <span style={{ fontWeight: 500, color: "var(--intel)" }}>
                            {m.source_doc || "Evidence Record"}
                            {m.source_page ? ` · p. ${m.source_page}` : ""}
                            {m.source_line ? ` · line ${m.source_line}` : ""}
                          </span>
                          <span>
                            {m.event_timestamp ? new Date(m.event_timestamp).toLocaleDateString() : ""}
                          </span>
                        </div>

                        {m.snippet ? (
                          <div className={s.citationSnippet}>
                            "{m.snippet}"
                          </div>
                        ) : (
                          <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)" }}>
                            Observed token: <code>{m.raw_value}</code>
                          </div>
                        )}

                        <div style={{ display: "flex", justifyContent: "space-between", font: "var(--type-mono-xs)", color: "var(--text-muted)", marginTop: "2px" }}>
                          <span>EXTRACTOR: {m.extractor}</span>
                          {m.confidence !== null && m.confidence !== undefined && (
                            <span>CONFIDENCE: {(m.confidence * 100).toFixed(0)}%</span>
                          )}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* Tab 3: Dual-Projection Relationships */}
              {activeTab === "relationships" && (
                <div className={s.dualRelContainer}>
                  {/* Canonical Relationships */}
                  <div className={s.relGroup}>
                    <div className={s.relGroupTitle}>
                      <span style={{ color: "var(--verified)" }}>●</span>
                      <span>Canonical Verified Relationships ({data.relationships.canonical_count})</span>
                    </div>
                    {data.relationships.canonical.length === 0 ? (
                      <span className="t-body-sm" style={{ color: "var(--text-muted)", padding: "var(--space-2) 0" }}>
                        No canonical relationships materialized.
                      </span>
                    ) : (
                      data.relationships.canonical.map((r) => (
                        <div key={r.id} className={s.relItem}>
                          <div className={s.relTarget}>
                            <span style={{ color: "var(--text-muted)", marginRight: "4px" }}>
                              {r.is_outbound ? "→" : "←"}
                            </span>
                            {onSelectEntity ? (
                              <button
                                type="button"
                                onClick={() => onSelectEntity(r.target_entity_id)}
                                style={{
                                  background: "none",
                                  border: "none",
                                  color: "var(--text-primary)",
                                  cursor: "pointer",
                                  fontWeight: 600,
                                  fontSize: "14px",
                                  textDecoration: "underline",
                                  padding: 0,
                                }}
                              >
                                {r.target_canonical_value}
                              </button>
                            ) : (
                              <span>{r.target_canonical_value}</span>
                            )}
                            <span className={s.typeBadge}>{r.target_entity_type}</span>
                          </div>
                          <span className={s.relEdge}>{r.relationship_type}</span>
                        </div>
                      ))
                    )}
                  </div>

                  {/* Analytical Inferred Relationships */}
                  <div className={s.relGroup} style={{ marginTop: "var(--space-4)" }}>
                    <div className={s.relGroupTitle}>
                      <span style={{ color: "var(--intel)" }}>●</span>
                      <span>Analytical / Inferred Relationships ({data.relationships.analytical_count})</span>
                    </div>
                    {data.relationships.analytical.length === 0 ? (
                      <span className="t-body-sm" style={{ color: "var(--text-muted)", padding: "var(--space-2) 0" }}>
                        No analytical relationships inferred.
                      </span>
                    ) : (
                      data.relationships.analytical.map((r) => (
                        <div key={r.id} className={s.relItem}>
                          <div className={s.relTarget}>
                            <span style={{ color: "var(--text-muted)", marginRight: "4px" }}>
                              {r.is_outbound ? "→" : "←"}
                            </span>
                            {onSelectEntity ? (
                              <button
                                type="button"
                                onClick={() => onSelectEntity(r.target_entity_id)}
                                style={{
                                  background: "none",
                                  border: "none",
                                  color: "var(--text-primary)",
                                  cursor: "pointer",
                                  fontWeight: 600,
                                  fontSize: "14px",
                                  textDecoration: "underline",
                                  padding: 0,
                                }}
                              >
                                {r.target_canonical_value}
                              </button>
                            ) : (
                              <span>{r.target_canonical_value}</span>
                            )}
                            <span className={s.typeBadge}>{r.target_entity_type}</span>
                          </div>
                          <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
                            {r.confidence !== null && r.confidence !== undefined && (
                              <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                                {(r.confidence * 100).toFixed(0)}%
                              </span>
                            )}
                            <span className={s.relEdge} style={{ background: "rgba(56, 189, 248, 0.08)", borderColor: "rgba(56, 189, 248, 0.2)" }}>
                              {r.relationship_type}
                            </span>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* Tab 4: Identity Candidates */}
              {activeTab === "conflicts" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                  {data.identity_candidates.length === 0 ? (
                    <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "var(--space-8)" }}>
                      No identity conflicts or ambiguous candidates associated with this entity.
                    </div>
                  ) : (
                    data.identity_candidates.map((cand) => (
                      <IdentityConflictPanel
                        key={cand.id}
                        candidate={cand}
                        caseId={caseId}
                        caseStateVersion={data.case_state_version}
                        onResolved={handleChildCandidateResolved}
                        onSelectEntity={onSelectEntity}
                      />
                    ))
                  )}
                </div>
              )}

              {/* Tab 5: Timeline */}
              {activeTab === "timeline" && (
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                  {data.related_events.length === 0 ? (
                    <div style={{ textAlign: "center", color: "var(--text-muted)", padding: "var(--space-8)" }}>
                      No timeline events associated with this entity.
                    </div>
                  ) : (
                    data.related_events.map((ev) => (
                      <div key={ev.id} className={s.citationCard}>
                        <div className={s.citationHead}>
                          <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                            {ev.event_type}
                          </span>
                          <span>
                            {ev.event_timestamp ? new Date(ev.event_timestamp).toLocaleString() : "Case Event"}
                          </span>
                        </div>
                        {ev.text_content && (
                          <div style={{ font: "var(--type-body-sm)", color: "var(--text-secondary)" }}>
                            {ev.text_content}
                          </div>
                        )}
                        {ev.source_doc && (
                          <span className="t-mono-xs" style={{ color: "var(--text-muted)" }}>
                            SOURCE: {ev.source_doc}
                            {ev.source_page ? ` · p. ${ev.source_page}` : ""}
                            {ev.source_line ? ` · line ${ev.source_line}` : ""}
                          </span>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
