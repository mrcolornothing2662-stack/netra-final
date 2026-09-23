import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { LensSummaryWidget as LensSummaryWidgetType } from '../../../types/commandCenter';

interface LensSummaryWidgetProps {
  widget: LensSummaryWidgetType;
}

export const LensSummaryWidget: React.FC<LensSummaryWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, money_events_count, comms_events_count, geo_events_count, cross_lens_signals_count, disclaimer } = widget;

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
          <span style={{ fontSize: '16px' }}>🔬</span>
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
          Open Forensic Lenses →
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginBottom: '12px' }}>
        <div
          onClick={() => navigate('/investigations/case/lenses')}
          style={{
            background: '#18202f',
            padding: '12px',
            borderRadius: '6px',
            textAlign: 'center',
            cursor: 'pointer',
            border: '1px solid #283548',
          }}
        >
          <div style={{ fontSize: '16px', marginBottom: '4px' }}>💳</div>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#f3f4f6' }}>{money_events_count}</div>
          <div style={{ fontSize: '10px', color: '#94a3b8' }}>Money Trail</div>
        </div>

        <div
          onClick={() => navigate('/investigations/case/lenses')}
          style={{
            background: '#18202f',
            padding: '12px',
            borderRadius: '6px',
            textAlign: 'center',
            cursor: 'pointer',
            border: '1px solid #283548',
          }}
        >
          <div style={{ fontSize: '16px', marginBottom: '4px' }}>📡</div>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#f3f4f6' }}>{comms_events_count}</div>
          <div style={{ fontSize: '10px', color: '#94a3b8' }}>Communications</div>
        </div>

        <div
          onClick={() => navigate('/investigations/case/lenses')}
          style={{
            background: '#18202f',
            padding: '12px',
            borderRadius: '6px',
            textAlign: 'center',
            cursor: 'pointer',
            border: '1px solid #283548',
          }}
        >
          <div style={{ fontSize: '16px', marginBottom: '4px' }}>📍</div>
          <div style={{ fontSize: '16px', fontWeight: 700, color: '#f3f4f6' }}>{geo_events_count}</div>
          <div style={{ fontSize: '10px', color: '#94a3b8' }}>Travel / Geo</div>
        </div>
      </div>

      {cross_lens_signals_count > 0 && (
        <div
          style={{
            fontSize: '11px',
            color: '#fbbf24',
            background: 'rgba(245, 158, 11, 0.1)',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid rgba(245, 158, 11, 0.2)',
            marginBottom: '8px',
          }}
        >
          ⚡ <b>{cross_lens_signals_count} cross-lens temporal pattern(s)</b> detected across financial and communication activity.
        </div>
      )}

      <div style={{ fontSize: '10px', color: '#64748b', fontStyle: 'italic', lineHeight: 1.3 }}>
        ⚠️ {disclaimer}
      </div>
    </div>
  );
};
