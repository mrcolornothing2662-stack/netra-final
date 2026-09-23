import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { RecentActivityWidget as RecentActivityWidgetType } from '../../../types/commandCenter';

interface ActivityWidgetProps {
  widget: RecentActivityWidgetType;
}

export const ActivityWidget: React.FC<ActivityWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, items } = widget;

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
          <span style={{ fontSize: '16px' }}>📜</span>
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
          Audit log →
        </button>
      </div>

      {items.length === 0 ? (
        <div style={{ padding: '20px', textAlign: 'center', fontSize: '12px', color: '#9ca3af' }}>
          No case activity recorded yet.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {items.slice(0, 5).map((act) => (
            <div
              key={act.id}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '10px',
                padding: '8px 10px',
                background: '#18202f',
                borderRadius: '6px',
                border: '1px solid #283548',
              }}
            >
              <div style={{ fontSize: '12px', color: '#60a5fa', marginTop: '1px' }}>•</div>
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '11px', fontWeight: 600, color: '#e2e8f0' }}>
                    {act.activity_type.replace(/_/g, ' ')}
                  </span>
                  <span style={{ fontSize: '10px', color: '#64748b' }}>
                    {new Date(act.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
                {act.reason && (
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                    {act.reason}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
