// Demo-mode incidents for the real demo buildings. The plan trace mirrors what
// the server's agent writes, built from the CoStar/Vexcel/Matterport snapshot;
// routes come from the ported router, comparing every entrance.
import { buildingById, demoBuilding, type Building } from './buildings'
import type { IncidentRow, PlanStepRow, RouteRow } from './contracts'
import { fixtureIncident } from './fixtures'
import { findRoute, routeSeconds } from './router'

export interface Scenario {
  incident: IncidentRow
  planSteps: PlanStepRow[]
  route: RouteRow
}

const t0 = Date.parse('2026-11-14T10:00:00Z')
const at = (s: number) => new Date(t0 + s * 1000).toISOString()
const id = fixtureIncident.id

/** The call each demo building is played with. */
const CALLS: Record<string, { complaint: string; age: string }> = {
  '233928': { complaint: 'chest pain', age: '65M' },
  '233903': { complaint: 'fall, head injury', age: '58F' },
}

function build(b: Building): Scenario {
  const goal = b.demoGoal ?? b.graph.nodes.at(-1)!.id
  const goalNode = b.graph.nodes.find((n) => n.id === goal)!
  const suiteTenant = b.record.current_tenants.find((t) => t.floor_guess_from_suite === goalNode.floor && t.company)
    ?? b.record.current_tenants.find((t) => t.floor_guess_from_suite === goalNode.floor)
  const suite = suiteTenant?.suite ?? String(goalNode.floor * 100)
  const call = CALLS[b.id] ?? { complaint: 'unresponsive', age: '60M' }

  const tries = b.markers.map((m) => ({ m, steps: findRoute(b.graph, m.node, goal) }))
  const best = tries.reduce((x, y) => (routeSeconds(y.steps) < routeSeconds(x.steps) ? y : x))
  const r = b.record
  const passenger = r.elevators.find((e) => e.type === 'Passenger')?.count
  const covered = r.parking.find((p) => p.type === 'Covered')

  const incident: IncidentRow = {
    id,
    created_at: at(0),
    note: `${call.age} ${call.complaint}, Suite ${suite}, ${r.address}`,
    parsed: { address: r.address, suite, floor: goalNode.floor, complaint: call.complaint, access_notes: null },
    building_id: b.id,
    status: 'en_route',
  }

  let seq = 0
  const step = (s: number, kind: PlanStepRow['kind'], title: string, detail: PlanStepRow['detail']): PlanStepRow =>
    ({ id: ++seq, incident_id: id, seq, kind, title, detail, created_at: at(s) })

  const destModel = b.matterport.find((m) => m.destination)
  const planSteps: PlanStepRow[] = [
    step(1, 'plan', 'Plan: find the building, read all three data layers, route to the suite', {
      steps: [
        'Parse the call note',
        'Pull the CoStar building record',
        'Find entrances from the Vexcel aerial and oblique images',
        'Load the interior graph from the Matterport scan',
        'Route from each entrance and pick the fastest',
      ],
    }),
    step(4, 'subagent', `records subagent: ${r.name} is ${r.stories_above_grade} stories; Suite ${suite} is ${suiteTenant?.company ?? 'listed'} on floor ${goalNode.floor}`, {
      subagent: 'records',
      building_id: b.id,
      result: {
        floor: goalNode.floor,
        suite,
        tenant: suiteTenant?.company ?? null,
        elevators: passenger ? [`${passenger} passenger`] : [],
        parking: covered?.spaces ? `covered garage, ${covered.spaces.toLocaleString()} spaces` : covered ? 'covered garage' : null,
      },
    }),
    b.imageryMatches
      ? step(6, 'subagent', `aerial subagent: ${b.markers.length} entrances from the Vexcel ortho and 4 obliques`, {
        subagent: 'aerial', collection: b.collection, entrances: b.markers.map((m) => m.label) })
      : step(6, 'subagent', 'aerial subagent: the Vexcel parcel is a neighbouring building, so entrances are estimated from the map footprint', {
        subagent: 'aerial', collection: b.collection, entrances: b.markers.map((m) => m.label), warning: 'parcel mismatch' }),
    step(8, 'subagent', `interior subagent: Suite ${suite} matched to Matterport scan ${destModel?.id ?? 'n/a'}`, {
      subagent: 'interior', models: b.matterport.length, destination_model: destModel?.id ?? null }),
    ...tries.map((t) => step(9, 'tool_call', `route(${b.id}, ${t.m.node}, ${goal})`, { tool: 'route', args: { start_node: t.m.node, goal_node: goal } })),
    step(10, 'tool_result', tries.map((t) => `${t.m.label} ${routeSeconds(t.steps)} s`).join(', '), {
      tool: 'route', ...Object.fromEntries(tries.map((t) => [t.m.node, routeSeconds(t.steps)])) }),
    step(11, 'final', `Final: enter at the ${best.m.label.toLowerCase()}, elevators to floor ${goalNode.floor}, then to ${goalNode.label ?? 'the patient'}`, {
      route_version: 1, total_seconds: routeSeconds(best.steps) }),
  ]

  const route: RouteRow = {
    id: 1,
    incident_id: id,
    version: 1,
    entrance_node: best.m.node,
    steps: best.steps,
    total_seconds: routeSeconds(best.steps),
    briefing: null,
    created_at: at(11),
  }
  return { incident, planSteps, route }
}

const cache = new Map<string, Scenario>()

/** The demo scenario for a building (default: the first demo building). */
export function scenarioFor(buildingId?: string | null): Scenario {
  const b = buildingById(buildingId) ?? demoBuilding
  if (!cache.has(b.id)) cache.set(b.id, build(b))
  return cache.get(b.id)!
}
