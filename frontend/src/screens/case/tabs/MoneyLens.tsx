import React from 'react';
import type { ForensicLensResponse, LensEvent, LensRelationship } from '../../../types/lenses';
import s from './ForensicLenses.module.css';

interface MoneyLensProps {
  data: ForensicLensResponse;
  onOpenEvidence?: (evidenceId: string) => void;
  onSelectEntity?: (entityId: string) => void;
}

export function MoneyLens({ data, onOpenEvidence, onSelectEntity }: MoneyLensProps) {
  const summary = data.summary || {};
  const totalVolume = summary.total_volume || 0;
  const txnCount = summary.transaction_count || data.events.length;
  const rapidCount = summary.rapid_transfer_signals || 0;
  const roundCount = summary.round_number_signals || 0;

  // Format currency (INR)
  const formatAmount = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val);
  };

  return (
    <div className={s.lensContent}>
      {/* 1. Stat Cards */}
      <div className={s.statGrid}>
        <div className={s.statCard}>
          <span className={s.statLabel}>Total Volume Tracked</span>
          <span className={s.statValue} style={{ color: '#F59E0B' }}>
            {formatAmount(totalVolume)}
          </span>
          <span className={s.statSub}>{txnCount} recorded transactions</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Identified Accounts</span>
          <span className={s.statValue}>{data.entities.length}</span>
          <span className={s.statSub}>Bank accounts & UPI VPAs</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Rapid Velocity Transits</span>
          <span className={s.statValue} style={{ color: rapidCount > 0 ? '#EF4444' : 'var(--text-primary)' }}>
            {rapidCount}
          </span>
          <span className={s.statSub}>Inflow-outflow &lt; 15 mins</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Round-Number Flags</span>
          <span className={s.statValue} style={{ color: roundCount > 0 ? '#F59E0B' : 'var(--text-primary)' }}>
            {roundCount}
          </span>
          <span className={s.statSub}>Multiples of ₹10,000 / ₹50,000</span>
        </div>
      </div>

      {/* 2. Rapid Transfer & Behavioral Signals */}
      {data.signals.length > 0 && (
        <div className={s.signalList}>
          <h4 style={{ margin: '0 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            DETECTED FINANCIAL SIGNALS & ANOMALIES
          </h4>
          {data.signals.map((sig) => {
            const isRapid = sig.signal_type === 'RAPID_TRANSFER';
            const isRound = sig.signal_type === 'ROUND_NUMBER_TXN';
            const cardClass = isRapid ? s.signalCritical : isRound ? s.signalHigh : s.signalInfo;

            return (
              <div key={sig.id} className={`${s.signalCard} ${cardClass}`}>
                <div className={s.signalBody}>
                  <div className={s.signalTitle}>
                    <span>{sig.title}</span>
                    <span style={{ fontSize: '0.7rem', opacity: 0.8, fontFamily: 'var(--type-mono)' }}>
                      {sig.severity} SEVERITY
                    </span>
                  </div>
                  <div className={s.signalDesc}>{sig.description}</div>
                  {sig.timestamp && (
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--type-mono)' }}>
                      Timestamp: {new Date(sig.timestamp).toLocaleString()}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* 3. Account Flow Cards */}
      {data.relationships.length > 0 && (
        <div>
          <h4 style={{ margin: 'var(--space-3) 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            ACCOUNT-TO-ACCOUNT TRANSFER FLOWS
          </h4>
          <div className={s.flowCards}>
            {data.relationships.map((rel: LensRelationship) => {
              const srcVal = rel.source_entity_value || rel.source_entity_id;
              const tgtVal = rel.target_entity_value || rel.target_entity_id;
              const isCanonical = rel.is_canonical;

              return (
                <div key={rel.id} className={s.flowCard}>
                  <div className={s.flowHeader}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--type-mono)' }}>
                      {rel.relationship_type} · {rel.epistemic_status}
                    </span>
                    {isCanonical ? (
                      <span style={{ fontSize: '0.68rem', color: '#10B981', background: 'rgba(16, 185, 129, 0.1)', padding: '2px 6px', borderRadius: 3 }}>
                        CANONICAL
                      </span>
                    ) : (
                      <span style={{ fontSize: '0.68rem', color: '#94A3B8', background: 'rgba(148, 163, 184, 0.1)', padding: '2px 6px', borderRadius: 3 }}>
                        ANALYTICAL
                      </span>
                    )}
                  </div>
                  <div className={s.flowPath}>
                    <span
                      onClick={() => onSelectEntity?.(rel.source_entity_id)}
                      style={{ cursor: onSelectEntity ? 'pointer' : 'default', fontWeight: 600, color: 'var(--text-primary)' }}
                      title="Filter by this account"
                    >
                      {srcVal}
                    </span>
                    <span className={s.flowArrow}>➔</span>
                    <span
                      onClick={() => onSelectEntity?.(rel.target_entity_id)}
                      style={{ cursor: onSelectEntity ? 'pointer' : 'default', fontWeight: 600, color: 'var(--text-primary)' }}
                      title="Filter by this account"
                    >
                      {tgtVal}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      Confidence: {Math.round(rel.confidence * 100)}%
                    </span>
                    {rel.evidence_refs.length > 0 && onOpenEvidence && (
                      <span
                        className={s.provBadge}
                        onClick={() => onOpenEvidence(rel.evidence_refs[0])}
                      >
                        Source File
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 4. Complete Traceable Ledger */}
      <div>
        <h4 style={{ margin: 'var(--space-4) 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          TRANSACTION FORENSIC LEDGER ({data.events.length} RECORDS)
        </h4>
        <div className={s.tableContainer}>
          <table className={s.lensTable}>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Type</th>
                <th>Sender / Source</th>
                <th>Receiver / Target</th>
                <th>Amount</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {data.events.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
                    No financial transaction events recorded in this case scope.
                  </td>
                </tr>
              ) : (
                data.events.map((ev: LensEvent) => {
                  const d = ev.details || {};
                  const amount = d.amount ? formatAmount(Number(d.amount)) : '—';
                  const sender = d.sender || d.source_account || '—';
                  const receiver = d.receiver || d.target_account || '—';
                  const timeFormatted = ev.event_time ? new Date(ev.event_time).toLocaleString() : 'Undated';

                  return (
                    <tr key={ev.id}>
                      <td style={{ fontFamily: 'var(--type-mono)', whiteSpace: 'nowrap' }}>
                        <div>{timeFormatted}</div>
                        {ev.time_confidence !== 'CONFIRMED' && (
                          <div style={{ fontSize: '0.65rem', color: '#F59E0B' }}>
                            [{ev.time_confidence}]
                          </div>
                        )}
                      </td>
                      <td style={{ fontFamily: 'var(--type-mono)', textTransform: 'uppercase' }}>
                        {ev.event_type.replace('_', ' ')}
                      </td>
                      <td style={{ fontWeight: 600 }}>{sender}</td>
                      <td style={{ fontWeight: 600 }}>{receiver}</td>
                      <td style={{ fontFamily: 'var(--type-mono)', color: '#F59E0B', fontWeight: 700 }}>
                        {amount}
                      </td>
                      <td>
                        {ev.source_doc ? (
                          <span
                            className={s.provBadge}
                            onClick={() => ev.evidence_file_id && onOpenEvidence?.(ev.evidence_file_id)}
                            title={`Doc: ${ev.source_doc} (Page ${ev.source_page ?? '—'}, Line ${ev.source_line ?? '—'})`}
                          >
                            📄 {ev.source_doc.length > 15 ? ev.source_doc.slice(0, 15) + '…' : ev.source_doc}
                            {ev.source_page ? ` :P${ev.source_page}` : ''}
                            {ev.source_line ? ` :L${ev.source_line}` : ''}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.7rem' }}>Direct Record</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
