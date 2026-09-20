import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Icon } from '../../../components/icons';
import { STORY_CONTENT } from '../data/storyContent';
import { startEnterTransition } from '../../../app/EnterOverlay';
import s from '../landing.module.css';

interface Props {
  storyProgress: number;
  onReplay: () => void;
}

interface LayerState {
  opacity: number;
  yOffset: number;
  blur: number;
}

interface ChapterTimelineState {
  id: string;
  name: string;
  isVisible: boolean;
  tag: LayerState;
  headline: LayerState;
  subheadline: LayerState;
  description: LayerState;
  detail: LayerState;
}

function smoothstep(min: number, max: number, value: number): number {
  const x = Math.max(0, Math.min(1, (value - min) / (max - min)));
  return x * x * (3 - 2 * x);
}

/**
 * Pure deterministic element lifecycle calculator.
 * Computes opacity, translateY, and subtle blur without animation lag.
 */
function calcLayer(
  p: number,
  enterStart: number,
  enterEnd: number,
  exitStart: number,
  exitEnd: number,
  isInitial = false,
  isFinal = false
): LayerState {
  // Chapter 1: Initial state holds from top
  if (isInitial) {
    if (p <= exitStart) {
      return { opacity: 1, yOffset: 0, blur: 0 };
    }
    if (p >= exitEnd) {
      return { opacity: 0, yOffset: -8, blur: 3 };
    }
    const t = (p - exitStart) / (exitEnd - exitStart);
    const opacity = 1 - smoothstep(0, 1, t);
    return { opacity, yOffset: -8 * t, blur: 3 * t };
  }

  // Chapter 6: Final resolution holds through bottom and overscroll
  if (isFinal) {
    if (p < enterStart) {
      return { opacity: 0, yOffset: 12, blur: 3 };
    }
    if (p >= enterEnd) {
      return { opacity: 1, yOffset: 0, blur: 0 };
    }
    const t = (p - enterStart) / (enterEnd - enterStart);
    const opacity = smoothstep(0, 1, t);
    return { opacity, yOffset: 12 * (1 - opacity), blur: 3 * (1 - opacity) };
  }

  if (p < enterStart || p > exitEnd) {
    return { opacity: 0, yOffset: p < enterStart ? 12 : -8, blur: 3 };
  }

  if (p < enterEnd) {
    const t = (p - enterStart) / (enterEnd - enterStart);
    const opacity = smoothstep(0, 1, t);
    return { opacity, yOffset: 12 * (1 - opacity), blur: 3 * (1 - opacity) };
  }

  if (p > exitStart) {
    const t = (p - exitStart) / (exitEnd - exitStart);
    const opacity = 1 - smoothstep(0, 1, t);
    return { opacity, yOffset: -8 * t, blur: 3 * t };
  }

  // Peak dwell plateau
  return { opacity: 1, yOffset: 0, blur: 0 };
}

/**
 * Computes decoupled staggered lifecycles for all 6 narrative chapters
 * and applies the Primary Focus Channel normalization so headlines never stack.
 */
