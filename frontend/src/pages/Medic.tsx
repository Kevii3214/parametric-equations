import { lazy, Suspense, useState } from 'react'
import Icon from '../components/Icon'
import CueIcon from '../components/CueIcon'
import FloorMap from '../components/FloorMap'
import FindDoor from '../components/site/FindDoor'
import MatterportTour from '../components/site/MatterportTour'
import { buildingById, buildingForRoute, patientFloor } from '../lib/buildings'
import type { Cue, RouteStep } from '../lib/contracts'
import { useDemo, useDemoBuilding, useIncidentParam } from '../lib/demo'
import { closures, graphFor } from '../lib/incident'
import { useRouteReplay } from '../lib/replay'
import { cueLabel, formatSeconds, isFloorChange, nodeMap, positionPoint, tidy } from '../lib/route'
import { readTour } from '../lib/tour'
import { useIncidentLive } from '../lib/useIncidentLive'

// MapLibre is large, so the 3D route view loads only when opened.
const SiteFlyover = lazy(() => import('../components/site/SiteFlyover'))
const TourPlayer = lazy(() => import('../components/tour/TourPlayer'))

export default function Medic() {
  const demo = useDemo()
  const [incidentId] = useIncidentParam()
  const live = useIncidentLive(incidentId, demo, useDemoBuilding())
  const route = live.route
  const steps = route?.steps ?? []
  const graph = graphFor(steps)
  const replay = useRouteReplay(route, graph, live.source === 'fixtures')
  const position = replay?.position ?? live.position
  const [pickedFloor, setPickedFloor] = useState<number | null>(null)
  const [view, setView] = useState<'plan' | 'tour' | 'route3d' | 'scan'>('plan')
  const [flyToken, setFlyToken] = useState(0)

  // The Matterport scan of the destination suite, when this building has one.
  const site = buildingById(live.incident?.building_id) ?? buildingForRoute(steps.flatMap((s) => [s.from_node, s.to_node]))
  const scans = site?.matterport.filter((m) => m.destination) ?? []
  const tour = readTour(live.route?.tour)
  const entranceMarker = site?.markers.find((m) => m.node === route?.entrance_node) ?? null
  const [doorHidden, setDoorHidden] = useState(false)

  if (!route) {
    return (
      <div className="mx-auto max-w-md py-16 text-center text-ink-2">
        {incidentId
          ? 'Waiting for the route…'
          : <>No incident selected. Open this page from Dispatch, or add <code className="rounded bg-sunk px-1 font-mono text-ink">?incident=&lt;id&gt;</code>.</>}
      </div>
    )
  }

  const stepIndex = Math.min(position?.step_index ?? 0, steps.length - 1)
  const step = steps[stepIndex]
  const progress = position?.step_index === stepIndex ? position.progress_m : 0
  const offRoute = position?.off_route ?? false
  const arrived = live.incident?.status === 'arrived' || (replay?.done ?? false)

  // The live cue row wins when there is one; otherwise derive it from the route.
  const cue: Cue = offRoute ? 'OFF_ROUTE' : arrived ? 'ARRIVE' : live.cue?.cue ?? step.cue
  const distance = arrived ? 0 : live.cue?.dist_m ?? Math.max(0, step.meters - progress)
  const text = offRoute
    ? 'You are off the route. Stop and wait for a new cue.'
    : arrived ? 'You have arrived.' : live.cue?.text ?? step.text
  const remaining = arrived ? 0 : steps.slice(stepIndex + 1).reduce((t, s) => t + s.seconds, 0)
    + step.seconds * (step.meters > 0 ? 1 - progress / step.meters : 1)

  const nodes = graph ? nodeMap(graph) : null
  const point = position && nodes ? positionPoint(position, steps, nodes) : null
  const currentFloor = point?.floor ?? position?.floor ?? nodes?.get(step.from_node)?.floor ?? step.floor
  const floors = [...new Set(steps.flatMap((s) => [nodes?.get(s.from_node)?.floor ?? s.floor, s.floor]))]
  const floor = pickedFloor ?? currentFloor

  return (
    <div className="mx-auto grid max-w-5xl gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div className="min-w-0 space-y-4">
        {site?.imageryMatches && entranceMarker && stepIndex === 0 && !arrived && !doorHidden && (
          <FindDoor building={site} entrance={entranceMarker} onDismiss={() => setDoorHidden(true)} />
        )}
        <NextTurn cue={cue} distance={distance} text={text} offRoute={offRoute}
          then={!arrived && !offRoute ? steps[stepIndex + 1] : undefined} />
        <div className="grid grid-cols-3 gap-2 text-center">
          <Stat label="Remaining" value={formatSeconds(remaining)} />
          <Stat label="Floor" value={currentFloor} />
          <Stat label="Step" value={`${stepIndex + 1} / ${steps.length}`} />
        </div>
        {site && (
          <button type="button" onClick={() => { if (tour) setView('tour'); else { setView('route3d'); setFlyToken((t) => t + 1) } }}
            className="flex w-full items-center gap-3 rounded-2xl bg-gradient-to-r from-azure to-azure-deep px-4 py-3 text-left text-white shadow-card transition hover:brightness-110">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white/15"><Icon name="route" className="h-5 w-5" /></span>
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">Fly the indoor route</span>
              <span className="block truncate text-sm text-white/75">
                {tour ? 'Automatic walk-through in the 3D scan' : '3D walk-through'} from the entrance to the patient, floor {patientFloor(site, live.incident?.parsed ?? null) ?? '?'}
              </span>
            </span>
            <Icon name="play" className="h-5 w-5 shrink-0" />
          </button>
        )}
        {replay && (
          <div className="flex items-center gap-2 rounded-2xl border border-line bg-card px-3 py-2 text-sm shadow-card">
            <span className="flex items-center gap-1.5 text-xs font-medium text-ink-2">
              <span className={`h-1.5 w-1.5 rounded-full ${replay.playing ? 'animate-pulse bg-azure' : 'bg-ink-3'}`} />
              Demo replay
            </span>
            <div className="ml-auto flex gap-1">
              <CtlButton onClick={() => replay.jump(-1)} label="Previous step"><Icon name="prev" /></CtlButton>
              <CtlButton onClick={replay.toggle} label={replay.playing ? 'Pause' : 'Play'}>
                <Icon name={replay.playing ? 'pause' : 'play'} />
              </CtlButton>
              <CtlButton onClick={() => replay.jump(1)} label="Next step"><Icon name="next" /></CtlButton>
              <CtlButton onClick={replay.restart} label="Restart"><Icon name="restart" /></CtlButton>
            </div>
          </div>
        )}
        <Upcoming steps={steps} current={stepIndex} arrived={arrived} />
      </div>

      <section className="min-w-0 self-start rounded-2xl border border-line bg-card p-4 shadow-card">
        <header className="mb-3 flex items-center gap-2">
          {site ? (
            <div className="flex gap-0.5 rounded-full bg-sunk p-0.5">
              {(['plan', ...(tour ? ['tour'] as const : []), 'route3d', ...(scans.length ? ['scan'] as const : [])] as const).map((v) => (
                <button key={v} type="button" onClick={() => setView(v)}
                  className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
                    view === v ? 'bg-card text-azure shadow-card' : 'text-ink-2 hover:text-ink'}`}>
                  {v === 'plan' ? 'Floor plan' : v === 'tour' ? 'Fly-through' : v === 'route3d' ? '3D route' : '3D scan'}
                </button>
              ))}
            </div>
          ) : (
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">Floor map</h2>
          )}
          <div className={`ml-auto flex gap-0.5 rounded-full bg-sunk p-0.5 ${view !== 'plan' ? 'invisible' : ''}`}>
            {floors.map((f) => (
              <button key={f} type="button" onClick={() => setPickedFloor(f === currentFloor ? null : f)}
                className={`min-w-10 rounded-full px-2.5 py-1 text-xs font-semibold transition ${
                  f === floor ? 'bg-card text-azure shadow-card' : 'text-ink-2 hover:text-ink'}`}>
                {f}{f === currentFloor && pickedFloor !== null && pickedFloor !== f && <span className="ml-1 inline-block h-1 w-1 rounded-full bg-azure align-middle" />}
              </button>
            ))}
          </div>
        </header>
        {view === 'tour' && site && tour ? (
          <div className="aspect-[4/3] w-full overflow-hidden rounded-xl">
            <Suspense fallback={<div className="grid h-full place-items-center bg-sunk text-sm text-ink-3">Loading fly-through…</div>}>
              {/* A re-plan (new route version) restarts the tour from the new one. */}
              <TourPlayer key={`${route.id}-${route.version}`} tour={tour} building={site} steps={steps}
                patientFloor={patientFloor(site, live.incident?.parsed ?? null)} />
            </Suspense>
          </div>
        ) : view === 'route3d' && site ? (
          <div className="aspect-[4/3] w-full overflow-hidden rounded-xl">
            <Suspense fallback={<div className="grid h-full place-items-center bg-sunk text-sm text-ink-3">Loading 3D route…</div>}>
              <SiteFlyover building={site} entranceNode={route.entrance_node} mode="medic"
                patientFloor={patientFloor(site, live.incident?.parsed ?? null)}
                steps={steps} currentStep={stepIndex} position={point} flyToken={flyToken} />
            </Suspense>
          </div>
        ) : view === 'scan' && scans.length ? (
          <div className="aspect-[4/3] w-full overflow-hidden rounded-xl">
            <MatterportTour models={scans} compact />
          </div>
        ) : graph ? (
          <FloorMap graph={graph} floor={floor} steps={steps} currentStep={stepIndex}
            position={point} offRoute={offRoute} closures={closures(live.planSteps)}
            className="aspect-[4/3] w-full rounded-xl bg-sunk" />
        ) : (
          <p className="py-16 text-center text-sm text-ink-3">No floor plan for this building yet.</p>
        )}
        {pickedFloor !== null && pickedFloor !== currentFloor && (
          <button type="button" onClick={() => setPickedFloor(null)}
            className="mt-3 text-xs font-medium text-azure hover:underline">Follow my floor ({currentFloor})</button>
        )}
      </section>
    </div>
  )
}

function NextTurn({ cue, distance, text, offRoute, then }: {
  cue: Cue; distance: number; text: string; offRoute: boolean; then?: RouteStep
}) {
  const showDist = !offRoute && cue !== 'ARRIVE' && !isFloorChange(cue) && distance > 0.5
  return (
    <section aria-live="polite"
      className={`relative overflow-hidden rounded-3xl p-5 text-white shadow-[0_12px_32px_-14px_rgb(24_63_159_/_0.55)] ${
        offRoute ? 'bg-alert' : cue === 'ARRIVE' ? 'bg-gradient-to-br from-fern to-fern-deep' : 'bg-gradient-to-br from-azure to-azure-deep'}`}>
      <div className="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full bg-white/10" aria-hidden="true" />
      <div className="relative flex items-center gap-4">
        <div className="grid h-20 w-20 shrink-0 place-items-center rounded-2xl bg-white/15 ring-1 ring-white/25">
          <CueIcon cue={cue} className="h-11 w-11" />
        </div>
        <div className="min-w-0">
          {showDist && <div className="text-sm font-medium text-white/75 tabular-nums">In {Math.round(distance)} m</div>}
          <div className="text-3xl font-semibold leading-tight tracking-tight">{cueLabel[cue]}</div>
        </div>
      </div>
      <p className="relative mt-4 text-[15px] leading-snug text-white/95">{tidy(text)}</p>
      {then && (
        <p className="relative mt-3 flex items-center gap-1.5 border-t border-white/15 pt-3 text-sm text-white/70">
          Then <CueIcon cue={then.cue} className="h-4 w-4" /> {cueLabel[then.cue].toLowerCase()}
        </p>
      )}
    </section>
  )
}

function Upcoming({ steps, current, arrived }: { steps: RouteStep[]; current: number; arrived: boolean }) {
  return (
    <ol className="space-y-0.5 rounded-2xl border border-line bg-card p-1.5 shadow-card">
      {steps.map((s) => {
        const state = arrived || s.index < current ? 'done' : s.index === current ? 'now' : 'next'
        return (
          <li key={s.index} className={`flex items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm ${
            state === 'now' ? 'bg-azure-soft font-medium text-azure-deep' : state === 'done' ? 'text-ink-3' : 'text-ink'}`}>
            {state === 'done'
              ? <span className="grid h-4 w-4 shrink-0 place-items-center rounded-full bg-fern-soft text-fern"><Icon name="check" className="h-3 w-3" /></span>
              : <CueIcon cue={s.cue} className={`h-4 w-4 shrink-0 ${state === 'now' ? 'text-azure' : 'text-ink-3'}`} />}
            <span className={`min-w-0 flex-1 truncate ${state === 'done' ? 'line-through decoration-line-strong' : ''}`}>{tidy(s.text)}</span>
          </li>
        )
      })}
    </ol>
  )
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-line bg-card px-2 py-2.5 shadow-card">
      <div className="text-[11px] text-ink-3">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tracking-tight text-ink tabular-nums">{value}</div>
    </div>
  )
}

function CtlButton({ onClick, label, children }: { onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className="grid h-8 w-8 place-items-center rounded-full text-ink-2 transition hover:bg-sunk hover:text-azure">
      {children}
    </button>
  )
}
