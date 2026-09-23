import React, { useState, useEffect } from 'react';
import { getLensesOverview, getForensicLens } from '../../../api/lenses';
import type {
  ForensicLensResponse,
  LensOverviewResponse,
  ForensicLensType,
  CrossLensSignal,
} from '../../../types/lenses';
import { MoneyLens } from './MoneyLens';
import { CommunicationLens } from './CommunicationLens';
import { GeographicLens } from './GeographicLens';
import s from './ForensicLenses.module.css';

interface ForensicLensesProps {
  caseId: string;
  onOpenEvidence?: (evidenceId: string) => void;
}

export function ForensicLenses({ caseId, onOpenEvidence }: ForensicLensesProps) {
  const [activeLens, setActiveLens] = useState<ForensicLensType>('MONEY');
  const [overview, setOverview] = useState<LensOverviewResponse | null>(null);
  const [lensData, setLensData] = useState<ForensicLensResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [entityFilter, setEntityFilter] = useState<string>('');
  const [activeEntityId, setActiveEntityId] = useState<string | undefined>(undefined);
  const [showCrossLensDrawer, setShowCrossLensDrawer] = useState<boolean>(true);

  // Load Overview once
  useEffect(() => {
    let isMounted = true;
    getLensesOverview(caseId)
      .then((res) => {
        if (isMounted) setOverview(res);
      })
      .catch((err) => {
        console.warn('Could not load lenses overview:', err);
      });
    return () => {
      isMounted = false;
    };
  }, [caseId]);

  // Load Active Lens Projection
  useEffect(() => {
    let isMounted = true;
    setLoading(true);
    setError(null);

    getForensicLens(caseId, activeLens, {
      entityId: activeEntityId || undefined,
    })
      .then((res) => {
        if (isMounted) {
          setLensData(res);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err?.message || 'Failed to load forensic lens data');
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [caseId, activeLens, activeEntityId]);

  const handleApplyEntityFilter = (e: React.FormEvent) => {
    e.preventDefault();
    setActiveEntityId(entityFilter.trim() || undefined);
  };

  const handleClearEntityFilter = () => {
    setEntityFilter('');
    setActiveEntityId(undefined);
  };

  const handleSelectEntity = (entId: string) => {
    setEntityFilter(entId);
    setActiveEntityId(entId);
  };

  return (
    <div className={s.container}>
      {/* 1. Header & Switcher */}
      <div className={s.headerBar}>
        <div className={s.titleArea}>
          <div className={s.title}>
            <span>FORENSIC LENSES</span>
            <span style={{ fontSize: '0.75rem', color: '#00F0FF', fontFamily: 'var(--type-mono)' }}>
              V5 MULTI-PERSPECTIVE ENGINE
            </span>
          </div>
          <div className={s.subtitle}>
            Read-only analytical projections over the canonical Investigation Brain. Lenses do not mutate state or create disjoint databases.
          </div>
        </div>

        {/* Lens Switcher */}
        <div className={s.lensSwitcher} role="tablist">
          <button
            role="tab"
            aria-selected={activeLens === 'MONEY'}
            className={`${s.lensTabBtn} ${activeLens === 'MONEY' ? s.lensTabMoneyActive : ''}`}
            onClick={() => setActiveLens('MONEY')}
          >
            <span>💰 MONEY TRAIL</span>
            {overview?.money_summary && (
              <span style={{ fontSize: '0.7rem', opacity: 0.8 }}>
                ({overview.money_summary.transaction_count ?? 0})
              </span>
            )}
          </button>

          <button
            role="tab"
            aria-selected={activeLens === 'COMMUNICATION'}
            className={`${s.lensTabBtn} ${activeLens === 'COMMUNICATION' ? s.lensTabCommsActive : ''}`}
            onClick={() => setActiveLens('COMMUNICATION')}
          >
            <span>📞 COMMUNICATIONS</span>
            {overview?.communications_summary && (
              <span style={{ fontSize: '0.7rem', opacity: 0.8 }}>
                ({overview.communications_summary.communication_count ?? 0})
              </span>
            )}
          </button>

          <button
            role="tab"
            aria-selected={activeLens === 'GEOGRAPHIC'}
            className={`${s.lensTabBtn} ${activeLens === 'GEOGRAPHIC' ? s.lensTabGeoActive : ''}`}
            onClick={() => setActiveLens('GEOGRAPHIC')}
          >
            <span>📡 TRAVEL / GEO</span>
            {overview?.geographic_summary && (
              <span style={{ fontSize: '0.7rem', opacity: 0.8 }}>
                ({overview.geographic_summary.observation_count ?? 0})
              </span>
            )}
          </button>
        </div>
      </div>

      {/* 2. Filter Bar */}
      <div className={s.filterBar}>
        <form onSubmit={handleApplyEntityFilter} style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <div className={s.filterItem}>
            <span>Entity / Number:</span>
            <input
              type="text"
              className={s.filterInput}
              placeholder="e.g. +919876543210, ACC-..., UPI VPA"
              value={entityFilter}
              onChange={(e) => setEntityFilter(e.target.value)}
              style={{ width: '220px' }}
            />
            <button
              type="submit"
              className={s.filterSelect}
              style={{ cursor: 'pointer', background: 'rgba(0, 240, 255, 0.12)', color: '#00F0FF', border: '1px solid rgba(0, 240, 255, 0.3)' }}
            >
              Filter
            </button>
            {activeEntityId && (
              <button
                type="button"
                className={s.filterSelect}
                onClick={handleClearEntityFilter}
                style={{ cursor: 'pointer', color: '#FDA4AF' }}
              >
                Clear
              </button>
            )}
          </div>
        </form>

        {activeEntityId && (
          <div style={{ fontSize: '0.75rem', color: '#00F0FF', fontFamily: 'var(--type-mono)' }}>
            Active Filter: <strong style={{ color: '#FFFFFF' }}>{activeEntityId}</strong>
          </div>
        )}

        {lensData?.is_historical && (
          <div style={{ fontSize: '0.75rem', color: '#F59E0B', fontFamily: 'var(--type-mono)', marginLeft: 'auto' }}>
            ⚡ Historical Projection (Case Version {lensData.state_version})
          </div>
        )}
      </div>

      {/* 3. Cross-Lens Coincidence Banner */}
      {lensData?.cross_lens_signals && lensData.cross_lens_signals.length > 0 && (
        <div className={s.crossLensBanner}>
          <div className={s.crossLensHeader}>
            <span>⚡ CROSS-DOMAIN COINCIDENCE DETECTED ({lensData.cross_lens_signals.length} INSTANCES)</span>
            <button
              onClick={() => setShowCrossLensDrawer(!showCrossLensDrawer)}
              style={{ background: 'none', border: 'none', color: '#C4B5FD', cursor: 'pointer', fontSize: '0.75rem' }}
            >
              {showCrossLensDrawer ? '▲ Hide' : '▼ View Coincidences'}
            </button>
          </div>
          {showCrossLensDrawer &&
            lensData.cross_lens_signals.map((sig: CrossLensSignal) => (
              <div key={sig.id} className={s.crossLensItem}>
                <div>
                  <strong>{sig.title}</strong> — {sig.description}
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ fontSize: '0.7rem', color: '#A78BFA', fontFamily: 'var(--type-mono)' }}>
                    Confidence: {Math.round(sig.confidence * 100)}%
                  </span>
                </div>
              </div>
            ))}
        </div>
      )}

      {/* 4. Active Lens View */}
      {loading ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-secondary)' }}>
          Loading forensic lens projection...
        </div>
      ) : error ? (
        <div style={{ padding: '20px', background: 'rgba(239, 68, 68, 0.1)', color: '#EF4444', borderRadius: 'var(--radius-md)' }}>
          Error loading lens: {error}
        </div>
      ) : !lensData ? (
        <div style={{ padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
          No data available for this lens.
        </div>
      ) : activeLens === 'MONEY' ? (
        <MoneyLens
          data={lensData}
          onOpenEvidence={onOpenEvidence}
          onSelectEntity={handleSelectEntity}
        />
      ) : activeLens === 'COMMUNICATION' ? (
        <CommunicationLens
          data={lensData}
          onOpenEvidence={onOpenEvidence}
          onSelectEntity={handleSelectEntity}
        />
      ) : (
        <GeographicLens
          data={lensData}
          onOpenEvidence={onOpenEvidence}
          onSelectEntity={handleSelectEntity}
        />
      )}
    </div>
  );
}
