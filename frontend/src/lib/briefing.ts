// What the crew should know before they go in: derived from the route, the
// building record and the agent's trace. Pure, so it can be tested.
import type { Building } from './buildings'
import type { PlanStepRow, RouteStep } from './contracts'
import { closures } from './incident'
import { formatSeconds, isFloorChange, tidy } from './route'

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

export interface HeadsUp {
  tone: 'warn' | 'info' | 'ok'
  text: string
}

/** Warnings and reassurances for the briefing, most important first. */
export function headsUp(building: Building | null, steps: RouteStep[], planSteps: PlanStepRow[]): HeadsUp[] {
  const out: HeadsUp[] = []
  const g = routeGlance(steps)
  for (const c of closures(planSteps)) out.push({ tone: 'warn', text: `Re-planned around a closure (${c}).` })
  if (g.climb === 'stairs') out.push({ tone: 'warn', text: 'Stairs on this route: bring the stair chair.' })
  if (building) {
    const lifts = building.graph.nodes.some((n) => n.kind === 'elevator')
    if (!lifts) out.push({ tone: 'warn', text: 'No elevator in the building data.' })
    if (!building.imageryMatches && building.imageryNote) out.push({ tone: 'warn', text: building.imageryNote })
    if (building.markers.some((m) => m.estimated)) out.push({ tone: 'info', text: 'Entrance positions are estimated from imagery, not measured.' })
    for (const n of building.record.data_quality_notes) out.push({ tone: 'info', text: n })
  }
  if (steps.length) out.push({ tone: 'ok', text: 'Route uses stretcher-safe paths only.' })
  return out
}

/** A short spoken briefing when the server did not send one. */
export function spokenSummary(steps: RouteStep[], entrance: string | null, goal: string | null): string {
  if (!steps.length) return ''
  const g = routeGlance(steps)
  const parts = [
    entrance ? `Enter at the ${tidy(entrance)}.` : '',
    g.climb ? `Take the ${g.climb} to floor ${g.floors.at(-1)}.` : '',
    goal ? `The patient is in the ${tidy(goal).replace(/^the /i, '')}.` : '',
    `About ${formatSeconds(g.seconds)} door to patient, ${steps.length} steps.`,
  ]
  return parts.filter(Boolean).join(' ')
}
