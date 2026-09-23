import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { IdentityConflictsWidget as IdentityConflictsWidgetType } from '../../../types/commandCenter';

interface IdentityConflictsWidgetProps {
  widget: IdentityConflictsWidgetType;
}

export const IdentityConflictsWidget: React.FC<IdentityConflictsWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, items, total_unresolved } = widget;

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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '16px' }}>👥</span>
          <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#f3f4f6' }}>
            {header.title}
          </h3>
        </div>
        <button
          onClick={() => navigate(header.click_action)}
          style={{
            background: 'none',
            border: 'none',
            fontSize: '11px',
            color: '#60a5fa',
            fontWeight: 600,
            cursor: 'pointer',
            padding: 0,
          }}
        >
          View all ({total_unresolved}) →
        </button>
      </div>

      {items.length === 0 ? (
        <div style={{ padding: '20px', textAlign: 'center', fontSize: '12px', color: '#9ca3af' }}>
          ✓ No identity candidates awaiting resolution.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {items.slice(0, 4).map((cand) => (
            <div
              key={cand.id}
              onClick={() => navigate(cand.click_action)}
              style={{
                background: '#18202f',
                border: '1px solid #283548',
                borderRadius: '6px',
                padding: '10px 12px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = '#f59e0b';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#283548';
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9' }}>
                  {cand.candidate_value}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    fontWeight: 600,
                    padding: '1px 6px',
                    borderRadius: '4px',
                    background: 'rgba(245, 158, 11, 0.15)',
                    border: '1px solid #f59e0b',
                    color: '#fbbf24',
                  }}
                >
                  {cand.candidate_type}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8' }}>
                {cand.conflict_signals.length > 0 ? (
                  <span style={{ color: '#f87171' }}>⚠️ Conflict: {cand.conflict_signals[0]}</span>
                ) : (
                  <span>Supporting: {cand.supporting_refs[0] || 'Evidence co-occurrence'}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
