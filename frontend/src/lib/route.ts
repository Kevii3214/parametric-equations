import type { BuildingGraph, Cue, GraphNode, PositionRow, RouteStep } from './contracts'

export function nodeMap(graph: BuildingGraph): Map<string, GraphNode> {
  return new Map(graph.nodes.map((n) => [n.id, n]))
}

export const isFloorChange = (cue: Cue) => cue === 'FLOOR_UP' || cue === 'FLOOR_DOWN'

export interface Point {
  x: number
  y: number
  floor: number
}

/**
 * Where the paramedic is, from a positions row. Assumes progress_m is metres
 * walked into step step_index (open question with Person 2).
 */
export function positionPoint(
  pos: Pick<PositionRow, 'step_index' | 'progress_m' | 'floor'>,
  steps: RouteStep[],
  nodes: Map<string, GraphNode>,
): Point | null {
  const step = steps[pos.step_index]
  if (!step) return null
  const a = nodes.get(step.from_node)
  const b = nodes.get(step.to_node)
  if (!a || !b) return null
  if (a.floor !== b.floor) {
    // In the elevator or stairwell: pin the dot to whichever end matches.
    const at = pos.floor === b.floor ? b : a
    return { x: at.x, y: at.y, floor: at.floor }
  }
  const f = step.meters > 0 ? Math.min(1, Math.max(0, pos.progress_m / step.meters)) : 1
  return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, floor: a.floor }
}

export function formatSeconds(s: number): string {
  const m = Math.floor(s / 60)
  const r = Math.round(s % 60)
  return m ? `${m} min ${r.toString().padStart(2, '0')} s` : `${r} s`
}

export const cueLabel: Record<Cue, string> = {
  LEFT: 'Turn left',
  RIGHT: 'Turn right',
  STRAIGHT: 'Go straight',
  UTURN: 'Turn around',
  FLOOR_UP: 'Go up',
  FLOOR_DOWN: 'Go down',
  ARRIVE: 'Arrive',
  OFF_ROUTE: 'Off route',
}

/**
 * Graph labels and step text can carry provenance notes in brackets
 * ("Stairs (lower level; placed from the scan's opening view)"). Drop them
 * for display; the data keeps them.
 */
export const tidy = (text: string) => text.replace(/\s*\([^)]*\)/g, '').replace(/\s+([.,])/g, '$1').trim()
