import { lazy, Suspense, type ReactNode } from 'react'
import CallIntake from '../components/call/CallIntake'
import CueIcon from '../components/CueIcon'
import PlanTrace from '../components/PlanTrace'
import SiteImagery from '../components/site/SiteImagery'
import { routeGlance } from '../lib/briefing'
import { buildingById } from '../lib/buildings'
import { fixtureIncident } from '../lib/fixtures'
import { parsedNote } from '../lib/incident'
import { formatSeconds, tidy } from '../lib/route'
import { useIncident } from '../lib/useIncident'

// The fly-through (Matterport SDK) and the 3D map are large: load on demand.
const TourPlayer = lazy(() => import('../components/tour/TourPlayer'))

/** In the ambulance: who, where to stop, the route in advance, and what to watch for. */
export default function PreArrival() {
  const inc = useIncident()
  const { live, route, steps, site, tour } = inc
  const note = parsedNote(live.incident?.parsed ?? null)
  const glance = routeGlance(steps)

  return (
    <div className="mx-auto max-w-6xl pb-10 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] lg:items-start lg:gap-8">
      <div className="min-w-0">
      <CallIntake reason={inc.reason} onCreated={inc.setIncident} />

      {!live.incident && !inc.started && (
        <p className="mt-10 text-center text-sm text-ink-3">No active call. Pick a sample call above, or wait for dispatch.</p>
      )}

      {inc.gaveUp && inc.finalStep && (
        <div role="alert" className="mt-5 rounded-2xl border border-amber/30 bg-amber-soft px-4 py-3">
          <p className="text-sm font-semibold text-ink">The agent finished without a route</p>
          <p className="mt-1 text-sm text-ink-2">{inc.finalStep.title.replace(/^Final:\s*/, '')}</p>
          {inc.demoFor && (
            <button type="button" onClick={() => inc.setIncident(fixtureIncident.id, inc.demoFor)}
              className="mt-2.5 rounded-full bg-azure px-4 py-1.5 text-sm font-semibold text-white hover:bg-azure-deep">
              Show the demo route for {buildingById(inc.demoFor)?.record.name ?? 'this building'}
            </button>
          )}
        </div>
      )}

      {live.incident && (
        <header className="mt-6">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">Patient</p>
          <h1 className="mt-1 text-2xl font-semibold leading-tight tracking-tight text-ink">
            {capitalise(String(note.complaint ?? live.incident.note ?? 'Call'))}
            {inc.patientFloor != null && <span className="text-ink-2"> · floor {inc.patientFloor}</span>}
          </h1>
          <p className="mt-1 text-[15px] text-ink-2">
            {[note.suite ? `Suite ${note.suite}` : note.location, site?.record.name ?? note.address].filter(Boolean).join(' · ')}
          </p>
          {route && (
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-2">
              <span className="font-semibold text-fern-deep">{formatSeconds(route.total_seconds)} door to patient</span>
              <span>{steps.length} steps</span>
              {glance.climb && <span>{glance.climb} to floor {glance.floors.at(-1)}</span>}
            </p>
          )}
        </header>
      )}

      {route && site && (
        <Section title="Where to stop">
          {/* Opens on the 3D view: the tower, the patient's floor, the entrance pins and the route. */}
          <SiteImagery building={site} entranceNode={route.entrance_node} patientFloor={inc.patientFloor} steps={steps} />
        </Section>
      )}

      {route && (
        <Section title="Route preview" aside={<span className="text-xs text-ink-3">{glance.turns} turns · {glance.meters} m</span>}>
          {tour && site ? (
            <div className="aspect-[16/10] w-full overflow-hidden rounded-2xl">
              <Suspense fallback={<div className="grid h-full place-items-center bg-sunk text-sm text-ink-3">Loading fly-through…</div>}>
                <TourPlayer key={`${route.id}-${route.version}`} tour={tour} building={site} steps={steps} patientFloor={inc.patientFloor} />
              </Suspense>
            </div>
          ) : null}
          <ol className="mt-3 divide-y divide-line">
            {steps.map((s) => (
              <li key={s.index} className="flex items-center gap-3 py-2 text-sm text-ink">
                <CueIcon cue={s.cue} className="h-4 w-4 shrink-0 text-azure" />
                <span className="min-w-0 flex-1">{tidy(s.text)}</span>
                <span className="font-mono text-[11px] text-ink-3">{s.seconds} s</span>
              </li>
            ))}
          </ol>
        </Section>
      )}


      </div>

      {/* The agent's plan trace stays on screen: a column beside the briefing on wide screens. */}
      {(live.planSteps.length > 0 || inc.working) && (
        <aside className="mt-6 border-t border-line pt-5 lg:sticky lg:top-20 lg:mt-0 lg:max-h-[calc(100vh-7rem)] lg:overflow-y-auto lg:border-t-0 lg:pt-0">
          <header className="mb-3 flex items-baseline justify-between">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">Agent plan trace</h2>
            <span className="text-xs text-ink-3">{live.planSteps.length} steps</span>
          </header>
          <PlanTrace steps={live.planSteps} waiting={inc.working} />
        </aside>
      )}

    </div>
  )
}

function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="mt-6 border-t border-line pt-5">
      <header className="mb-3 flex items-baseline justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">{title}</h2>
        {aside}
      </header>
      {children}
    </section>
  )
}



const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
