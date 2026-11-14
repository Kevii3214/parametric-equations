// Small readers over the shared rows. Person 1 never reads Person 2's private
// tables (buildings, graphs), so building facts come from the plan trace.
import type { BuildingGraph, PlanStepRow, RouteStep } from './contracts'
import { fixtureGraph } from './fixtures'

type Json = Record<string, unknown>

const isObj = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Result of the records subagent (CoStar building data), if it has reported. */
export function recordsResult(steps: PlanStepRow[]): Json | null {
  const s = steps.find((s) => s.kind === 'subagent' && s.detail?.subagent === 'records')
  const r = s?.detail?.result
  return isObj(r) ? r : null
}

/** Edges closed by replans, as "from->to". */
export function closures(steps: PlanStepRow[]): string[] {
  return steps
    .filter((s) => s.kind === 'replan' && typeof s.detail?.closure === 'string')
    .map((s) => s.detail!.closure as string)
}

/** The parsed call note, with only the string/number fields kept. */
export function parsedNote(parsed: Json | null): Record<string, string | number> {
  const out: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(parsed ?? {})) {
    if (typeof v === 'string' || typeof v === 'number') out[k] = v
  }
  return out
}

/**
 * The interior graph for a route. The graphs table is private to the server
 * and the API has no graph endpoint yet (open question with Person 2), so for
 * now this is the fixture graph, used only when it contains the route's nodes.
 */
export function graphFor(steps: RouteStep[] | undefined): BuildingGraph | null {
  if (!steps?.length) return null
  const ids = new Set(fixtureGraph.nodes.map((n) => n.id))
  return steps.every((s) => ids.has(s.from_node) && ids.has(s.to_node)) ? fixtureGraph : null
}