function computeTimeline(p: number) {
  // 1. Compute decoupled staggered lifecycles with dedicated breathing windows
  // so the 3D background animation has clear, unblurred stages to shine.
  const ch1: ChapterTimelineState = {
    id: 'problem',
    name: 'THE PROBLEM',
    isVisible: false,
    tag: calcLayer(p, -0.1, -0.1, 0.08, 0.11, true),
    headline: calcLayer(p, -0.1, -0.1, 0.08, 0.11, true),
    subheadline: calcLayer(p, -0.1, -0.1, 0.07, 0.10, true),
    description: calcLayer(p, -0.1, -0.1, 0.06, 0.09, true),
    detail: calcLayer(p, -0.1, -0.1, 0.06, 0.09, true),
  };

  // Breathing Window 1 [0.11 - 0.18]: Isolated entities gravitate, filaments ignite

  const ch2: ChapterTimelineState = {
    id: 'correlation',
    name: 'CORRELATION',
    isVisible: false,
    tag: calcLayer(p, 0.18, 0.21, 0.28, 0.31),
    headline: calcLayer(p, 0.19, 0.22, 0.28, 0.31),
    subheadline: calcLayer(p, 0.20, 0.23, 0.26, 0.29),
    description: calcLayer(p, 0.21, 0.24, 0.25, 0.28),
    detail: calcLayer(p, 0.21, 0.24, 0.25, 0.28),
  };

  // Breathing Window 2 [0.31 - 0.38]: Connected graph web rotates in 3D

  const ch3: ChapterTimelineState = {
    id: 'graph',
    name: 'THE GRAPH',
    isVisible: false,
    tag: calcLayer(p, 0.38, 0.41, 0.47, 0.50),
    headline: calcLayer(p, 0.39, 0.42, 0.47, 0.50),
    subheadline: calcLayer(p, 0.40, 0.43, 0.45, 0.48),
    description: calcLayer(p, 0.41, 0.44, 0.44, 0.47),
    detail: calcLayer(p, 0.41, 0.44, 0.44, 0.47),
  };

  // Breathing Window 3 [0.50 - 0.56]: Multi-cluster isometric network expansion

  const ch4: ChapterTimelineState = {
    id: 'evidence',
    name: 'EVIDENCE TRAIL',
    isVisible: false,
    tag: calcLayer(p, 0.56, 0.59, 0.66, 0.69),
    headline: calcLayer(p, 0.57, 0.60, 0.66, 0.69),
    subheadline: calcLayer(p, 0.58, 0.61, 0.64, 0.67),
    description: calcLayer(p, 0.59, 0.62, 0.63, 0.66),
    detail: calcLayer(p, 0.57, 0.60, 0.65, 0.68),
  };

  // Breathing Window 4 [0.69 - 0.76]: Probe beam finish, noise reduction, rose halo bloom

  const ch5: ChapterTimelineState = {
    id: 'patterns',
    name: 'HIDDEN PATTERNS',
    isVisible: false,
    tag: calcLayer(p, 0.76, 0.79, 0.85, 0.88),
    headline: calcLayer(p, 0.77, 0.80, 0.85, 0.88),
    subheadline: calcLayer(p, 0.78, 0.81, 0.84, 0.87),
    description: calcLayer(p, 0.79, 0.82, 0.84, 0.87),
    detail: calcLayer(p, 0.79, 0.82, 0.84, 0.87),
  };

  // Breathing Window 5 [0.88 - 0.93]: Planar alignment into 2D isometric layout & framing brackets

  const ch6: ChapterTimelineState = {
    id: 'resolution',
    name: 'INTELLIGENCE',
    isVisible: false,
    tag: calcLayer(p, 0.93, 0.95, 5.0, 5.0, false, true),
    headline: calcLayer(p, 0.94, 0.96, 5.0, 5.0, false, true),
    subheadline: calcLayer(p, 0.95, 0.97, 5.0, 5.0, false, true),
    description: calcLayer(p, 0.95, 0.98, 5.0, 5.0, false, true),
    detail: calcLayer(p, 0.95, 0.98, 5.0, 5.0, false, true),
  };

  const chapters = [ch1, ch2, ch3, ch4, ch5, ch6];

  // 2. PRIMARY FOCUS CHANNEL NORMALIZATION
  // Guarantees that at no point do two adjacent primary headlines have opacity > 0.50
  for (let i = 0; i < chapters.length - 1; i++) {
    const cur = chapters[i].headline;
    const next = chapters[i + 1].headline;
    if (cur.opacity > 0 && next.opacity > 0) {
      const sum = cur.opacity + next.opacity;
      if (sum > 1.0) {
        cur.opacity = cur.opacity / sum;
        next.opacity = next.opacity / sum;
      }
    }
  }

  // 3. Mark visibility
  for (const ch of chapters) {
    const maxOp = Math.max(
      ch.tag.opacity,
      ch.headline.opacity,
      ch.subheadline.opacity,
      ch.description.opacity,
      ch.detail.opacity
    );
    ch.isVisible = maxOp > 0.01;
  }

  return chapters;
}

