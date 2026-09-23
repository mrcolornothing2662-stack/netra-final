import React from 'react';
import { useNavigate } from 'react-router-dom';
import type { EvidenceStatusWidget as EvidenceStatusWidgetType } from '../../../types/commandCenter';

interface EvidenceStatusWidgetProps {
  widget: EvidenceStatusWidgetType;
}

export const EvidenceStatusWidget: React.FC<EvidenceStatusWidgetProps> = ({ widget }) => {
  const navigate = useNavigate();
  const { header, items, total_files, processed_files, pending_files } = widget;

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
          <span style={{ fontSize: '16px' }}>📁</span>
          <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#f3f4f6' }}>
            {header.title}
          </h3>
          <span
            style={{
              fontSize: '10px',
              fontWeight: 700,
              padding: '1px 6px',
              borderRadius: '4px',
              background: pending_files > 0 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
              border: `1px solid ${pending_files > 0 ? '#f59e0b' : '#10b981'}`,
              color: pending_files > 0 ? '#fbbf24' : '#34d399',
            }}
          >
            {processed_files}/{total_files} READY
          </span>
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
          Manage files →
        </button>
      </div>

      {items.length === 0 ? (
        <div style={{ padding: '20px', textAlign: 'center', fontSize: '12px', color: '#9ca3af' }}>
          No evidence files ingested yet.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {items.slice(0, 4).map((ef) => (
            <div
              key={ef.id}
              onClick={() => navigate(ef.click_action)}
              style={{
                background: '#18202f',
                border: '1px solid #283548',
                borderRadius: '6px',
                padding: '10px 12px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = '#10b981';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = '#283548';
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#f1f5f9' }}>
                  {ef.filename}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    fontWeight: 600,
                    padding: '1px 6px',
                    borderRadius: '4px',
                    background: ef.upload_status === 'processed' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                    color: ef.upload_status === 'processed' ? '#34d399' : '#fbbf24',
                  }}
                >
                  {ef.upload_status}
                </span>
              </div>
              <div style={{ fontSize: '10px', color: '#64748b', fontFamily: 'monospace' }}>
                SHA-256: {ef.sha256_hash ? `${ef.sha256_hash.slice(0, 16)}...` : 'N/A'}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
