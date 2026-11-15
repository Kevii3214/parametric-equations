// The route at a glance for the briefing. Pure, so it can be tested.
import type { RouteStep } from './contracts'
import { isFloorChange } from './route'

export interface Glance {
  seconds: number
  meters: number
  floors: number[]
  /** 'elevator', 'stairs', or null when the route stays on one floor. */
  climb: 'elevator' | 'stairs' | null
  turns: number
}

export function routeGlance(steps: RouteStep[]): Glance {
  const floorChange = steps.find((s) => isFloorChange(s.cue))
  return {
    seconds: steps.reduce((t, s) => t + s.seconds, 0),
    meters: Math.round(steps.reduce((m, s) => m + s.meters, 0)),
    floors: [...new Set(steps.map((s) => s.floor))],
    climb: floorChange ? (/stairs/i.test(floorChange.text) ? 'stairs' : 'elevator') : null,
    turns: steps.filter((s) => s.cue === 'LEFT' || s.cue === 'RIGHT' || s.cue === 'UTURN').length,
  }
}
