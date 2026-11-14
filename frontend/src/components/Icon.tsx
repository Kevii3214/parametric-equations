// Small stroke icons on a 24x24 grid, drawn with currentColor (no emoji or
// text glyphs, so they look the same on every platform).
const PATHS = {
  play: 'M8 5.5v13l10.5-6.5z',
  pause: 'M8 5v14M16 5v14',
  restart: 'M4 12a8 8 0 1 0 2.4-5.7M4 4v4.5h4.5',
  prev: 'M15 5l-7 7 7 7',
  next: 'M9 5l7 7-7 7',
  close: 'M6 6l12 12M18 6L6 18',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 7.5h.01',
  star: 'M12 3.5l2.6 5.3 5.9.9-4.25 4.1 1 5.8L12 16.9l-5.25 2.7 1-5.8L3.5 9.7l5.9-.9z',
  route: 'M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a3 3 0 0 1 3-3h7M18 9v6a3 3 0 0 1-3 3H8',
} as const

export type IconName = keyof typeof PATHS
const FILLED: IconName[] = ['play', 'star']

export default function Icon({ name, className = 'h-4 w-4' }: { name: IconName; className?: string }) {
  const filled = FILLED.includes(name)
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true"
      fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={filled ? 0 : 2.2}
      strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name]} />
    </svg>
  )
}
