import React, { useState, useEffect, useCallback } from 'react';
import { connectivity } from '../../offline/connectivity';
import { getQueuedMutationCount } from '../../offline/mutationQueue';
import { getClientStateVersion, isCaseCachedOffline } from '../../offline/db';
import { syncEngine, SyncResultSummary } from '../../offline/syncEngine';
import { getPendingConflicts, resolveSyncConflict } from '../../api/sync';
import type { SyncConflict } from '../../types/sync';

interface SyncStatusProps {
  caseId: string;
  onSyncCompleted?: () => void;
}

export const SyncStatus: React.FC<SyncStatusProps> = ({ caseId, onSyncCompleted }) => {
  const [isOnline, setIsOnline] = useState<boolean>(connectivity.isOnline());
  const [isSimulated, setIsSimulated] = useState<boolean>(connectivity.isSimulatedOffline());
  const [queuedCount, setQueuedCount] = useState<number>(0);
  const [clientVersion, setClientVersion] = useState<number>(1);
  const [isCached, setIsCached] = useState<boolean>(false);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncSummary, setSyncSummary] = useState<SyncResultSummary | null>(null);
  const [conflicts, setConflicts] = useState<SyncConflict[]>([]);
  const [showModal, setShowModal] = useState<boolean>(false);
  const [selectedConflict, setSelectedConflict] = useState<SyncConflict | null>(null);
  const [resolutionRationale, setResolutionRationale] = useState<string>('');
  const [isResolving, setIsResolving] = useState<boolean>(false);

  const refreshStatus = useCallback(async () => {
    setIsOnline(connectivity.isOnline());
    setIsSimulated(connectivity.isSimulatedOffline());
    setQueuedCount(getQueuedMutationCount(caseId));
    setClientVersion(getClientStateVersion(caseId));
    setIsCached(isCaseCachedOffline(caseId));

    if (connectivity.isOnline()) {
      try {
        const pending = await getPendingConflicts(caseId);
        setConflicts(pending);
      } catch {
        // Silently fail if server unreachable
      }
    }
  }, [caseId]);

  useEffect(() => {
    refreshStatus();
    const unsub = connectivity.subscribe(() => {
      refreshStatus();
    });
    const interval = setInterval(refreshStatus, 5000);
    return () => {
      unsub();
      clearInterval(interval);
    };
  }, [refreshStatus]);

  const handleToggleOffline = () => {
    connectivity.setSimulatedOffline(!isSimulated);
    refreshStatus();
  };

  const handleCacheOffline = async () => {
    setIsSyncing(true);
    await syncEngine.cacheCaseForOffline(caseId);
    setIsSyncing(false);
    refreshStatus();
  };

  const handleSyncNow = async () => {
    setIsSyncing(true);
    setSyncSummary(null);
    const res = await syncEngine.syncCase(caseId);
    setIsSyncing(false);
    setSyncSummary(res);
    refreshStatus();
    if (onSyncCompleted && res.success) {
      onSyncCompleted();
    }
  };

  const handleResolve = async (resolution: 'KEEP_SERVER' | 'APPLY_OFFLINE' | 'CREATE_NEW_REVIEW') => {
    if (!selectedConflict) return;
    if (!resolutionRationale.trim()) {
      alert('Investigative rationale is required for conflict resolution audit.');
      return;
    }

    setIsResolving(true);
    try {
      await resolveSyncConflict(caseId, selectedConflict.conflict_id, {
        resolution,
        rationale: resolutionRationale.trim(),
      });
      setSelectedConflict(null);
      setResolutionRationale('');
      await refreshStatus();
      if (onSyncCompleted) onSyncCompleted();
    } catch (err: any) {
      alert(`Conflict resolution failed: ${err?.message || 'Server error'}`);
    } finally {
      setIsResolving(false);
    }
  };

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
      {/* Dynamic Status Pill */}
      {isSyncing ? (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '11px',
            fontWeight: 600,
            padding: '4px 10px',
            borderRadius: '9999px',
            background: 'rgba(59, 130, 246, 0.15)',
            border: '1px solid #3b82f6',
            color: '#60a5fa',
          }}
        >
          <span style={{ animation: 'spin 1s linear infinite' }}>⟳</span> Syncing...
        </span>
      ) : !isOnline ? (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '11px',
            fontWeight: 600,
            padding: '4px 10px',
            borderRadius: '9999px',
            background: 'rgba(245, 158, 11, 0.15)',
            border: '1px solid #f59e0b',
            color: '#fbbf24',
          }}
        >
          <span
            style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              background: '#f59e0b',
            }}
          />
          OFFLINE {queuedCount > 0 ? `(${queuedCount} queued)` : '(Ready)'}
        </span>
      ) : (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '11px',
            fontWeight: 600,
            padding: '4px 10px',
            borderRadius: '9999px',
            background: 'rgba(16, 185, 129, 0.15)',
            border: '1px solid #10b981',
            color: '#34d399',
          }}
        >
          <span
            style={{
              width: '6px',
              height: '6px',
              borderRadius: '50%',
              background: '#10b981',
            }}
          />
          ONLINE (v{clientVersion})
        </span>
      )}

      {/* Pending Conflict Indicator */}
      {conflicts.length > 0 && (
        <button
          onClick={() => {
            setSelectedConflict(conflicts[0]);
            setShowModal(true);
          }}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            fontSize: '11px',
            fontWeight: 700,
            padding: '4px 10px',
            borderRadius: '9999px',
            background: 'rgba(239, 68, 68, 0.2)',
            border: '1px solid #ef4444',
            color: '#f87171',
            cursor: 'pointer',
          }}
        >
          ⚠️ {conflicts.length} Conflict{conflicts.length > 1 ? 's' : ''}
        </button>
      )}

      {/* Action Popover Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
        <button
          onClick={handleToggleOffline}
          title={isSimulated ? 'Exit Field Simulation' : 'Simulate Field Disconnect'}
          style={{
            fontSize: '11px',
            padding: '4px 8px',
            borderRadius: '4px',
            background: isSimulated ? '#78350f' : '#1f2937',
            border: `1px solid ${isSimulated ? '#f59e0b' : '#374151'}`,
            color: isSimulated ? '#fde68a' : '#9ca3af',
            cursor: 'pointer',
          }}
        >
          {isSimulated ? '📡 Reconnect' : '📵 Field Mode'}
        </button>

        {!isCached && (
          <button
            onClick={handleCacheOffline}
            title="Download full case snapshot for offline field operations"
            style={{
              fontSize: '11px',
              padding: '4px 8px',
              borderRadius: '4px',
              background: '#1f2937',
              border: '1px solid #374151',
              color: '#d1d5db',
              cursor: 'pointer',
            }}
          >
            💾 Cache Case
          </button>
        )}

        {(queuedCount > 0 || isOnline) && (
          <button
            onClick={handleSyncNow}
            disabled={isSyncing || !isOnline}
            title="Synchronize queued mutations against server"
            style={{
              fontSize: '11px',
              padding: '4px 8px',
              borderRadius: '4px',
              background: '#2563eb',
              border: '1px solid #3b82f6',
              color: '#ffffff',
              cursor: isSyncing || !isOnline ? 'not-allowed' : 'pointer',
              opacity: isSyncing || !isOnline ? 0.6 : 1,
            }}
          >
            Sync
          </button>
        )}
      </div>

      {/* Sync Summary Notification */}
      {syncSummary && (
        <div
          style={{
            position: 'absolute',
            top: '48px',
            right: '24px',
            background: '#111827',
            border: '1px solid #374151',
            borderRadius: '8px',
            padding: '12px 16px',
            boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
            zIndex: 9999,
            fontSize: '12px',
            maxWidth: '320px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
            <span style={{ fontWeight: 600, color: syncSummary.success ? '#34d399' : '#f87171' }}>
              {syncSummary.success ? '✓ Synchronization Complete' : '✕ Sync Error'}
            </span>
            <button
              onClick={() => setSyncSummary(null)}
              style={{ background: 'none', border: 'none', color: '#9ca3af', cursor: 'pointer' }}
            >
              ×
            </button>
          </div>
          {syncSummary.success ? (
            <div style={{ color: '#d1d5db', lineHeight: '1.5' }}>
              <div>Accepted: <b>{syncSummary.acceptedCount}</b></div>
              <div>Rebased: <b>{syncSummary.rebasedCount}</b></div>
              {syncSummary.conflictCount > 0 && (
                <div style={{ color: '#f87171' }}>Conflicts: <b>{syncSummary.conflictCount}</b></div>
              )}
              {syncSummary.rejectedCount > 0 && (
                <div style={{ color: '#fbbf24' }}>Rejected: <b>{syncSummary.rejectedCount}</b></div>
              )}
              <div style={{ marginTop: '4px', fontSize: '11px', color: '#9ca3af' }}>
                Server state version: v{syncSummary.newServerVersion}
              </div>
            </div>
          ) : (
            <div style={{ color: '#f87171' }}>{syncSummary.error}</div>
          )}
        </div>
      )}

      {/* Conflict Adjudication Modal */}
      {showModal && selectedConflict && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(4px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            zIndex: 10000,
          }}
        >
          <div
            style={{
              background: '#181f2a',
              border: '1px solid #374151',
              borderRadius: '12px',
              padding: '24px',
              maxWidth: '680px',
              width: '90%',
              boxShadow: '0 20px 40px rgba(0,0,0,0.8)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '16px', color: '#f9fafb', fontWeight: 600 }}>
                  ⚖️ Adjudicate Offline Conflict
                </h3>
                <span style={{ fontSize: '12px', color: '#ef4444', fontWeight: 500 }}>
                  {selectedConflict.conflict_type} (Command: {selectedConflict.command_type})
                </span>
              </div>
              <button
                onClick={() => setShowModal(false)}
                style={{ background: 'none', border: 'none', color: '#9ca3af', fontSize: '18px', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <p style={{ fontSize: '12px', color: '#9ca3af', marginBottom: '16px', lineHeight: 1.5 }}>
              This offline mutation diverged from the authoritative server state. The server state has not been overwritten.
              Select an adjudication decision and provide your formal investigative rationale.
            </p>

            {/* Side by side comparison */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
              <div
                style={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: '8px',
                  padding: '12px',
                }}
              >
                <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 600, marginBottom: '6px' }}>
                  OFFLINE MUTATION (Base v{selectedConflict.base_state_version})
                </div>
                <div style={{ fontSize: '11px', color: '#cbd5e1' }}>
                  <b>Device:</b> {selectedConflict.client_payload?.device_id || 'FIELD-DEVICE'}<br />
                  <b>Decision / Payload:</b>
                  <pre style={{ fontSize: '10px', background: '#020617', padding: '6px', borderRadius: '4px', marginTop: '4px', overflowX: 'auto' }}>
                    {JSON.stringify(selectedConflict.client_payload, null, 2)}
                  </pre>
                </div>
              </div>

              <div
                style={{
                  background: '#0f172a',
                  border: '1px solid #1e293b',
                  borderRadius: '8px',
                  padding: '12px',
                }}
              >
                <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 600, marginBottom: '6px' }}>
                  SERVER CURRENT STATE (Server v{selectedConflict.server_state_version})
                </div>
                <div style={{ fontSize: '11px', color: '#cbd5e1' }}>
                  <b>Status:</b> Authoritative State Preserved<br />
                  <b>Current Row State:</b>
                  <pre style={{ fontSize: '10px', background: '#020617', padding: '6px', borderRadius: '4px', marginTop: '4px', overflowX: 'auto' }}>
                    {JSON.stringify(selectedConflict.server_current_state, null, 2)}
                  </pre>
                </div>
              </div>
            </div>

            {/* Investigative Rationale Field */}
            <div style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', fontSize: '11px', color: '#e2e8f0', fontWeight: 600, marginBottom: '6px' }}>
                Investigative Adjudication Rationale (Audited) *
              </label>
              <textarea
                value={resolutionRationale}
                onChange={(e) => setResolutionRationale(e.target.value)}
                placeholder="Enter formal justification for accepting server state, superseding with offline decision, or re-opening review..."
                rows={3}
                style={{
                  width: '100%',
                  background: '#0b1120',
                  border: '1px solid #334155',
                  borderRadius: '6px',
                  color: '#f1f5f9',
                  fontSize: '12px',
                  padding: '8px',
                  resize: 'none',
                }}
              />
            </div>

            {/* Decision Buttons */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                onClick={() => handleResolve('KEEP_SERVER')}
                disabled={isResolving}
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  padding: '8px 14px',
                  borderRadius: '6px',
                  background: '#1e293b',
                  border: '1px solid #475569',
                  color: '#f1f5f9',
                  cursor: isResolving ? 'not-allowed' : 'pointer',
                }}
              >
                🛡️ Keep Server State
              </button>
              <button
                onClick={() => handleResolve('APPLY_OFFLINE')}
                disabled={isResolving}
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  padding: '8px 14px',
                  borderRadius: '6px',
                  background: '#b45309',
                  border: '1px solid #f59e0b',
                  color: '#ffffff',
                  cursor: isResolving ? 'not-allowed' : 'pointer',
                }}
              >
                ⚡ Apply Offline Decision
              </button>
              <button
                onClick={() => handleResolve('CREATE_NEW_REVIEW')}
                disabled={isResolving}
                style={{
                  fontSize: '12px',
                  fontWeight: 600,
                  padding: '8px 14px',
                  borderRadius: '6px',
                  background: '#4338ca',
                  border: '1px solid #6366f1',
                  color: '#ffffff',
                  cursor: isResolving ? 'not-allowed' : 'pointer',
                }}
              >
                🔄 Re-Open Joint Review
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
