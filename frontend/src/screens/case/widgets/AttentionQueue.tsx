import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { AttentionQueueWidget, AttentionItem } from '../../../types/commandCenter';

interface AttentionQueueProps {
  widget: AttentionQueueWidget;
}

export const AttentionQueue: React.FC<AttentionQueueProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, items, counts_by_priority } = widget;

  const urgentCount = counts_by_priority['URGENT_ACTION'] || 0;
  const reviewCount = counts_by_priority['REVIEW_REQUIRED'] || 0;

  const getPriorityBadgeStyle = (priority: AttentionItem['priority']) => {
    switch (priority) {
      case 'URGENT_ACTION':
        return { background: 'rgba(239, 68, 68, 0.15)', border: '1px solid #ef4444', color: '#f87171' };
      case 'REVIEW_REQUIRED':
        return { background: 'rgba(245, 158, 11, 0.15)', border: '1px solid #f59e0b', color: '#fbbf24' };
      case 'NEW_INTELLIGENCE':
        return { background: 'rgba(59, 130, 246, 0.15)', border: '1px solid #3b82f6', color: '#60a5fa' };
      default:
        return { background: 'rgba(107, 114, 128, 0.15)', border: '1px solid #4b5563', color: '#9ca3af' };
    }
  };

  return (
    <div
      style={{
        background: '#111827',
        border: '1px solid #1f2937',
        borderRadius: '10px',
        padding: '16px 20px',
        marginBottom: '16px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '18px' }}>🚨</span>
          <h2 style={{ margin: 0, fontSize: '15px', fontWeight: 600, color: '#f3f4f6', letterSpacing: '0.02em' }}>
            {header.title}
          </h2>
          <span
            style={{
              fontSize: '11px',
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: '9999px',
              ...getPriorityBadgeStyle(header.status as any),
            }}
          >
            {header.metric} ITEMS PENDING
          </span>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {urgentCount > 0 && (
            <span style={{ fontSize: '11px', color: '#f87171', fontWeight: 600 }}>
              🔴 {urgentCount} Urgent
            </span>
          )}
          {reviewCount > 0 && (
            <span style={{ fontSize: '11px', color: '#fbbf24', fontWeight: 600 }}>
              🟡 {reviewCount} Review
            </span>
          )}
        </div>
      </div>

      {items.length === 0 ? (
        <div
          style={{
            padding: '16px',
            textAlign: 'center',
            fontSize: '12px',
            color: '#10b981',
            background: 'rgba(16, 185, 129, 0.05)',
            borderRadius: '6px',
            border: '1px dashed rgba(16, 185, 129, 0.2)',
          }}
        >
          ✓ No urgent bottlenecks detected. All identity conflicts, relationship proposals, and findings are adjudicated.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '10px' }}>
          {items.map((item) => (
            <div
              key={item.item_id}
              onClick={() => navigate(item.click_action)}
              style={{
                background: '#18202f',
                border: '1px solid #283548',
                borderRadius: '8px',
                padding: '12px 14px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = '#3b82f6';
                e.currentTarget.style.background = '#1e293b';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#283548';
                e.currentTarget.style.background = '#18202f';
              }}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                  <span
                    style={{
                      fontSize: '10px',
                      fontWeight: 700,
                      padding: '1px 6px',
                      borderRadius: '4px',
                      ...getPriorityBadgeStyle(item.priority),
                    }}
                  >
                    {item.category.replace('_', ' ')}
                  </span>
                  <span style={{ fontSize: '11px', color: '#60a5fa', fontWeight: 500 }}>Review →</span>
                </div>
                <div style={{ fontSize: '13px', fontWeight: 600, color: '#f1f5f9', marginBottom: '4px' }}>
                  {item.title}
                </div>
                <div style={{ fontSize: '11px', color: '#94a3b8', lineHeight: 1.4 }}>
                  {item.description}
                </div>
              </div>

              {item.source_refs.length > 0 && (
                <div style={{ marginTop: '8px', fontSize: '10px', color: '#64748b' }}>
                  Ref: {item.source_refs[0]}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
