import React from 'react';
import type { InvestigationHealthWidget } from '../../../types/commandCenter';

interface InvestigationHealthProps {
  widget: InvestigationHealthWidget;
}

export const InvestigationHealth: React.FC<InvestigationHealthProps> = ({ widget }) => {
  const { header, overall_score, integrity_status, state_version, entities_count, evidence_count, processed_evidence_count, relationships_count, canonical_count, unreviewed_relationships_count, findings_count, stale_findings_count, unresolved_identities_count } = widget;

  const getScoreColor = (score: number) => {
    if (score >= 85) return '#10b981';
    if (score >= 60) return '#f59e0b';
    return '#ef4444';
  };

  return (
    <div
      style={{
        background: '#111827',
        border: '1px solid #1f2937',
        borderRadius: '10px',
        padding: '16px 20px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '16px' }}>🛡️</span>
          <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#f3f4f6' }}>
            {header.title}
          </h3>
        </div>
        <span
          style={{
            fontSize: '11px',
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: '9999px',
            background: 'rgba(16, 185, 129, 0.1)',
            border: `1px solid ${getScoreColor(overall_score)}`,
            color: getScoreColor(overall_score),
          }}
        >
          {integrity_status} (v{state_version})
        </span>
      </div>

      {/* Main Score & Gauge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '16px' }}>
        <div
          style={{
            fontSize: '32px',
            fontWeight: 800,
            color: getScoreColor(overall_score),
            lineHeight: 1,
          }}
        >
          {overall_score}%
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '11px', color: '#9ca3af', marginBottom: '4px' }}>
            Adjudication & Freshness Score
          </div>
          <div style={{ width: '100%', height: '6px', background: '#1f2937', borderRadius: '3px', overflow: 'hidden' }}>
            <div
              style={{
                width: `${overall_score}%`,
                height: '100%',
                background: getScoreColor(overall_score),
                borderRadius: '3px',
                transition: 'width 0.4s ease',
              }}
            />
          </div>
        </div>
      </div>

      {/* Metric Breakdown Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', textAlign: 'center' }}>
        <div style={{ background: '#18202f', padding: '8px 4px', borderRadius: '6px' }}>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#f3f4f6' }}>{entities_count}</div>
          <div style={{ fontSize: '10px', color: '#94a3b8' }}>Entities</div>
        </div>
        <div style={{ background: '#18202f', padding: '8px 4px', borderRadius: '6px' }}>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#f3f4f6' }}>{processed_evidence_count}/{evidence_count}</div>
          <div style={{ fontSize: '10px', color: '#94a3b8' }}>Files Done</div>
        </div>
        <div style={{ background: '#18202f', padding: '8px 4px', borderRadius: '6px' }}>
          <div style={{ fontSize: '16px', fontWeight: 700, color: canonical_count > 0 ? '#34d399' : '#f3f4f6' }}>
            {canonical_count}/{relationships_count}
          </div>
          <div style={{ fontSize: '10px', color: '#94a3b8' }}>Canonical Links</div>
        </div>
        <div style={{ background: '#18202f', padding: '8px 4px', borderRadius: '6px' }}>
          <div style={{ fontSize: '16px', fontWeight: 700, color: stale_findings_count > 0 ? '#fbbf24' : '#f3f4f6' }}>
            {findings_count - stale_findings_count}/{findings_count}
          </div>
          <div style={{ fontSize: '10px', color: '#94a3b8' }}>Fresh Findings</div>
        </div>
      </div>
    </div>
  );
};
