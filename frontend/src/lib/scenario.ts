// Demo-mode incident for the real demo building (1415 Louisiana, Houston).
// The plan trace mirrors what the server's agent writes, built from the real
// CoStar/Vexcel/Matterport snapshot; routes come from the ported router.
import { demoBuilding as b } from './buildings'
import type { IncidentRow, PlanStepRow, RouteRow } from './contracts'
import { fixtureIncident } from './fixtures'
import { findRoute, routeSeconds } from './router'

const t0 = Date.parse('2026-11-14T10:00:00Z')
const at = (s: number) => new Date(t0 + s * 1000).toISOString()
const id = fixtureIncident.id
const GOAL = 'phone_door'

const fromMain = findRoute(b.graph, 'st_main', GOAL)
const fromGarage = findRoute(b.graph, 'gar1', GOAL)
const best = routeSeconds(fromGarage) <= routeSeconds(fromMain)
  ? { node: 'gar1', steps: fromGarage, label: 'parking garage lobby' }
  : { node: 'st_main', steps: fromMain, label: 'Louisiana St main entrance' }

const r = b.record
const passenger = r.elevators.find((e) => e.type === 'Passenger')?.count
const covered = r.parking.find((p) => p.type === 'Covered')

export const scenarioIncident: IncidentRow = {
  id,
  created_at: at(0),
  note: `65M chest pain, Suite 1800, ${r.address}`,
  parsed: { address: r.address, suite: '1800', floor: 18, complaint: 'chest pain', access_notes: null },
  building_id: b.id,
  status: 'en_route',
}

let seq = 0
const step = (s: number, kind: PlanStepRow['kind'], title: string, detail: PlanStepRow['detail']): PlanStepRow =>
  ({ id: ++seq, incident_id: id, seq, kind, title, detail, created_at: at(s) })

export const scenarioPlanSteps: PlanStepRow[] = [
  step(1, 'plan', 'Plan: find the building, read all three data layers, route to the suite', {
    steps: [
      'Parse the call note',
      'Pull the CoStar building record',
      'Find entrances from the Vexcel aerial and oblique images',
      'Load the interior graph from the Matterport scan',
      'Route from each entrance and pick the fastest',
    ],
  }),
  step(4, 'subagent', `records subagent: ${r.name} is ${r.stories_above_grade} stories; Suite 1800 is Regus on floor 18`, {
    subagent: 'records',
    building_id: b.id,
    result: {
      floor: 18,
      suite: '1800',
      tenant: 'Regus',
      elevators: [`${passenger} passenger`, '1 freight'],
      parking: covered ? `covered garage, ${covered.spaces?.toLocaleString()} spaces` : null,
    },
  }),
  step(6, 'subagent', 'aerial subagent: 2 entrances from the Vexcel ortho and 4 obliques', {
    subagent: 'aerial',
    collection: b.collection,
    entrances: b.markers.map((m) => m.label),
  }),
  step(8, 'subagent', 'interior subagent: Regus Suite 1800 matched to Matterport scan LJn59uoV759', {
    subagent: 'interior',
    models: b.matterport.length,
    destination_model: 'LJn59uoV759',
  }),
  step(9, 'tool_call', `route(${b.id}, st_main, ${GOAL})`, { tool: 'route', args: { start_node: 'st_main', goal_node: GOAL } }),
  step(9, 'tool_call', `route(${b.id}, gar1, ${GOAL})`, { tool: 'route', args: { start_node: 'gar1', goal_node: GOAL } }),
  step(10, 'tool_result', `Main entrance ${routeSeconds(fromMain)} s, garage lobby ${routeSeconds(fromGarage)} s`, {
    tool: 'route',
    st_main: routeSeconds(fromMain),
    gar1: routeSeconds(fromGarage),
  }),
  step(11, 'final', `Final: enter at the ${best.label}, elevators to floor 18, through Regus reception to the phone room`, {
    route_version: 1,
    total_seconds: routeSeconds(best.steps),
  }),
]

export const scenarioRoute: RouteRow = {
  id: 1,
  incident_id: id,
  version: 1,
  entrance_node: best.node,
  steps: best.steps,
  total_seconds: routeSeconds(best.steps),
  briefing: null,
  created_at: at(11),
}
