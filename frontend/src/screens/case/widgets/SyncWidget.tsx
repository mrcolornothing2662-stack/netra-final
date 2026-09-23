import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { SyncWidget as SyncWidgetType } from '../../../types/commandCenter';

interface SyncWidgetProps {
  widget: SyncWidgetType;
}

export const SyncWidget: React.FC<SyncWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, server_state_version, pending_conflicts_count, recent_synced_count, last_synced_at, sync_status } = widget;

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
          <span style={{ fontSize: '16px' }}>🔄</span>
          <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#f3f4f6' }}>
            {header.title}
          </h3>
        </div>
        <span
          style={{
            fontSize: '10px',
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: '9999px',
            background: pending_conflicts_count > 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
            border: `1px solid ${pending_conflicts_count > 0 ? '#ef4444' : '#10b981'}`,
            color: pending_conflicts_count > 0 ? '#f87171' : '#34d399',
          }}
        >
          {sync_status}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '12px' }}>
        <div style={{ background: '#18202f', padding: '10px', borderRadius: '6px' }}>
          <div style={{ fontSize: '11px', color: '#9ca3af' }}>Server State Version</div>
          <div style={{ fontSize: '18px', fontWeight: 700, color: '#f3f4f6' }}>v{server_state_version}</div>
        </div>
        <div style={{ background: '#18202f', padding: '10px', borderRadius: '6px' }}>
          <div style={{ fontSize: '11px', color: '#9ca3af' }}>Offline Conflicts</div>
          <div style={{ fontSize: '18px', fontWeight: 700, color: pending_conflicts_count > 0 ? '#f87171' : '#34d399' }}>
            {pending_conflicts_count}
          </div>
        </div>
      </div>

      <div style={{ fontSize: '11px', color: '#94a3b8', display: 'flex', justifyContent: 'space-between' }}>
        <span>Synced mutations: <b>{recent_synced_count}</b></span>
        {last_synced_at && (
          <span style={{ color: '#64748b' }}>
            Last: {new Date(last_synced_at).toLocaleTimeString()}
          </span>
        )}
      </div>

      {pending_conflicts_count > 0 && (
        <button
          onClick={() => navigate(header.click_action)}
          style={{
            marginTop: '10px',
            width: '100%',
            padding: '6px 12px',
            borderRadius: '6px',
            background: 'rgba(239, 68, 68, 0.2)',
            border: '1px solid #ef4444',
            color: '#f87171',
            fontSize: '11px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          ⚖️ Resolve Diverged Conflicts Now
        </button>
      )}
    </div>
  );
};
