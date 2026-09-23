import React from 'react';
import type { ReplayVersionItem } from '../../../types/timeline';
import s from './TimelineTab.module.css';

interface ReplayDeckProps {
  currentVersion: number;
  totalVersions: number;
  currentCaseVersion: number;
  versions: ReplayVersionItem[];
  isPlaying: boolean;
  playSpeed: number;
  onSelectVersion: (version: number) => void;
  onTogglePlay: () => void;
  onChangeSpeed: (speed: number) => void;
}

export const ReplayDeck: React.FC<ReplayDeckProps> = ({
  currentVersion,
  totalVersions,
  currentCaseVersion,
  versions,
  isPlaying,
  playSpeed,
  onSelectVersion,
  onTogglePlay,
  onChangeSpeed,
}) => {
  const isHistorical = currentVersion < currentCaseVersion;
  const currentVersionItem = versions.find(v => v.version === currentVersion);

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSelectVersion(Number(e.target.value));
  };

  const handleStepBack = () => {
    if (currentVersion > 1) {
      onSelectVersion(currentVersion - 1);
    }
  };

  const handleStepForward = () => {
    if (currentVersion < totalVersions) {
      onSelectVersion(currentVersion + 1);
    }
  };

  return (
    <div className={s.replayDeck}>
      {isHistorical && (
        <div className={s.historicalNotice}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className={s.historicalTag}>HISTORICAL PROJECTION</span>
            <span>
              Viewing investigation state at <strong>v{currentVersion}</strong> (current case version is <strong>v{currentCaseVersion}</strong>).
            </span>
          </div>
          <button
            className={s.modeBtn}
            style={{ fontSize: '0.7rem', padding: '2px 8px', border: '1px solid rgba(139, 92, 246, 0.4)' }}
            onClick={() => onSelectVersion(currentCaseVersion)}
          >
            Jump to Present (v{currentCaseVersion}) ⏭
          </button>
        </div>
      )}

      <div className={s.replayControlsRow}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div className={s.playbackGroup}>
            <button
              className={s.playbackBtn}
              onClick={() => onSelectVersion(1)}
              disabled={currentVersion <= 1}
              title="First Version (v1)"
            >
              ⏮
            </button>
            <button
              className={s.playbackBtn}
              onClick={handleStepBack}
              disabled={currentVersion <= 1}
              title="Step Back 1 Version"
            >
              ◀
            </button>
            <button
              className={`${s.playbackBtn} ${s.playbackBtnPlay}`}
              onClick={onTogglePlay}
              title={isPlaying ? 'Pause Replay' : 'Play Replay'}
            >
              {isPlaying ? '⏸' : '▶'}
            </button>
            <button
              className={s.playbackBtn}
              onClick={handleStepForward}
              disabled={currentVersion >= totalVersions}
              title="Step Forward 1 Version"
            >
              ▶
            </button>
            <button
              className={s.playbackBtn}
              onClick={() => onSelectVersion(totalVersions)}
              disabled={currentVersion >= totalVersions}
              title="Latest Version"
            >
              ⏭
            </button>
          </div>

          <div className={s.speedSelect}>
            {[1, 2, 4].map(spd => (
              <button
                key={spd}
                className={`${s.speedOption} ${playSpeed === spd ? s.speedOptionActive : ''}`}
                onClick={() => onChangeSpeed(spd)}
              >
                {spd}x
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span className={s.versionBadge}>
            VERSION {currentVersion} / {totalVersions}
          </span>
          {currentVersionItem?.timestamp && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--type-mono)' }}>
              {new Date(currentVersionItem.timestamp).toLocaleString()}
            </span>
          )}
        </div>
      </div>

      <div className={s.versionScrubberTrack}>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--type-mono)' }}>v1</span>
        <input
          type="range"
          min={1}
          max={totalVersions || 1}
          value={currentVersion}
          onChange={handleSliderChange}
          className={s.scrubberSlider}
        />
        <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontFamily: 'var(--type-mono)' }}>
          v{totalVersions}
        </span>
      </div>

      {currentVersionItem && (
        <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', borderTop: '1px dashed var(--line)', paddingTop: '8px' }}>
          <strong style={{ color: 'var(--text-primary)' }}>Trigger: </strong>
          <span style={{ color: '#00F0FF', fontFamily: 'var(--type-mono)' }}>{currentVersionItem.activity_type}</span>
          {' — '}
          <span>{currentVersionItem.summary}</span>
          {currentVersionItem.actor && (
            <span style={{ marginLeft: '8px', color: 'var(--text-muted)' }}>
              (actor: {currentVersionItem.actor})
            </span>
          )}
        </div>
      )}
    </div>
  );
};
