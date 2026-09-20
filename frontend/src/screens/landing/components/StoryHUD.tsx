import { STORY_CHAPTERS } from '../storyConfig';
import { getActiveChapter } from '../storyUtils';
import s from '../landing.module.css';

interface Props {
  storyProgress: number;
  onJumpTo: (targetProgress: number) => void;
}

export function StoryHUD({ storyProgress, onJumpTo }: Props) {
  const activeChapter = getActiveChapter(storyProgress);

  return (
    <aside className={s.hud} aria-label="Story Chapters">
      {STORY_CHAPTERS.map((ch) => {
        const isActive = activeChapter.id === ch.id;
        return (
          <button
            key={ch.id}
            className={`${s.hudItem} ${isActive ? s.hudActive : ''}`}
            onClick={() => onJumpTo((ch.start + ch.end) / 2)}
          >
            <span className={s.hudDot} />
            <span className={s.hudLabel}>
              {ch.label}
            </span>
          </button>
        );
      })}
    </aside>
  );
}
