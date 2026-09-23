import React, { useState } from 'react';
import type { HistoricalStateProjection } from '../../../types/timeline';
import s from './TimelineTab.module.css';

interface ReplayStatePanelProps {
  projection: HistoricalStateProjection | null;
  loading: boolean;
}

export const ReplayStatePanel: React.FC<ReplayStatePanelProps> = ({
  projection,
  loading,
}) => {
  const [activeSubTab, setActiveSubTab] = useState<'relationships' | 'candidates' | 'findings' | 'entities'>('relationships');

  if (loading) {
    return (
      <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>
        Reconstructing historical state snapshot...
      </div>
    );
  }

  if (!projection) {
    return (
      <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>
        No historical state projection available.
      </div>
    );
  }

  const { metrics, cursor_activity, relationships, identity_candidates, findings, entities } = projection;

  return (
    <div className={s.statePanel}>
      {/* Metrics Row */}
      <div className={s.stateMetricsGrid}>
        <div className={s.metricCard}>
          <span className={s.metricValue}>{metrics.entities_count}</span>
          <span className={s.metricLabel}>Active Entities</span>
        </div>
        <div className={s.metricCard}>
          <span className={s.metricValue} style={{ color: '#4ADE80' }}>
            {metrics.canonical_relationships_count}
          </span>
          <span className={s.metricLabel}>Canonical Links</span>
        </div>
        <div className={s.metricCard}>
          <span className={s.metricValue} style={{ color: '#FBBF24' }}>
            {metrics.inferred_relationships_count}
          </span>
          <span className={s.metricLabel}>Inferred Links</span>
        </div>
        <div className={s.metricCard}>
          <span className={s.metricValue} style={{ color: '#C084FC' }}>
            {metrics.unresolved_candidates_count}
          </span>
          <span className={s.metricLabel}>Unresolved Candidates</span>
        </div>
        <div className={s.metricCard}>
          <span className={s.metricValue}>{metrics.findings_count}</span>
          <span className={s.metricLabel}>Findings Active</span>
        </div>
      </div>

      {/* Cursor Activity Card */}
      {cursor_activity && (
        <div className={s.cursorActivityCard}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontWeight: 700, color: '#00F0FF', fontFamily: 'var(--type-mono)' }}>
              STATE MUTATION: {cursor_activity.activity_type}
            </span>
            {cursor_activity.created_at && (
              <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--type-mono)' }}>
                {new Date(cursor_activity.created_at).toISOString()}
              </span>
            )}
          </div>
          <div style={{ fontSize: '0.76rem', color: 'var(--text-primary)' }}>
            Target: <strong>{cursor_activity.target_type || 'system'}</strong> ({cursor_activity.target_id || 'case'})
            {cursor_activity.actor_id && <span> · Actor: {cursor_activity.actor_id}</span>}
          </div>
          {cursor_activity.reason && (
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
              Reason: &ldquo;{cursor_activity.reason}&rdquo;
            </div>
          )}
        </div>
      )}

      {/* Subtabs Header */}
      <div style={{ display: 'flex', gap: '8px', borderBottom: '1px solid var(--line)', paddingBottom: '4px' }}>
        <button
          className={`${s.modeBtn} ${activeSubTab === 'relationships' ? s.modeBtnActive : ''}`}
          onClick={() => setActiveSubTab('relationships')}
        >
          Graph Relationships ({relationships.canonical.length + relationships.inferred.length})
        </button>
        <button
          className={`${s.modeBtn} ${activeSubTab === 'candidates' ? s.modeBtnActive : ''}`}
          onClick={() => setActiveSubTab('candidates')}
        >
          Identity Candidates ({identity_candidates.length})
        </button>
        <button
          className={`${s.modeBtn} ${activeSubTab === 'findings' ? s.modeBtnActive : ''}`}
          onClick={() => setActiveSubTab('findings')}
        >
          Intelligence Findings ({findings.length})
        </button>
        <button
          className={`${s.modeBtn} ${activeSubTab === 'entities' ? s.modeBtnActive : ''}`}
          onClick={() => setActiveSubTab('entities')}
        >
          Entities ({entities.length})
        </button>
      </div>

      {/* Subtab Content: Relationships */}
      {activeSubTab === 'relationships' && (
        <div className={s.stateCard}>
          <div className={s.sectionHeader}>
            <span>Dual-Graph State at Version {projection.state_version}</span>
          </div>

          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#4ADE80', marginBottom: '8px', textTransform: 'uppercase' }}>
              Canonical Relationships (G_Canonical) — {relationships.canonical.length} verified
            </div>
            {relationships.canonical.length === 0 ? (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', padding: '8px 0' }}>
                No canonical relationships established at this version.
              </div>
            ) : (
              <table className={s.tableList}>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Source ➔ Target</th>
                    <th>Epistemic</th>
                    <th>Verification</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {relationships.canonical.map(r => (
                    <tr key={r.id}>
                      <td><span className={s.streamPill} style={{ background: 'rgba(255,255,255,0.05)' }}>{r.relationship_type}</span></td>
                      <td style={{ fontFamily: 'var(--type-mono)', fontSize: '0.72rem' }}>
                        {r.source_entity_id.slice(0, 8)} ➔ {r.target_entity_id.slice(0, 8)}
                      </td>
                      <td><span className={s.streamPill}>{r.epistemic_status}</span></td>
                      <td><span className={s.badgeCanonical}>{r.verification_status}</span></td>
                      <td>{(r.confidence * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#FBBF24', marginBottom: '8px', textTransform: 'uppercase' }}>
              Inferred / Analytical Relationships (G_Analytical) — {relationships.inferred.length} candidate links
            </div>
            {relationships.inferred.length === 0 ? (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', padding: '8px 0' }}>
                No unreviewed or rejected inferred relationships at this version.
              </div>
            ) : (
              <table className={s.tableList}>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Source ➔ Target</th>
                    <th>Epistemic</th>
                    <th>Verification</th>
                    <th>Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {relationships.inferred.map(r => (
                    <tr key={r.id}>
                      <td><span className={s.streamPill} style={{ background: 'rgba(255,255,255,0.05)' }}>{r.relationship_type}</span></td>
                      <td style={{ fontFamily: 'var(--type-mono)', fontSize: '0.72rem' }}>
                        {r.source_entity_id.slice(0, 8)} ➔ {r.target_entity_id.slice(0, 8)}
                      </td>
                      <td><span className={s.streamPill}>{r.epistemic_status}</span></td>
                      <td>
                        <span className={r.verification_status === 'REJECTED' ? s.badgeRejected : s.badgeInferred}>
                          {r.verification_status}
                        </span>
                      </td>
                      <td>{(r.confidence * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* Subtab Content: Candidates */}
      {activeSubTab === 'candidates' && (
        <div className={s.stateCard}>
          <div className={s.sectionHeader}>
            <span>Identity Candidates at Version {projection.state_version}</span>
          </div>
          {identity_candidates.length === 0 ? (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              No identity ambiguity candidates tracked at this version.
            </div>
          ) : (
            <table className={s.tableList}>
              <thead>
                <tr>
                  <th>Candidate Value</th>
                  <th>Type</th>
                  <th>Status at v{projection.state_version}</th>
                  <th>Recorded At</th>
                </tr>
              </thead>
              <tbody>
                {identity_candidates.map(c => (
                  <tr key={c.id}>
                    <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{c.candidate_value}</td>
                    <td><span className={s.streamPill}>{c.candidate_type}</span></td>
                    <td>
                      <span className={
                        c.resolution_status === 'CONFIRMED_SAME'
                          ? s.badgeCanonical
                          : c.resolution_status === 'CONFIRMED_DIFFERENT'
                          ? s.badgeRejected
                          : s.badgeInferred
                      }>
                        {c.resolution_status}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--type-mono)' }}>
                      {c.created_at ? new Date(c.created_at).toLocaleDateString() : 'N/A'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Subtab Content: Findings */}
      {activeSubTab === 'findings' && (
        <div className={s.stateCard}>
          <div className={s.sectionHeader}>
            <span>Active Findings at Version {projection.state_version}</span>
          </div>
          {findings.length === 0 ? (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              No intelligence findings active at this version.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {findings.map(f => (
                <div
                  key={f.id}
                  style={{
                    padding: '8px 12px',
                    background: 'var(--surface-2)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '0.82rem', color: 'var(--text-primary)' }}>
                      {f.title}
                    </div>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                      Type: {f.finding_type} · Severity: {f.severity} · Gen at v{f.generated_at_case_version}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span className={f.freshness_status === 'CURRENT' ? s.badgeCanonical : s.badgeInferred}>
                      {f.freshness_status}
                    </span>
                    <span style={{ fontSize: '0.75rem', fontFamily: 'var(--type-mono)' }}>
                      {(f.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Subtab Content: Entities */}
      {activeSubTab === 'entities' && (
        <div className={s.stateCard}>
          <div className={s.sectionHeader}>
            <span>Entities Present at Version {projection.state_version}</span>
          </div>
          {entities.length === 0 ? (
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              No entities registered at this version.
            </div>
          ) : (
            <table className={s.tableList}>
              <thead>
                <tr>
                  <th>Value</th>
                  <th>Type</th>
                  <th>Degree Centrality</th>
                  <th>Bridge Score</th>
                </tr>
              </thead>
              <tbody>
                {entities.map(e => (
                  <tr key={e.id}>
                    <td style={{ fontWeight: 600 }}>{e.canonical_value}</td>
                    <td><span className={s.streamPill}>{e.entity_type}</span></td>
                    <td style={{ fontFamily: 'var(--type-mono)' }}>{e.degree_centrality.toFixed(3)}</td>
                    <td style={{ fontFamily: 'var(--type-mono)' }}>{e.bridge_score.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
};
