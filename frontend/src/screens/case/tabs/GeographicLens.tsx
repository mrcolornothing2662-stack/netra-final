import React from 'react';
import type { ForensicLensResponse, LensEvent } from '../../../types/lenses';
import s from './ForensicLenses.module.css';

interface GeographicLensProps {
  data: ForensicLensResponse;
  onOpenEvidence?: (evidenceId: string) => void;
  onSelectEntity?: (entityId: string) => void;
}

export function GeographicLens({ data, onOpenEvidence, onSelectEntity }: GeographicLensProps) {
  const summary = data.summary || {};
  const totalObs = summary.total_observations || data.events.length;
  const uniqueTowers = summary.unique_towers_count || 0;
  const towerHops = summary.tower_hops_count || 0;
  const disclaimer = data.disclaimer || summary.disclaimer;

  // Extract tower hop movements from summary if present
  const hops: any[] = summary.tower_movements || [];

  return (
    <div className={s.lensContent}>
      {/* 1. Mandatory Evidentiary Disclaimer (Invariant 6) */}
      <div className={s.disclaimerBanner}>
        <span style={{ fontSize: '1.2rem', lineHeight: 1 }}>⚠️</span>
        <div>
          <span className={s.disclaimerTitle}>
            TECHNICAL LIMITATION — CELL-SITE TELEMETRY ≠ PHYSICAL GPS LOCATION
          </span>
          <div>
            {disclaimer ||
              'Observed cell-site association — NOT exact physical location. Mobile devices register with cellular base stations based on radio propagation, azimuth orientation, and network load balancing, not true GPS coordinates.'}
          </div>
        </div>
      </div>

      {/* 2. Stat Cards */}
      <div className={s.statGrid}>
        <div className={s.statCard}>
          <span className={s.statLabel}>Cell Observations</span>
          <span className={s.statValue} style={{ color: '#10B981' }}>
            {totalObs}
          </span>
          <span className={s.statSub}>Radio tower associations</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Distinct Towers / Sectors</span>
          <span className={s.statValue}>{uniqueTowers}</span>
          <span className={s.statSub}>Base transceiver stations</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Tower Hopping Sequences</span>
          <span className={s.statValue} style={{ color: towerHops > 0 ? '#F59E0B' : 'var(--text-primary)' }}>
            {towerHops}
          </span>
          <span className={s.statSub}>Rapid sector transitions</span>
        </div>
        <div className={s.statCard}>
          <span className={s.statLabel}>Monitored Identifiers</span>
          <span className={s.statValue}>{data.entities.length}</span>
          <span className={s.statSub}>IMSI / IMEI / MSISDN devices</span>
        </div>
      </div>

      {/* 3. Signals (Tower Hopping & Physical Anomalies) */}
      {data.signals.length > 0 && (
        <div className={s.signalList}>
          <h4 style={{ margin: '0 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            TRAVEL & CELL-SITE MOVEMENT SIGNALS
          </h4>
          {data.signals.map((sig) => {
            const isHop = sig.signal_type === 'TOWER_HOPPING';
            const cardClass = isHop ? s.signalHigh : s.signalInfo;

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

      {/* 4. Tower Hopping Movement Sequence */}
      {hops.length > 0 && (
        <div>
          <h4 style={{ margin: 'var(--space-3) 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            CHRONOLOGICAL TOWER MOVEMENT HOPS ({hops.length} DETECTED HOPS)
          </h4>
          <div className={s.hopTimeline}>
            {hops.map((h, idx) => (
              <div key={idx} className={s.hopItem}>
                <span className={s.hopSeq}>#{idx + 1}</span>
                <div className={s.hopDetails}>
                  <div className={s.hopTower}>
                    <span>{h.from_tower}</span>
                    <span style={{ color: '#10B981', margin: '0 8px' }}>➔</span>
                    <span>{h.to_tower}</span>
                  </div>
                  <div className={s.hopMeta}>
                    From: {new Date(h.from_time).toLocaleTimeString()} · To: {new Date(h.to_time).toLocaleTimeString()}
                  </div>
                </div>
                <div className={s.hopDelta}>
                  Δ {h.interval_minutes} mins
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 5. Complete Cell-Site Association Ledger */}
      <div>
        <h4 style={{ margin: 'var(--space-4) 0 var(--space-2) 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
          CELL-SITE OBSERVATION RECORDS ({data.events.length} OBSERVATIONS)
        </h4>
        <div className={s.tableContainer}>
          <table className={s.lensTable}>
            <thead>
              <tr>
                <th>Observed Time</th>
                <th>Monitored Phone / Entity</th>
                <th>Associated Tower ID</th>
                <th>Azimuth / Sector</th>
                <th>Time Quality</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {data.events.length === 0 ? (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
                    No cell-site or travel observations recorded in this case scope.
                  </td>
                </tr>
              ) : (
                data.events.map((ev: LensEvent) => {
                  const d = ev.details || {};
                  const phone = d.phone || d.monitored_identifier || '—';
                  const tower = d.tower_id || d.cell_id || ev.summary || '—';
                  const azimuth = d.azimuth !== undefined ? `${d.azimuth}°` : d.sector || '—';
                  const timeFormatted = ev.event_time ? new Date(ev.event_time).toLocaleString() : 'Undated';

                  return (
                    <tr key={ev.id}>
                      <td style={{ fontFamily: 'var(--type-mono)', whiteSpace: 'nowrap' }}>
                        {timeFormatted}
                      </td>
                      <td style={{ fontWeight: 600 }}>
                        <span
                          onClick={() => phone !== '—' && onSelectEntity?.(phone)}
                          style={{ cursor: phone !== '—' && onSelectEntity ? 'pointer' : 'default' }}
                        >
                          {phone}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--type-mono)', color: '#10B981', fontWeight: 600 }}>
                        {tower}
                      </td>
                      <td style={{ fontFamily: 'var(--type-mono)' }}>{azimuth}</td>
                      <td>
                        {ev.time_confidence === 'CONFIRMED' ? (
                          <span style={{ color: '#10B981', fontSize: '0.7rem' }}>✓ Confirmed</span>
                        ) : (
                          <span style={{ color: '#F59E0B', fontSize: '0.7rem' }}>
                            ⚠ {ev.time_confidence}
                          </span>
                        )}
                        {ev.time_warning && (
                          <div style={{ fontSize: '0.65rem', color: '#FDA4AF' }}>
                            {ev.time_warning}
                          </div>
                        )}
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
