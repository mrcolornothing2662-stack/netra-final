import React from 'react';
import type { ForensicLensResponse, LensEvent, LensRelationship } from '../../../types/lenses';
import s from './ForensicLenses.module.css';

interface CommunicationLensProps {
  data: ForensicLensResponse;
  onOpenEvidence?: (evidenceId: string) => void;
  onSelectEntity?: (entityId: string) => void;
}

export function CommunicationLens({ data, onOpenEvidence, onSelectEntity }: CommunicationLensProps) {
  const summary = data.summary || {};
  const totalCalls = summary.call_count || 0;
  const totalMsgs = summary.message_count || 0;
  const totalComms = summary.total_communications || data.events.length;
  const burstCount = summary.burst_count || 0;
  const nightCount = summary.night_activity_count || 0;
  const heatmap: Record<string, number> = summary.hourly_distribution || {};

  // Find peak hour for heatmap scaling
  const maxHourVal = Math.max(...Object.values(heatmap), 1);

  // Format seconds into MM:SS or HH:MM:SS
  const formatDuration = (secs: number) => {
    if (!secs) return '0s';
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    if (m > 60) {
      const h = Math.floor(m / 60);
      return `${h}h ${m % 60}m`;
    }
    return `${m}m ${s}s`;
  };

  return (
    <div className={s.lensContent}>
      {/* 1. Stat Cards */}
      <div className={s.statGrid}>
        <div className={s.statCard}>
          <span className={s.statLabel}>Total Communications</span>
          <span className={s.statValue} style={{ color: '#06B6D4' }}>
            {totalComms}
          </span>
          <span className={s.statSub}>
            {totalCalls} calls · {totalMsgs} chats/SMS
          </span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Monitored Numbers</span>
          <span className={s.statValue}>{data.entities.length}</span>
          <span className={s.statSub}>Phone identifiers & contacts</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>30-Min High-Frequency Bursts</span>
          <span className={s.statValue} style={{ color: burstCount > 0 ? '#EF4444' : 'var(--text-primary)' }}>
            {burstCount}
          </span>
          <span className={s.statSub}>&ge; 5 communications within 30 mins</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Late-Night Activity</span>
          <span className={s.statValue} style={{ color: nightCount > 0 ? '#F59E0B' : 'var(--text-primary)' }}>
            {nightCount}
          </span>
          <span className={s.statSub}>Events between 23:00 - 05:00</span>
        </div>
      </div>

      {/* 2. 24-Hour Temporal Heatmap */}
      <div className={s.heatmapContainer}>
        <div className={s.heatmapTitle}>
          <span>24-HOUR TEMPORAL DISTRIBUTION (COMMUNICATION INTENSITY)</span>
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Peak: {maxHourVal} events/hr</span>
        </div>
        <div className={s.heatmapGrid}>
          {Array.from({ length: 24 }).map((_, hour) => {
            const count = heatmap[String(hour)] || 0;
            const heightPct = Math.round((count / maxHourVal) * 100);
            const isNight = hour >= 23 || hour < 5;

            return (
              <div key={hour} className={s.heatmapBarCol} title={`${hour}:00 - ${hour + 1}:00: ${count} events`}>
                <div
                  className={s.heatmapBar}
                  style={{
                    height: `${Math.max(heightPct, 4)}%`,
                    background: isNight && count > 0 ? '#F59E0B' : undefined,
                  }}
                />
                <span className={s.heatmapHourLabel}>{hour}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 3. Communication Burst & Anomaly Alerts */}
      {data.signals.length > 0 && (
        <div className={s.signalList}>
          <h4 style={{ margin: '0 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            COMMUNICATION PATTERNS & BURST DETECTIONS
          </h4>
          {data.signals.map((sig) => {
            const isBurst = sig.signal_type === 'COMMUNICATION_BURST';
            const isNight = sig.signal_type === 'NIGHT_ACTIVITY';
            const cardClass = isBurst ? s.signalCritical : isNight ? s.signalHigh : s.signalInfo;

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

      {/* 4. Active Contact Pairs */}
      {data.relationships.length > 0 && (
        <div>
          <h4 style={{ margin: 'var(--space-3) 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            INTERACTION GRAPH & CALL PAIRS
          </h4>
          <div className={s.flowCards}>
            {data.relationships.map((rel: LensRelationship) => {
              const srcVal = rel.source_entity_value || rel.source_entity_id;
              const tgtVal = rel.target_entity_value || rel.target_entity_id;

              return (
                <div key={rel.id} className={s.flowCard}>
                  <div className={s.flowHeader}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--type-mono)' }}>
                      {rel.relationship_type} · {rel.direction}
                    </span>
                    <span style={{ fontSize: '0.68rem', color: '#06B6D4', background: 'rgba(6, 182, 212, 0.1)', padding: '2px 6px', borderRadius: 3 }}>
                      {rel.epistemic_status}
                    </span>
                  </div>
                  <div className={s.flowPath}>
                    <span
                      onClick={() => onSelectEntity?.(rel.source_entity_id)}
                      style={{ cursor: onSelectEntity ? 'pointer' : 'default', fontWeight: 600, color: 'var(--text-primary)' }}
                    >
                      {srcVal}
                    </span>
                    <span style={{ color: '#06B6D4' }}>↔</span>
                    <span
                      onClick={() => onSelectEntity?.(rel.target_entity_id)}
                      style={{ cursor: onSelectEntity ? 'pointer' : 'default', fontWeight: 600, color: 'var(--text-primary)' }}
                    >
                      {tgtVal}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4 }}>
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                      Confidence: {Math.round(rel.confidence * 100)}%
                    </span>
                    {rel.evidence_refs.length > 0 && onOpenEvidence && (
                      <span className={s.provBadge} onClick={() => onOpenEvidence(rel.evidence_refs[0])}>
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

      {/* 5. Complete CDR & Communication Ledger */}
      <div>
        <h4 style={{ margin: 'var(--space-4) 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          COMMUNICATIONS AUDIT RECORD ({data.events.length} EVENTS)
        </h4>
        <div className={s.tableContainer}>
          <table className={s.lensTable}>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Type</th>
                <th>Caller / Sender</th>
                <th>Receiver / Recipient</th>
                <th>Duration / Content</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {data.events.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
                    No communication events recorded in this case scope.
                  </td>
                </tr>
              ) : (
                data.events.map((ev: LensEvent) => {
                  const d = ev.details || {};
                  const caller = d.caller || d.sender || d.source_phone || '—';
                  const callee = d.callee || d.recipient || d.target_phone || '—';
                  const duration = d.duration_sec !== undefined ? formatDuration(Number(d.duration_sec)) : d.message_snippet || '—';
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
                      <td style={{ fontWeight: 600 }}>{caller}</td>
                      <td style={{ fontWeight: 600 }}>{callee}</td>
                      <td style={{ fontFamily: 'var(--type-mono)' }}>{duration}</td>
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
