// Demo-mode re-plan for "Elevator out" and "Blocked", using the ported router
// (live incidents send an event and the server re-plans instead).
import type { BuildingGraph, RouteStep } from './contracts'
import { isFloorChange } from './route'
import { findRoute } from './router'

export type Problem = 'elevator_out' | 'blocked'

/**
 * A new route from the current step's start to the same goal, avoiding the
 * problem: the next floor change for "elevator out", the current corridor
 * for "blocked". Null when nothing needs closing or no route remains.
 */
export function replanAround(graph: BuildingGraph, steps: RouteStep[], current: number, problem: Problem):
  { steps: RouteStep[]; closure: string } | null {
  const here = steps[current]
  const goal = steps.at(-1)?.to_node
  if (!here || !goal) return null
  const target = problem === 'elevator_out'
    ? steps.slice(current).find((s) => isFloorChange(s.cue) && !/stairs/i.test(s.text))
    : here
  if (!target) return null
  const closure = `${target.from_node}->${target.to_node}`
  try {
    const next = findRoute(graph, here.from_node, goal, [closure])
    return next.length ? { steps: next, closure } : null
  } catch {
    return null
  }
}
