// Which route step the medic is on. Inside the building there may be no
// live position, so the medic moves on with Next / Back; a live position (or
// the demo replay) moves it forward when it reports a later step. A new
// route (a re-plan) starts again at step 0.
import { useState } from 'react'

export interface Cursor {
  /** Identifies the route; a change resets the cursor. */
  key: string
  index: number
  /** The last step index reported by live positions, so Back is not undone. */
  lastLive: number
}

export type CursorInput =
  | { type: 'route'; key: string }
  | { type: 'live'; step: number }
  | { type: 'next' }
  | { type: 'back' }

export function moveCursor(c: Cursor, input: CursorInput, total: number): Cursor {
  const clamp = (i: number) => Math.max(0, Math.min(Math.max(0, total - 1), i))
  switch (input.type) {
    case 'route': return c.key === input.key ? c : { key: input.key, index: 0, lastLive: -1 }
    // Follow a live position only when it moves past what it last reported.
    case 'live': return input.step > c.lastLive ? { ...c, index: clamp(Math.max(c.index, input.step)), lastLive: input.step } : c
    case 'next': return { ...c, index: clamp(c.index + 1) }
    case 'back': return { ...c, index: clamp(c.index - 1) }
  }
}

/** The current step, with Next/Back, following live positions and resetting on a new route. */
export function useStepCursor(routeKey: string, total: number, liveStep: number | null) {
  const [stored, setStored] = useState<Cursor>({ key: routeKey, index: 0, lastLive: -1 })
  // Adjust during render (React's recommended pattern for state derived from props).
  let c = moveCursor(stored, { type: 'route', key: routeKey }, total)
  if (liveStep !== null) c = moveCursor(c, { type: 'live', step: liveStep }, total)
  if (c !== stored) setStored(c)
  return {
    index: c.index,
    next: () => setStored((s) => moveCursor(moveCursor(s, { type: 'route', key: routeKey }, total), { type: 'next' }, total)),
    back: () => setStored((s) => moveCursor(moveCursor(s, { type: 'route', key: routeKey }, total), { type: 'back' }, total)),
  }
}
