// TypeScript port of backend/app/graph/router.py, used only in demo mode so
// the app can show real routes (and elevator-out replans) with no server.
// Same costs, closure rules, cues and step text as the server's router.
import type { BuildingGraph, Cue, GraphEdge, GraphNode, RouteStep } from './contracts'

const STAIRS_PENALTY_S = 1000
const TURN_DEGREES = 45
const UTURN_DEGREES = 135

export function turnCue(before: number, after: number): Cue {
  const delta = ((after - before + 540) % 360) - 180
  if (Math.abs(delta) >= UTURN_DEGREES) return 'UTURN'
  if (delta >= TURN_DEGREES) return 'RIGHT'
  if (delta <= -TURN_DEGREES) return 'LEFT'
  return 'STRAIGHT'
}

/** Fastest stretcher-safe route; closures are node ids or "a->b" (both directions). */
export function findRoute(graph: BuildingGraph, start: string, goal: string, closures: string[] = []): RouteStep[] {
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]))
  if (!nodes.has(start) || !nodes.has(goal)) throw new Error(`Unknown node in ${graph.building_id}`)
  if (start === goal) return []

  const closedNodes = new Set<string>()
  const closedEdges = new Set<string>()
  for (const c of closures) {
    if (c.includes('->')) {
      const [a, b] = c.split('->').map((s) => s.trim())
      closedEdges.add(`${a}->${b}`).add(`${b}->${a}`)
    } else closedNodes.add(c)
  }
  const out = new Map<string, GraphEdge[]>()
  for (const e of graph.edges) {
    if (!e.stretcher_ok || closedNodes.has(e.from) || closedNodes.has(e.to) || closedEdges.has(`${e.from}->${e.to}`)) continue
    out.set(e.from, [...(out.get(e.from) ?? []), e])
  }
  const cost = (e: GraphEdge) => e.seconds + (e.kind === 'stairs' ? STAIRS_PENALTY_S : 0)

  // Dijkstra: the graphs are tiny, so a linear scan is fine.
  const dist = new Map<string, number>([[start, 0]])
  const prev = new Map<string, GraphEdge>()
  const done = new Set<string>()
  while (true) {
    let cur: string | null = null
    for (const [id, d] of dist) if (!done.has(id) && (cur === null || d < dist.get(cur)!)) cur = id
    if (cur === null) throw new Error(`No stretcher-safe route from ${start} to ${goal}`)
    if (cur === goal) break
    done.add(cur)
    for (const e of out.get(cur) ?? []) {
      const d = dist.get(cur)! + cost(e)
      if (d < (dist.get(e.to) ?? Infinity)) {
        dist.set(e.to, d)
        prev.set(e.to, e)
      }
    }
  }
  const path: GraphEdge[] = []
  for (let at = goal; at !== start; at = prev.get(at)!.from) path.unshift(prev.get(at)!)
  return toSteps(path, nodes)
}

function bearing(a: GraphNode, b: GraphNode): number | null {
  const dx = b.x - a.x
  const dy = b.y - a.y
  if (a.floor !== b.floor || Math.hypot(dx, dy) === 0) return null
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360
}

function toSteps(path: GraphEdge[], nodes: Map<string, GraphNode>): RouteStep[] {
  return path.map((e, index) => {
    const a = nodes.get(e.from)!
    const b = nodes.get(e.to)!
    let cue: Cue
    if (index === path.length - 1) cue = 'ARRIVE'
    else if (a.floor !== b.floor) cue = b.floor > a.floor ? 'FLOOR_UP' : 'FLOOR_DOWN'
    else {
      const next = path[index + 1]
      const here = bearing(a, b)
      const ahead = bearing(nodes.get(next.from)!, nodes.get(next.to)!)
      cue = here === null || ahead === null ? 'STRAIGHT' : turnCue(here, ahead)
    }
    return { index, from_node: e.from, to_node: e.to, cue, meters: e.meters, seconds: e.seconds, floor: b.floor, text: text(cue, e, b, a.floor) }
  })
}

function text(cue: Cue, e: GraphEdge, to: GraphNode, floorA: number): string {
  if (floorA !== to.floor) {
    const how = e.kind === 'stairs' ? 'Climb the stairs' : 'Take the elevator'
    return `${how} ${to.floor > floorA ? 'up' : 'down'} to floor ${to.floor}.`
  }
  const walk = `Walk ${e.meters} m`
  switch (cue) {
    case 'ARRIVE': return `${walk}. ${to.label ?? 'Your destination'} is ahead.`
    case 'LEFT': return `${walk}, then turn left.`
    case 'RIGHT': return `${walk}, then turn right.`
    case 'UTURN': return `${walk}, then turn around.`
    default: return to.label ? `${walk} to ${to.label}.` : `${walk}.`
  }
}

export const routeSeconds = (steps: RouteStep[]) => steps.reduce((t, s) => t + s.seconds, 0)