export function computeTextIntensity(storyProgress: number): number {
  const chapters = computeTimeline(storyProgress);
  let maxIntensity = 0;
  for (const ch of chapters) {
    const intensity = ch.headline.opacity * 0.6 + ch.description.opacity * 0.4;
    if (intensity > maxIntensity) {
      maxIntensity = intensity;
    }
  }
  // Only trigger subtle blur when text is genuinely established (intensity > 0.6)
  // This guarantees that during all 5 breathing windows and transitions, blur is strictly 0
  if (maxIntensity < 0.6) return 0;
  const factor = (maxIntensity - 0.6) / 0.4;
  return factor * factor * (3 - 2 * factor);
}

export function StoryNarrative({ storyProgress, onReplay }: Props) {
  const navigate = useNavigate();
  const enter = () => navigate('/login');

  // Development debug HUD toggle (via Shift+D or ?debugNarrative=true)
  const [debugActive, setDebugActive] = useState(() => {
    if (typeof window === 'undefined') return false;
    return new URLSearchParams(window.location.search).get('debugNarrative') === 'true';
  });

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.shiftKey && (e.key === 'D' || e.key === 'd')) {
        setDebugActive((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Compute decoupled staggered timeline
  const [ch1, ch2, ch3, ch4, ch5, ch6] = computeTimeline(storyProgress);
  const textIntensity = computeTextIntensity(storyProgress);

  // Debug HUD metrics
  const allChapters = [ch1, ch2, ch3, ch4, ch5, ch6];
  const dominantChapter = [...allChapters].sort((a, b) => b.headline.opacity - a.headline.opacity)[0];
  const activeSecond = allChapters.find((c) => c !== dominantChapter && c.headline.opacity > 0.05);

  return (
    <div className={s.stickyStage}>
      {/* Atmospheric Background Focus Scrim (gently softens background canvas during text reading dwell) */}
      <div
        className={s.backdropScrim}
        style={{
          opacity: textIntensity * 0.75,
          backdropFilter: textIntensity > 0 ? `blur(${Math.round(textIntensity * 8)}px)` : 'none',
          WebkitBackdropFilter: textIntensity > 0 ? `blur(${Math.round(textIntensity * 8)}px)` : 'none',
        }}
      />

      {/* ── CHAPTER 01: THE PROBLEM ── */}
      {ch1.isVisible && (
        <div
          className={s.chapterLayer}
          style={{
            pointerEvents: ch1.headline.opacity > 0.4 ? 'auto' : 'none',
          }}
        >
          <div className={s.cardContent}>
            <div
              className={s.tag}
              style={{
                opacity: ch1.tag.opacity,
                transform: `translate3d(0, ${ch1.tag.yOffset}px, 0)`,
                filter: `blur(${ch1.tag.blur}px)`,
              }}
            >
              <span className={s.tagDot} />
              <span>{STORY_CONTENT.problem.annotation || STORY_CONTENT.problem.eyebrow}</span>
            </div>
            <h1
              className={s.headline}
              style={{
                opacity: ch1.headline.opacity,
                transform: `translate3d(0, ${ch1.headline.yOffset}px, 0)`,
                filter: `blur(${ch1.headline.blur}px)`,
              }}
            >
              {STORY_CONTENT.problem.title}
            </h1>
            <p
              className={s.subheadline}
              style={{
                opacity: ch1.subheadline.opacity,
                transform: `translate3d(0, ${ch1.subheadline.yOffset}px, 0)`,
                filter: `blur(${ch1.subheadline.blur}px)`,
              }}
            >
              {STORY_CONTENT.problem.subtitle}
            </p>
            <p
              className={s.description}
              style={{
                opacity: ch1.description.opacity,
                transform: `translate3d(0, ${ch1.description.yOffset}px, 0)`,
                filter: `blur(${ch1.description.blur}px)`,
              }}
            >
              {STORY_CONTENT.problem.description}
            </p>
            {STORY_CONTENT.problem.chips && (
              <div
                className={s.fragmentsGrid}
                style={{
                  marginTop: '16px',
                  opacity: ch1.detail.opacity,
                  transform: `translate3d(0, ${ch1.detail.yOffset}px, 0)`,
                  filter: `blur(${ch1.detail.blur}px)`,
                }}
              >
                {STORY_CONTENT.problem.chips.map((c) => (
                  <div key={c} className={s.fragPill}>
                    <span className={s.fragLabel}>SIGNAL</span>
                    <span className={s.fragVal}>{c}</span>
                  </div>
                ))}
              </div>
            )}
            <div
              className={s.scrollCue}
              style={{
                opacity: Math.max(0, 1 - storyProgress / 0.08),
              }}
            >
              <span>Scroll to enter the intelligence field</span>
              <span className={s.scrollArrow}>↓</span>
            </div>
          </div>
        </div>
      )}

      {/* ── CHAPTER 02: CORRELATION (Left-aligned; clears before Ch 3 enters) ── */}
      {ch2.isVisible && (
        <div
          className={`${s.chapterLayer} ${s.chapterLayerLeft}`}
          style={{
            pointerEvents: ch2.headline.opacity > 0.4 ? 'auto' : 'none',
          }}
        >
          <div className={s.cardContent}>
            <div
              className={s.tag}
              style={{
                opacity: ch2.tag.opacity,
                transform: `translate3d(0, ${ch2.tag.yOffset}px, 0)`,
                filter: `blur(${ch2.tag.blur}px)`,
              }}
            >
              <span className={s.tagDot} />
              <span>{STORY_CONTENT.correlation.annotation || STORY_CONTENT.correlation.eyebrow}</span>
            </div>
            <h2
              className={s.headline}
              style={{
                opacity: ch2.headline.opacity,
                transform: `translate3d(0, ${ch2.headline.yOffset}px, 0)`,
                filter: `blur(${ch2.headline.blur}px)`,
              }}
            >
              {STORY_CONTENT.correlation.title}
            </h2>
            <p
              className={s.subheadline}
              style={{
                opacity: ch2.subheadline.opacity,
                transform: `translate3d(0, ${ch2.subheadline.yOffset}px, 0)`,
                filter: `blur(${ch2.subheadline.blur}px)`,
              }}
            >
              {STORY_CONTENT.correlation.subtitle}
            </p>
            <p
              className={s.description}
              style={{
                opacity: ch2.description.opacity,
                transform: `translate3d(0, ${ch2.description.yOffset}px, 0)`,
                filter: `blur(${ch2.description.blur}px)`,
              }}
            >
              {STORY_CONTENT.correlation.description}
            </p>
          </div>
        </div>
      )}

      {/* ── CHAPTER 03: THE GRAPH (Left-aligned; matches chapters 2, 4, 5) ── */}
      {ch3.isVisible && (
        <div
          className={`${s.chapterLayer} ${s.chapterLayerLeft}`}
          style={{
            pointerEvents: ch3.headline.opacity > 0.4 ? 'auto' : 'none',
          }}
        >
          <div className={s.cardContent}>
            <div
              className={s.tag}
              style={{
                opacity: ch3.tag.opacity,
                transform: `translate3d(0, ${ch3.tag.yOffset}px, 0)`,
                filter: `blur(${ch3.tag.blur}px)`,
              }}
            >
              <span className={s.tagDot} />
              <span>{STORY_CONTENT.graph.annotation || STORY_CONTENT.graph.eyebrow}</span>
            </div>
            <h2
              className={s.headline}
              style={{
                opacity: ch3.headline.opacity,
                transform: `translate3d(0, ${ch3.headline.yOffset}px, 0)`,
                filter: `blur(${ch3.headline.blur}px)`,
              }}
            >
              {STORY_CONTENT.graph.title}
            </h2>
            <p
              className={s.subheadline}
              style={{
                opacity: ch3.subheadline.opacity,
                transform: `translate3d(0, ${ch3.subheadline.yOffset}px, 0)`,
                filter: `blur(${ch3.subheadline.blur}px)`,
              }}
            >
              {STORY_CONTENT.graph.subtitle}
            </p>
            <p
              className={s.description}
              style={{
                opacity: ch3.description.opacity,
                transform: `translate3d(0, ${ch3.description.yOffset}px, 0)`,
                filter: `blur(${ch3.description.blur}px)`,
              }}
            >
              {STORY_CONTENT.graph.description}
            </p>
            {STORY_CONTENT.graph.chips && (
              <div
                className={s.fragmentsGrid}
                style={{
                  marginTop: '16px',
                  justifyContent: 'flex-start',
                  opacity: ch3.detail.opacity,
                  transform: `translate3d(0, ${ch3.detail.yOffset}px, 0)`,
                  filter: `blur(${ch3.detail.blur}px)`,
                }}
              >
                {STORY_CONTENT.graph.chips.map((c) => (
                  <div key={c} className={s.fragPill}>
                    <span className={s.fragLabel}>NETWORK</span>
                    <span className={s.fragVal}>{c}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── CHAPTER 04: EVIDENCE TRAIL (Left-aligned + progressive trail steps) ── */}
      {ch4.isVisible && (
        <div
          className={`${s.chapterLayer} ${s.chapterLayerLeft}`}
          style={{
            pointerEvents: ch4.headline.opacity > 0.4 ? 'auto' : 'none',
          }}
        >
          <div className={s.cardContent}>
            <div
              className={s.tag}
              style={{
                opacity: ch4.tag.opacity,
                transform: `translate3d(0, ${ch4.tag.yOffset}px, 0)`,
                filter: `blur(${ch4.tag.blur}px)`,
              }}
            >
              <span className={s.tagDot} />
              <span>{STORY_CONTENT.evidence.annotation || STORY_CONTENT.evidence.eyebrow}</span>
            </div>
            <h2
              className={s.headline}
              style={{
                opacity: ch4.headline.opacity,
                transform: `translate3d(0, ${ch4.headline.yOffset}px, 0)`,
                filter: `blur(${ch4.headline.blur}px)`,
              }}
            >
              {STORY_CONTENT.evidence.title}
            </h2>
            <p
              className={s.subheadline}
              style={{
                opacity: ch4.subheadline.opacity,
                transform: `translate3d(0, ${ch4.subheadline.yOffset}px, 0)`,
                filter: `blur(${ch4.subheadline.blur}px)`,
              }}
            >
              {STORY_CONTENT.evidence.subtitle}
            </p>
            <p
              className={s.description}
              style={{
                opacity: ch4.description.opacity,
                transform: `translate3d(0, ${ch4.description.yOffset}px, 0)`,
                filter: `blur(${ch4.description.blur}px)`,
              }}
            >
              {STORY_CONTENT.evidence.description}
            </p>
            {STORY_CONTENT.evidence.steps && (
              <div
                className={s.trailWrap}
                style={{
                  justifyContent: 'flex-start',
                  marginTop: '18px',
                  opacity: ch4.detail.opacity,
                  transform: `translate3d(0, ${ch4.detail.yOffset}px, 0)`,
                  filter: `blur(${ch4.detail.blur}px)`,
                }}
              >
                {STORY_CONTENT.evidence.steps.map((st, idx) => {
                  const segProgress = Math.max(0, Math.min(1, (storyProgress - 0.58) / 0.08));
                  const isActive = segProgress >= idx * 0.25 && segProgress < (idx + 1) * 0.25;
                  const isDone = segProgress >= (idx + 1) * 0.25;
                  return (
                    <div key={st.step} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <div className={`${s.trailStep} ${isActive ? s.trailStepActive : isDone ? s.trailStepCompleted : ''}`}>
                        <span className={s.stepNum}>STEP {st.step}</span>
                        <span className={s.stepName}>{st.name}</span>
                        <span className={s.stepDetail}>{st.detail}</span>
                      </div>
                      {idx < 3 && <span className={s.trailSep}>→</span>}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── CHAPTER 05: HIDDEN PATTERNS (Left-aligned + discovery contrast) ── */}
      {ch5.isVisible && (
        <div
          className={`${s.chapterLayer} ${s.chapterLayerLeft}`}
          style={{
            pointerEvents: ch5.headline.opacity > 0.4 ? 'auto' : 'none',
          }}
        >
          <div className={s.cardContent}>
            <div
              className={s.tag}
              style={{
                opacity: ch5.tag.opacity,
                transform: `translate3d(0, ${ch5.tag.yOffset}px, 0)`,
                filter: `blur(${ch5.tag.blur}px)`,
              }}
            >
              <span className={`${s.tagDot} ${s.tagAlertDot}`} />
              <span>{STORY_CONTENT.patterns.annotation || STORY_CONTENT.patterns.eyebrow}</span>
            </div>
            <h2
              className={s.headline}
              style={{
                opacity: ch5.headline.opacity,
                transform: `translate3d(0, ${ch5.headline.yOffset}px, 0)`,
                filter: `blur(${ch5.headline.blur}px)`,
              }}
            >
              {STORY_CONTENT.patterns.title}
            </h2>
            <p
              className={s.subheadline}
              style={{
                opacity: ch5.subheadline.opacity,
                transform: `translate3d(0, ${ch5.subheadline.yOffset}px, 0)`,
                filter: `blur(${ch5.subheadline.blur}px)`,
              }}
            >
              {STORY_CONTENT.patterns.subtitle}
            </p>
            <p
              className={s.description}
              style={{
                opacity: ch5.description.opacity,
                transform: `translate3d(0, ${ch5.description.yOffset}px, 0)`,
                filter: `blur(${ch5.description.blur}px)`,
              }}
            >
              {STORY_CONTENT.patterns.description}
            </p>
            {STORY_CONTENT.patterns.discovery && (
              <div
                className={s.discoveryCard}
                style={{
                  marginTop: '16px',
                  opacity: ch5.detail.opacity,
                  transform: `translate3d(0, ${ch5.detail.yOffset}px, 0)`,
                  filter: `blur(${ch5.detail.blur}px)`,
                }}
              >
                <div className={s.discRow}>
                  <div className={s.discBox}>
                    <span className={s.discTag} style={{ color: '#94a3b8', borderColor: 'rgba(255,255,255,0.1)' }}>
                      {STORY_CONTENT.patterns.discovery.visibleTitle}
                    </span>
                    <span style={{ fontSize: '11px', color: '#cbd5e1', lineHeight: '1.4' }}>
                      {STORY_CONTENT.patterns.discovery.visibleDetail}
                    </span>
                  </div>
                  <div className={s.discBox} style={{ background: 'rgba(251, 113, 133, 0.08)', borderColor: 'rgba(251, 113, 133, 0.3)' }}>
                    <span className={s.discTag} style={{ color: '#fb7185', borderColor: 'rgba(251, 113, 133, 0.3)' }}>
                      {STORY_CONTENT.patterns.discovery.hiddenTitle}
                    </span>
                    <span style={{ fontSize: '11px', color: '#fecdd3', lineHeight: '1.4' }}>
                      {STORY_CONTENT.patterns.discovery.hiddenDetail}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── CHAPTER 06: RESOLUTION (Resolution copy + Enter Workspace permanently active) ── */}
      {ch6.isVisible && (
        <div
          className={s.chapterLayer}
          style={{
            pointerEvents: ch6.headline.opacity > 0.4 ? 'auto' : 'none',
          }}
        >
          <div className={s.cardContent}>
            <div
              className={s.tag}
              style={{
                opacity: ch6.tag.opacity,
                transform: `translate3d(0, ${ch6.tag.yOffset}px, 0)`,
                filter: `blur(${ch6.tag.blur}px)`,
              }}
            >
              <span className={s.tagDot} />
              <span>{STORY_CONTENT.resolution.annotation || STORY_CONTENT.resolution.eyebrow}</span>
            </div>
            <h2
              className={s.headline}
              style={{
                opacity: ch6.headline.opacity,
                transform: `translate3d(0, ${ch6.headline.yOffset}px, 0)`,
                filter: `blur(${ch6.headline.blur}px)`,
              }}
            >
              {STORY_CONTENT.resolution.title}
            </h2>
            <p
              className={s.subheadline}
              style={{
                opacity: ch6.subheadline.opacity,
                transform: `translate3d(0, ${ch6.subheadline.yOffset}px, 0)`,
                filter: `blur(${ch6.subheadline.blur}px)`,
              }}
            >
              {STORY_CONTENT.resolution.subtitle}
            </p>
            <p
              className={s.description}
              style={{
                maxWidth: '580px',
                opacity: ch6.description.opacity,
                transform: `translate3d(0, ${ch6.description.yOffset}px, 0)`,
                filter: `blur(${ch6.description.blur}px)`,
              }}
            >
              {STORY_CONTENT.resolution.description}
            </p>

            {/* Enter Workspace CTA prominently displayed at the end in the middle */}
            <div
              className={s.enterActions}
              style={{
                marginTop: '32px',
                opacity: ch6.detail.opacity,
                transform: `translate3d(0, ${ch6.detail.yOffset}px, 0)`,
                filter: `blur(${ch6.detail.blur}px)`,
              }}
            >
              <button
                className={s.enterBtn}
                onClick={enter}
                style={{
                  padding: '16px 36px',
                  fontSize: '14px',
                  fontWeight: 600,
                  letterSpacing: '0.04em',
                  boxShadow: '0 0 32px rgba(241, 241, 238, 0.4)',
                  cursor: 'pointer',
                  pointerEvents: 'auto',
                }}
              >
                <span>ENTER WORKSPACE</span>
                <Icon name="arrow" size={16} />
              </button>
              <button
                className={s.secondaryCaseBtn}
                onClick={() => {
                  window.scrollTo(0, 0);
                  document.documentElement.scrollTop = 0;
                  document.body.scrollTop = 0;
                  navigate('/investigations/CYB-2026-042/overview');
                }}
                style={{ cursor: 'pointer', pointerEvents: 'auto' }}
              >
                Explore Demonstration Case →
              </button>
              <button
                className={s.replayBtn}
                onClick={onReplay}
                style={{ cursor: 'pointer', pointerEvents: 'auto' }}
              >
                Replay Story ↑
              </button>
            </div>
          </div>

          <footer className={s.colophon}>
            <span>CyberDrishti — From Fragments to Truth</span>
            <span>Law Enforcement & Intelligence Systems · 2026</span>
          </footer>
        </div>
      )}

      {/* ── Developer Timing Debug HUD (Shift+D or ?debugNarrative=true) ── */}
      {debugActive && (
        <aside className={s.debugOverlay} aria-label="Narrative Timing Debug HUD">
          <div className={s.debugRow}>
            <span className={s.debugLabel}>PROGRESS:</span>
            <span className={s.debugVal}>{storyProgress.toFixed(3)}</span>
          </div>
          <div className={s.debugRow}>
            <span className={s.debugLabel}>DOMINANT:</span>
            <span className={s.debugVal}>{dominantChapter?.name}</span>
          </div>
          <div className={s.debugRow}>
            <span className={s.debugLabel}>PRIMARY OP:</span>
            <span className={s.debugVal}>{(dominantChapter?.headline.opacity ?? 0).toFixed(2)}</span>
          </div>
          {activeSecond && (
            <div className={s.debugRow}>
              <span className={s.debugLabel}>HANDOFF:</span>
              <span className={s.debugVal}>
                {activeSecond.name} ({activeSecond.headline.opacity.toFixed(2)})
              </span>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
