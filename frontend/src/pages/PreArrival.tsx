import { lazy, Suspense, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import CostarCard from '../components/briefing/CostarCard'
import CallIntake from '../components/call/CallIntake'
import CueIcon from '../components/CueIcon'
import Icon from '../components/Icon'
import PlanTrace from '../components/PlanTrace'
import FindDoor from '../components/site/FindDoor'
import SiteImagery from '../components/site/SiteImagery'
import { headsUp, routeGlance, spokenSummary } from '../lib/briefing'
import { buildingById } from '../lib/buildings'
import { fixtureIncident } from '../lib/fixtures'
import { parsedNote } from '../lib/incident'
import { formatSeconds, nodeMap, tidy } from '../lib/route'
import { useIncident } from '../lib/useIncident'

// The fly-through (Matterport SDK) and the 3D map are large: load on demand.
const TourPlayer = lazy(() => import('../components/tour/TourPlayer'))

/** In the ambulance: who, where to stop, the route in advance, and what to watch for. */
export default function PreArrival() {
  const inc = useIncident()
  const { live, route, steps, site, tour, entrance } = inc
  const navigate = useNavigate()
  const { search } = useLocation()
  const note = parsedNote(live.incident?.parsed ?? null)
  const nodes = inc.graph ? nodeMap(inc.graph) : null
  const goal = nodes?.get(steps.at(-1)?.to_node ?? '')?.label ?? null
  const glance = routeGlance(steps)
  const warnings = headsUp(site, steps, live.planSteps)

  return (
    <div className="mx-auto max-w-3xl pb-28">
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
          {route && <Briefing text={route.briefing || spokenSummary(steps, entrance?.label ?? null, goal)} />}
        </header>
      )}

      {route && site && entrance && site.imageryMatches && (
        <Section title="Where to stop">
          <FindDoor building={site} entrance={entrance} />
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

      {route && warnings.length > 0 && (
        <Section title="Heads-up">
          <ul className="space-y-2">
            {warnings.map((w) => (
              <li key={w.text} className="flex gap-2.5 text-sm leading-snug text-ink">
                <Icon name={w.tone === 'ok' ? 'check' : 'info'}
                  className={`mt-0.5 h-4 w-4 shrink-0 ${w.tone === 'warn' ? 'text-amber' : w.tone === 'ok' ? 'text-fern' : 'text-ink-3'}`} />
                {w.text}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {site && route && (
        <Collapsible title="The building, in 3D and from above">
          <SiteImagery building={site} entranceNode={route.entrance_node} patientFloor={inc.patientFloor} steps={steps} />
        </Collapsible>
      )}

      {site && live.incident && (
        <Collapsible title="Building facts">
          <CostarCard building={site} incident={live.incident} steps={live.planSteps} />
        </Collapsible>
      )}

      {(live.planSteps.length > 0 || inc.working) && (
        <Collapsible title={`How the route was planned (${live.planSteps.length} steps)`} open={inc.working}>
          <PlanTrace steps={live.planSteps} waiting={inc.working} />
        </Collapsible>
      )}

      {route && (
        <div className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper/90 px-4 py-3 backdrop-blur">
          <button type="button" onClick={() => navigate({ pathname: '/arrival', search })}
            className="mx-auto flex w-full max-w-3xl items-center justify-center gap-2 rounded-2xl bg-azure py-3.5 text-base font-semibold text-white shadow-card hover:bg-azure-deep">
            We're here, start directions <Icon name="next" className="h-5 w-5" />
          </button>
        </div>
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

function Collapsible({ title, open, children }: { title: string; open?: boolean; children: ReactNode }) {
  return (
    <details open={open} className="group mt-6 border-t border-line pt-5">
      <summary className="flex cursor-pointer list-none items-center justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3 hover:text-azure">
        {title}
        <Icon name="next" className="h-4 w-4 transition group-open:rotate-90" />
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  )
}

/** Reads the briefing aloud with the browser's speech synthesis. */
function Briefing({ text }: { text: string }) {
  const [speaking, setSpeaking] = useState(false)
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window
  if (!text) return null
  const toggle = () => {
    if (!canSpeak) return
    if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return }
    const u = new SpeechSynthesisUtterance(text)
    u.onend = () => setSpeaking(false)
    window.speechSynthesis.speak(u)
    setSpeaking(true)
  }
  return (
    <div className="mt-4 flex items-start gap-3 rounded-2xl bg-azure-soft p-3">
      {canSpeak && (
        <button type="button" onClick={toggle} aria-label={speaking ? 'Stop briefing' : 'Play briefing'}
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-azure text-white hover:bg-azure-deep">
          <Icon name={speaking ? 'pause' : 'play'} className="h-4 w-4" />
        </button>
      )}
      <p className="text-sm leading-snug text-azure-deep">{tidy(text)}</p>
    </div>
  )
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)
