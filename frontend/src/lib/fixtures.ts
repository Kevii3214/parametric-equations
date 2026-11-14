// Sample data from ../fixtures (same shapes the real server produces), for
// building the UI before the server exists. Read-only: never edit fixtures/.
import graphJson from '../../../fixtures/building_graph.json'
import incidentJson from '../../../fixtures/incident.json'
import planStepsJson from '../../../fixtures/plan_steps.json'
import routeJson from '../../../fixtures/route.json'
import type {
  BuildingGraph,
  IncidentRow,
  PlanStepRow,
  RouteRow,
  RouteStep,
} from './contracts'

export const fixtureGraph = graphJson as BuildingGraph
export const fixtureIncident = incidentJson as IncidentRow

// The fixture rows have no bigserial id, so number them by seq.
export const fixturePlanSteps: PlanStepRow[] = (
  planStepsJson as Omit<PlanStepRow, 'id'>[]
).map((s) => ({ ...s, id: s.seq }))

// fixtures/route.json is only the routes.steps value; wrap it as a routes row.
const steps = routeJson as RouteStep[]
export const fixtureRoute: RouteRow = {
  id: 1,
  incident_id: fixtureIncident.id,
  version: 1,
  entrance_node: steps[0]?.from_node ?? '',
  steps,
  total_seconds: steps.reduce((sum, s) => sum + s.seconds, 0),
  briefing: null,
  created_at: fixtureIncident.created_at,
}
