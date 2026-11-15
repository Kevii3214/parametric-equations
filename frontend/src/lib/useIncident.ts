// Everything both tabs need about the current incident, worked out once.
import { buildingById, buildingForNote, buildingForRoute, patientFloor } from './buildings'
import { useDemoBuilding, useDemoReason, useIncidentParam } from './demo'
import { graphFor } from './incident'
import { readTour } from './tour'
import { useIncidentLive } from './useIncidentLive'

export function useIncident() {
  const reason = useDemoReason()
  const demo = reason !== null
  const [incidentId, setIncident] = useIncidentParam()
  const live = useIncidentLive(incidentId, demo, useDemoBuilding())
  const route = live.route
  const steps = route?.steps ?? []
  const site = buildingById(live.incident?.building_id) ?? buildingForRoute(steps.flatMap((s) => [s.from_node, s.to_node]))
  const started = live.source === 'fixtures' || incidentId !== null
  // The agent finished (a final step) but saved no route: it gave up.
  const finalStep = live.planSteps.findLast((s) => s.kind === 'final') ?? null
  const gaveUp = live.source === 'supabase' && !!finalStep && !route
  const working = started && !route && !finalStep
  return {
    reason,
    demo,
    incidentId,
    setIncident,
    live,
    route,
    steps,
    graph: graphFor(steps),
    site,
    tour: readTour(route?.tour),
    entrance: site?.markers.find((m) => m.node === route?.entrance_node) ?? null,
    patientFloor: site ? patientFloor(site, live.incident?.parsed ?? null) : null,
    started,
    working,
    gaveUp,
    finalStep,
    /** The demo building the call note names, for the "show the demo route" fallback. */
    demoFor: buildingForNote(live.incident?.note ?? ''),
  }
}
