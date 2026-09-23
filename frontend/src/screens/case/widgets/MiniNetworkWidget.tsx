import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { MiniNetworkWidget as MiniNetworkWidgetType } from '../../../types/commandCenter';

interface MiniNetworkWidgetProps {
  widget: MiniNetworkWidgetType;
}

export const MiniNetworkWidget: React.FC<MiniNetworkWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, nodes, edges } = widget;

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
          <span style={{ fontSize: '16px' }}>🕸️</span>
          <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#f3f4f6' }}>
            {header.title}
          </h3>
          <span style={{ fontSize: '10px', color: '#9ca3af' }}>({header.metric})</span>
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
          Full graph Explorer →
        </button>
      </div>

      {nodes.length === 0 ? (
        <div style={{ padding: '24px', textAlign: 'center', fontSize: '12px', color: '#9ca3af' }}>
          No graph entities extracted yet.
        </div>
      ) : (
        <div
          onClick={() => navigate(header.click_action)}
          style={{
            background: '#0d121c',
            border: '1px solid #1e293b',
            borderRadius: '8px',
            padding: '12px',
            cursor: 'pointer',
            position: 'relative',
            minHeight: '140px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
          }}
        >
          {/* Top preview chips */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '10px' }}>
            {nodes.slice(0, 6).map((node) => (
              <span
                key={node.id}
                style={{
                  fontSize: '10px',
                  fontWeight: 600,
                  padding: '2px 8px',
                  borderRadius: '4px',
                  background: '#1e293b',
                  border: '1px solid #334155',
                  color: '#cbd5e1',
                }}
              >
                {node.label} ({node.entity_type})
              </span>
            ))}
            {nodes.length > 6 && (
              <span style={{ fontSize: '10px', color: '#64748b', alignSelf: 'center' }}>
                +{nodes.length - 6} more
              </span>
            )}
          </div>

          {/* Interactive SVG Canvas Schema */}
          <svg viewBox="0 0 320 60" style={{ width: '100%', height: '50px' }}>
            <line x1="30" y1="30" x2="100" y2="20" stroke="#3b82f6" strokeWidth="1.5" strokeDasharray="3 3" />
            <line x1="100" y1="20" x2="180" y2="40" stroke="#10b981" strokeWidth="2" />
            <line x1="180" y1="40" x2="250" y2="25" stroke="#10b981" strokeWidth="2" />
            <line x1="100" y1="20" x2="250" y2="25" stroke="#6366f1" strokeWidth="1.5" strokeDasharray="3 3" />
            <circle cx="30" cy="30" r="5" fill="#3b82f6" />
            <circle cx="100" cy="20" r="7" fill="#10b981" />
            <circle cx="180" cy="40" r="6" fill="#f59e0b" />
            <circle cx="250" cy="25" r="6" fill="#10b981" />
          </svg>

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#64748b' }}>
            <span>🟢 Solid: Confirmed Canonical</span>
            <span>🔵 Dashed: Inferred (Review Required)</span>
          </div>
        </div>
      )}
    </div>
  );
};
