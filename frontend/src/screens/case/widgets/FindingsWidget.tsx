import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { FindingsWidget as FindingsWidgetType } from '../../../types/commandCenter';

interface FindingsWidgetProps {
  widget: FindingsWidgetType;
}

export const FindingsWidget: React.FC<FindingsWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, items, total_findings, stale_count } = widget;

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
          <span style={{ fontSize: '16px' }}>💡</span>
          <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#f3f4f6' }}>
            {header.title}
          </h3>
          {stale_count > 0 && (
            <span
              style={{
                fontSize: '10px',
                fontWeight: 700,
                padding: '1px 6px',
                borderRadius: '4px',
                background: 'rgba(245, 158, 11, 0.15)',
                border: '1px solid #f59e0b',
                color: '#fbbf24',
              }}
            >
              {stale_count} STALE
            </span>
          )}
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
          All findings ({total_findings}) →
        </button>
      </div>

      {items.length === 0 ? (
        <div style={{ padding: '20px', textAlign: 'center', fontSize: '12px', color: '#9ca3af' }}>
          No findings requiring immediate investigator review.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {items.slice(0, 4).map((f) => (
            <div
              key={f.id}
              onClick={() => navigate(f.click_action)}
              style={{
                background: '#18202f',
                border: '1px solid #283548',
                borderRadius: '6px',
                padding: '10px 12px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = '#3b82f6';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#283548';
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9' }}>
                  {f.title}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    fontWeight: 700,
                    padding: '1px 6px',
                    borderRadius: '4px',
                    background: f.freshness_status === 'STALE' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                    border: `1px solid ${f.freshness_status === 'STALE' ? '#f59e0b' : '#10b981'}`,
                    color: f.freshness_status === 'STALE' ? '#fbbf24' : '#34d399',
                  }}
                >
                  {f.freshness_status}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
                <span>Type: {f.finding_type}</span>
                <span>Confidence: {f.confidence ? Math.round(f.confidence * 100) : 85}%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
