import type { ReactNode } from "react";

export type IconName =
  | "logo" | "command" | "cases" | "intel" | "settings"
  | "search" | "arrow" | "plus" | "close" | "download" | "filter"
  | "sun" | "moon";

const PATHS: Record<IconName, ReactNode> = {
  logo: (
    <>
      <circle cx="10" cy="4" r="2" fill="currentColor" stroke="none" />
      <line x1="10" y1="8" x2="10" y2="12" />
      <circle cx="10" cy="16" r="2" fill="currentColor" stroke="none" />
    </>
  ),
  command: (
    <>
      <circle cx="10" cy="10" r="6" />
      <circle cx="10" cy="10" r="1.2" fill="currentColor" stroke="none" />
    </>
  ),
  cases: <path d="M10 3.5 16.5 10 10 16.5 3.5 10Z" />,
  intel: (
    <path d="M10 3C10.7 7.2 12.8 9.3 17 10 12.8 10.7 10.7 12.8 10 17 9.3 12.8 7.2 10.7 3 10 7.2 9.3 9.3 7.2 10 3Z" />
  ),
  settings: (
    <>
      <line x1="3" y1="6.5" x2="17" y2="6.5" />
      <circle cx="12.5" cy="6.5" r="2" fill="currentColor" stroke="none" />
      <line x1="3" y1="13.5" x2="17" y2="13.5" />
      <circle cx="7.5" cy="13.5" r="2" fill="currentColor" stroke="none" />
    </>
  ),
  search: (
    <>
      <circle cx="9" cy="9" r="5.5" />
      <line x1="13.2" y1="13.2" x2="17" y2="17" />
    </>
  ),
  arrow: (
    <>
      <path d="M4 10h11" />
      <path d="M11 6l4 4-4 4" />
    </>
  ),
  plus: <path d="M10 5v10M5 10h10" />,
  close: (
    <>
      <line x1="5" y1="5" x2="15" y2="15" />
      <line x1="15" y1="5" x2="5" y2="15" />
    </>
  ),
  download: (
    <>
      <path d="M10 3v9M6 8l4 4 4-4" />
      <path d="M4 15h12" />
    </>
  ),
  filter: (
    <>
      <path d="M3 5h14M6 10h8M8 15h4" />
    </>
  ),
  sun: (
    <>
      <circle cx="10" cy="10" r="3.5" />
      <line x1="10" y1="2" x2="10" y2="4" />
      <line x1="10" y1="16" x2="10" y2="18" />
      <line x1="2" y1="10" x2="4" y2="10" />
      <line x1="16" y1="10" x2="18" y2="10" />
      <line x1="4.3" y1="4.3" x2="5.7" y2="5.7" />
      <line x1="14.3" y1="14.3" x2="15.7" y2="15.7" />
      <line x1="4.3" y1="15.7" x2="5.7" y2="14.3" />
      <line x1="14.3" y1="5.7" x2="15.7" y2="4.3" />
    </>
  ),
  moon: (
    <path d="M15.5 11.5A6.5 6.5 0 0 1 8.5 4.5 6.5 6.5 0 1 0 15.5 11.5Z" />
  ),
};

export function Icon({ name, size = 20, className, style }: { name: IconName; size?: number; className?: string; style?: React.CSSProperties }) {
  return (
    <svg
      viewBox="0 0 20 20" width={size} height={size}
      fill="none" stroke="currentColor" strokeWidth={1.5}
      strokeLinecap="round" strokeLinejoin="round"
      className={className} style={style} aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}
