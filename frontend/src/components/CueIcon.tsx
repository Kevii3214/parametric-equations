import type { Cue } from '../lib/contracts'

// Arrow glyphs drawn on a 24x24 grid, stroke only, so they scale cleanly.
const paths: Record<Cue, string> = {
  STRAIGHT: 'M12 20V4M6 10l6-6 6 6',
  LEFT: 'M18 20v-8a4 4 0 0 0-4-4H5M9 4L5 8l4 4',
  RIGHT: 'M6 20v-8a4 4 0 0 1 4-4h9M15 4l4 4-4 4',
  UTURN: 'M8 20V9a4 4 0 0 1 8 0v4M12 10l4 4 4-4',
  FLOOR_UP: 'M4 20h5v-5h5v-5h5M14 5h5v5',
  FLOOR_DOWN: 'M4 5h5v5h5v5h5M19 14v5h-5',
  ARRIVE: 'M12 21s-6-5.6-6-11a6 6 0 0 1 12 0c0 5.4-6 11-6 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  OFF_ROUTE: 'M12 3l10 18H2L12 3zM12 10v5M12 18h.01',
}

export default function CueIcon({ cue, className = 'h-6 w-6' }: { cue: Cue; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      <path d={paths[cue]} />
    </svg>
  )
}
