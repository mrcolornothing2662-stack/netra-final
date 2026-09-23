import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getCommandCenter } from '../../api/commandCenter';
import type { CommandCenterProjection } from '../../types/commandCenter';

import { AttentionQueue } from './widgets/AttentionQueue';
import { InvestigationHealth } from './widgets/InvestigationHealth';
import { IdentityConflictsWidget } from './widgets/IdentityConflictsWidget';
import { RelationshipReviewWidget } from './widgets/RelationshipReviewWidget';
import { FindingsWidget } from './widgets/FindingsWidget';
import { LensSummaryWidget } from './widgets/LensSummaryWidget';
import { EvidenceStatusWidget } from './widgets/EvidenceStatusWidget';
import { SyncWidget } from './widgets/SyncWidget';
import { ActivityWidget } from './widgets/ActivityWidget';
import { MiniNetworkWidget } from './widgets/MiniNetworkWidget';

interface CommandCenterProps {
  caseId: string;
}

export const CommandCenter: React.FC<CommandCenterProps> = ({ caseId }) => {
  const navigate = useNavigate();
  const [data, setData] = useState<CommandCenterProjection | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getCommandCenter(caseId);
      setData(res);
      setError(null);
    } catch (err: any) {
      console.error('[CommandCenter] Failed to fetch projection:', err);
      setError(err?.message || 'Failed to load Command Center projection');
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 15000);
    return () => clearInterval(interval);
  }, [loadData]);

  if (loading && !data) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: '#9ca3af', fontSize: '13px' }}>
        <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite', marginRight: '8px' }}>⟳</span>
        Synthesizing Investigation Command Center...
      </div>
    );
  }

  if (error && !data) {
    return (
      <div
        style={{
          padding: '24px',
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid #ef4444',
          borderRadius: '8px',
          color: '#f87171',
          fontSize: '13px',
          margin: '20px 0',
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: '6px' }}>Failed to load Command Center</div>
        <div>{error}</div>
        <button
          onClick={loadData}
          style={{
            marginTop: '12px',
            padding: '6px 12px',
            background: '#1f2937',
            border: '1px solid #374151',
            borderRadius: '4px',
            color: '#f3f4f6',
            cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* 1. TOP BANNER: Attention Required (URGENT ACTION) */}
      <AttentionQueue widget={data.attention_queue} />

      {/* 2. ROW 1: Investigation Health + Offline Sync Status */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px' }}>
        <InvestigationHealth widget={data.investigation_health} />
        <SyncWidget widget={data.sync_status} />
      </div>

      {/* 3. ROW 2: Identity Conflicts + Relationship Review Queue */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px' }}>
        <IdentityConflictsWidget widget={data.identity_conflicts} />
        <RelationshipReviewWidget widget={data.relationship_review} />
      </div>

      {/* 4. ROW 3: Findings Requiring Review + Forensic Lens Summary */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px' }}>
        <FindingsWidget widget={data.findings_requiring_review} />
        <LensSummaryWidget widget={data.lens_summary} />
      </div>

      {/* 5. ROW 4: Evidence Status + Recent Activity */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px' }}>
        <EvidenceStatusWidget widget={data.evidence_status} />
        <ActivityWidget widget={data.recent_activity} />
      </div>

      {/* 6. ROW 5: Case Graph (Mini Network) + Quick Actions Toolbar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '16px' }}>
        <MiniNetworkWidget widget={data.mini_network} />

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
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
              <span style={{ fontSize: '16px' }}>⚡</span>
              <h3 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#f3f4f6' }}>
                Next Actions
              </h3>
            </div>
            <p style={{ fontSize: '11px', color: '#9ca3af', lineHeight: 1.5, margin: '0 0 16px 0' }}>
              Canonical investigative workflows for this case state. All actions preserve tamper-evident audit trails.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <button
              onClick={() => navigate(`/investigations/${caseId}/evidence`)}
              style={{
                padding: '10px',
                borderRadius: '6px',
                background: '#1e293b',
                border: '1px solid #334155',
                color: '#f1f5f9',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              📥 Ingest Evidence
            </button>
            <button
              onClick={() => navigate(`/investigations/${caseId}/entities`)}
              style={{
                padding: '10px',
                borderRadius: '6px',
                background: '#1e293b',
                border: '1px solid #334155',
                color: '#f1f5f9',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              👥 Entity Explorer
            </button>
            <button
              onClick={() => navigate(`/investigations/${caseId}/network`)}
              style={{
                padding: '10px',
                borderRadius: '6px',
                background: '#1e293b',
                border: '1px solid #334155',
                color: '#f1f5f9',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              🕸️ Review Links
            </button>
            <button
              onClick={() => navigate(`/investigations/${caseId}/timeline`)}
              style={{
                padding: '10px',
                borderRadius: '6px',
                background: '#1e293b',
                border: '1px solid #334155',
                color: '#f1f5f9',
                fontSize: '12px',
                fontWeight: 600,
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              ⏱️ Timeline Replay
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
