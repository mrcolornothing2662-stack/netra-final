import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { RelationshipReviewWidget as RelationshipReviewWidgetType } from '../../../types/commandCenter';

interface RelationshipReviewWidgetProps {
  widget: RelationshipReviewWidgetType;
}

export const RelationshipReviewWidget: React.FC<RelationshipReviewWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, items, total_unreviewed } = widget;

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
          <span style={{ fontSize: '16px' }}>🔗</span>
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
          Review all ({total_unreviewed}) →
        </button>
      </div>

      {items.length === 0 ? (
        <div style={{ padding: '20px', textAlign: 'center', fontSize: '12px', color: '#9ca3af' }}>
          ✓ All inferred graph relationships adjudicated.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {items.slice(0, 4).map((rel) => (
            <div
              key={rel.id}
              onClick={() => navigate(rel.click_action)}
              style={{
                background: '#18202f',
                border: '1px solid #283548',
                borderRadius: '6px',
                padding: '10px 12px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = '#6366f1';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#283548';
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9' }}>
                  {rel.source_value || rel.source_entity_id.slice(0, 8)} → {rel.target_value || rel.target_entity_id.slice(0, 8)}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    fontWeight: 600,
                    padding: '1px 6px',
                    borderRadius: '4px',
                    background: 'rgba(99, 102, 241, 0.15)',
                    border: '1px solid #6366f1',
                    color: '#818cf8',
                  }}
                >
                  {rel.relationship_type}
                </span>
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
                <span>Inferred link (Confidence: {intPct(rel.confidence)}%)</span>
                <span style={{ color: '#60a5fa' }}>Adjudicate →</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

function intPct(val?: number | null): number {
  if (val == null) return 80;
  return Math.round(val * 100);
}
