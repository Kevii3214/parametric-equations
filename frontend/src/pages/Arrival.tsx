import { lazy, Suspense, useMemo, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import CueIcon from '../components/CueIcon'
import FloorPlan from '../components/FloorPlan'
import Icon from '../components/Icon'
import { sendEvent } from '../lib/api'
import type { RouteRow, RouteStep } from '../lib/contracts'
import { replanAround, type Problem } from '../lib/replan'
import { useRouteReplay } from '../lib/replay'
import { cueLabel, formatSeconds, isFloorChange, nodeMap, positionPoint, tidy, type Point } from '../lib/route'
import { useStepCursor } from '../lib/stepCursor'
import { useIncident } from '../lib/useIncident'

const TourPlayer = lazy(() => import('../components/tour/TourPlayer'))
const SiteFlyover = lazy(() => import('../components/site/SiteFlyover'))
// The scan-from-above view loads the Matterport SDK, so it is split out too.
const ScanPlan = lazy(() => import('../components/ScanPlan'))
const SCAN_KEY = (import.meta.env.VITE_MATTERPORT_SDK_KEY as string | undefined) || ''

/** Inside the building: one instruction at a time, Next / Back, and what to do when the way is blocked. */
export default function Arrival() {
  const inc = useIncident()
  const { search } = useLocation()
  const [notice, setNotice] = useState<string | null>(null)
  const [preview, setPreview] = useState(false)
  // Scanned floors open on the scan seen from above; the drawn plan is the toggle and the fallback.
  const [planView, setPlanView] = useState<'scan' | 'drawn'>('scan')
  // Demo re-plans are worked out here; live ones come back from the server as a new route version.
  const [demoRoute, setDemoRoute] = useState<{ steps: RouteStep[]; n: number; base: string } | null>(null)

  const baseKey = inc.route ? `${inc.route.id}-${inc.route.version}` : ''
  const override = demoRoute && demoRoute.base === baseKey ? demoRoute : null
  const route: RouteRow | null = useMemo(
    () => (inc.route && override ? { ...inc.route, steps: override.steps, version: inc.route.version + override.n } : inc.route),
    [inc.route, override],
  )
  const steps = route?.steps ?? []
  const graph = inc.graph
  const nodes = graph ? nodeMap(graph) : null
  const replay = useRouteReplay(route, graph, inc.live.source === 'fixtures')
  const position = replay?.playing || replay?.done ? replay.position : inc.live.position
  const cursor = useStepCursor(`${baseKey}-${override?.n ?? 0}`, steps.length, position?.step_index ?? null)

  if (!route || !steps.length) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <p className="text-ink-2">{inc.working ? 'The route is still being planned…' : 'No route yet.'}</p>
        <Link to={{ pathname: '/pre-arrival', search }} className="mt-3 inline-block text-sm font-semibold text-azure hover:underline">
          Back to Pre-arrival
        </Link>
      </div>
    )
  }

  const i = cursor.index
  const step = steps[i]
  const from = nodes?.get(step.from_node)
  const offRoute = inc.live.position?.off_route ?? false
  const arrived = inc.live.incident?.status === 'arrived'
  const remaining = steps.slice(i).reduce((t, s) => t + s.seconds, 0)
  const point: Point | null = position && nodes ? positionPoint(position, steps, nodes)
    : from ? { x: from.x, y: from.y, floor: from.floor } : null
  const floor = point?.floor ?? from?.floor ?? step.floor
  const last = i === steps.length - 1
  const scanned = !!SCAN_KEY && !!inc.site?.floorPlans?.[floor]

  async function report(problem: Problem) {
    if (!route || !graph) return
    if (inc.demo || inc.live.source === 'fixtures') {
      const r = replanAround(graph, steps, i, problem)
      if (!r) { setNotice(problem === 'elevator_out' ? 'No elevator ahead on this route.' : 'No other way around from here.'); return }
      setDemoRoute({ steps: r.steps, n: (override?.n ?? 0) + 1, base: baseKey })
      setNotice(`Re-planned around ${problem === 'elevator_out' ? 'the elevator' : 'the blockage'}: ${formatSeconds(r.steps.reduce((t, s) => t + s.seconds, 0))} from here.`)
      return
    }
    try {
      await sendEvent(inc.incidentId!, problem === 'elevator_out' ? 'elevator_out' : 'obstacle', null, false)
      setNotice('Reported. The agent is re-planning; the new route appears here.')
    } catch {
      setNotice('Could not reach the server. Try again, or use the floor map.')
    }
  }



  if (arrived) {
    return (
      <div className="mx-auto max-w-xl">
        <section className="rounded-3xl bg-gradient-to-br from-fern to-fern-deep p-6 text-white shadow-card">
          <CueIcon cue="ARRIVE" className="h-12 w-12" />
          <h1 className="mt-4 text-4xl font-semibold tracking-tight">Patient reached</h1>
          <p className="mt-1 text-sm text-white/70">{tidy(nodes?.get(steps.at(-1)!.to_node)?.label ?? '')}</p>
        </section>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-3 pb-6">
      {/* Where we are */}
      <div className="flex items-center gap-2 text-xs font-medium text-ink-2">
        <span className="truncate">{inc.site?.record.name ?? 'Building'}</span>
        <span className="text-ink-3">·</span>
        <span>Floor {floor}</span>
        <span className="ml-auto tabular-nums">Step {i + 1}/{steps.length} · {formatSeconds(remaining)} left</span>
      </div>
      <div className="flex gap-1" aria-hidden="true">
        {steps.map((s) => (
          <span key={s.index} className={`h-1 flex-1 rounded-full ${s.index < i ? 'bg-azure-line' : s.index === i ? 'bg-azure' : 'bg-sunk'}`} />
        ))}
      </div>

      <StepCard step={step} next={steps[i + 1]} offRoute={offRoute} fromFloor={from?.floor ?? step.floor}
        onNext={cursor.next} onBack={cursor.back} />

      {notice && (
        <p role="status" className="flex items-start gap-2 rounded-2xl bg-amber-soft px-3 py-2 text-sm text-ink">
          <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0 text-amber" />
          <span className="flex-1">{notice}</span>
          <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><Icon name="close" className="h-4 w-4 text-ink-3" /></button>
        </p>
      )}

      {/* Back / Next, in thumb reach */}
      <div className="grid grid-cols-[1fr_2fr] gap-2">
        <button type="button" onClick={cursor.back} disabled={i === 0}
          className="flex h-14 items-center justify-center gap-1.5 rounded-2xl border border-line bg-card text-base font-semibold text-ink-2 shadow-card disabled:opacity-40">
          <Icon name="prev" className="h-5 w-5" /> Back
        </button>
        <button type="button" onClick={cursor.next} disabled={last}
          className="flex h-14 items-center justify-center gap-2 rounded-2xl bg-azure text-base font-semibold text-white shadow-card hover:bg-azure-deep disabled:bg-line-strong">
          {last ? 'Last step' : <>Done, next step <Icon name="next" className="h-5 w-5" /></>}
        </button>
      </div>

      {/* The floor, following the current step */}
      {graph && (
        <section className="overflow-hidden rounded-2xl border border-line bg-card shadow-card">
          {scanned && (
            <div className="flex gap-0.5 border-b border-line bg-card p-1.5">
              {(['scan', 'drawn'] as const).map((v) => (
                <button key={v} type="button" onClick={() => setPlanView(v)}
                  className={`flex-1 rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                    planView === v ? 'bg-azure-soft text-azure-deep' : 'text-ink-2 hover:text-ink'}`}>
                  {v === 'scan' ? 'Scan from above' : 'Drawn plan'}
                </button>
              ))}
            </div>
          )}
          {scanned && planView === 'scan' && inc.site ? (
            <Suspense fallback={<div className="grid aspect-[4/3] w-full place-items-center bg-sunk text-sm text-ink-3">Loading the scan…</div>}>
              <ScanPlan key={`${inc.site.id}:${floor}`} building={inc.site} graph={graph} floor={floor} steps={steps}
                currentStep={i} position={point} className="aspect-[4/3] w-full"
                onFail={(why) => { setPlanView('drawn'); setNotice(`Could not show the scan from above (${why}); showing the drawn plan.`) }} />
            </Suspense>
          ) : (
            <FloorPlan building={inc.site} graph={graph} floor={floor} steps={steps} currentStep={i} position={point}
              offRoute={offRoute} className="aspect-[4/3] w-full bg-sunk" />
          )}
          {inc.site && (
            <button type="button" onClick={() => setPreview(true)}
              className="flex w-full items-center gap-2 border-t border-line px-3 py-2.5 text-sm font-semibold text-azure hover:bg-azure-soft">
              <Icon name="route" className="h-4 w-4" /> Preview this step in 3D
            </button>
          )}
        </section>
      )}

      {/* When the way is blocked */}
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={() => void report('elevator_out')}
          className="h-12 rounded-2xl border border-line bg-card text-sm font-semibold text-ink shadow-card hover:border-amber hover:text-amber">
          Elevator out
        </button>
        <button type="button" onClick={() => void report('blocked')}
          className="h-12 rounded-2xl border border-line bg-card text-sm font-semibold text-ink shadow-card hover:border-amber hover:text-amber">
          Way blocked
        </button>
      </div>


      {replay && (
        <button type="button" onClick={replay.toggle} className="self-center text-xs text-ink-3 hover:text-azure">
          {replay.playing ? 'Pause demo walk' : 'Demo: walk the route automatically'}
        </button>
      )}

      {preview && inc.site && (
        <div className="fixed inset-0 z-20 flex flex-col bg-ink/70 p-3 backdrop-blur-sm" role="dialog" aria-label="Step preview">
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col overflow-hidden rounded-2xl bg-card">
            <header className="flex items-center gap-2 border-b border-line px-3 py-2">
              <span className="text-sm font-semibold text-ink">Step {i + 1}: {tidy(step.text)}</span>
              <button type="button" onClick={() => setPreview(false)} aria-label="Close preview"
                className="ml-auto grid h-9 w-9 place-items-center rounded-full hover:bg-sunk"><Icon name="close" /></button>
            </header>
            <div className="relative min-h-0 flex-1">
              <Suspense fallback={<div className="grid h-full place-items-center text-sm text-ink-3">Loading…</div>}>
                {inc.tour && inc.tour.keyframes.some((k) => k.kind === 'scanned' && k.step_index >= i)
                  ? <TourPlayer key={`${baseKey}-${i}`} tour={inc.tour} building={inc.site} steps={steps} patientFloor={inc.patientFloor} startStep={i} />
                  : <SiteFlyover building={inc.site} entranceNode={route.entrance_node} mode="medic" patientFloor={inc.patientFloor}
                    steps={steps} currentStep={i} position={point} flyToken={1} />}
              </Suspense>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** The current instruction, big. Swipe left for Next, right for Back. */
function StepCard({ step, next, offRoute, fromFloor, onNext, onBack }: {
  step: RouteStep; next?: RouteStep; offRoute: boolean; fromFloor: number; onNext: () => void; onBack: () => void
}) {
  const x0 = useRef<number | null>(null)
  const swipe = {
    onPointerDown: (e: React.PointerEvent) => { x0.current = e.clientX },
    onPointerUp: (e: React.PointerEvent) => {
      if (x0.current === null) return
      const dx = e.clientX - x0.current
      x0.current = null
      if (dx < -60) onNext()
      else if (dx > 60) onBack()
    },
  }
  const floorChange = isFloorChange(step.cue)
  const stairs = /stairs/i.test(step.text)
  const tone = offRoute ? 'bg-alert' : step.cue === 'ARRIVE' ? 'bg-gradient-to-br from-fern to-fern-deep' : 'bg-gradient-to-br from-azure to-azure-deep'

  return (
    <section aria-live="polite" {...swipe}
      className={`relative touch-pan-y overflow-hidden rounded-3xl p-5 text-white shadow-[0_12px_32px_-14px_rgb(24_63_159_/_0.55)] select-none ${tone}`}>
      {offRoute ? (
        <>
          <CueIcon cue="OFF_ROUTE" className="h-14 w-14" />
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">Off route</h1>
          <p className="mt-2 text-lg text-white/90">Stop. A new route is on its way.</p>
        </>
      ) : floorChange ? (
        <>
          <p className="text-sm font-medium text-white/75">{stairs ? 'Stairs' : 'Elevator'}</p>
          <div className="mt-1 flex items-center gap-4">
            <span className="text-2xl font-semibold text-white/70 tabular-nums">{fromFloor}</span>
            <CueIcon cue={step.cue} className="h-10 w-10" />
            <span className="text-6xl font-semibold tracking-tight tabular-nums">{step.floor}</span>
          </div>
          <p className="mt-3 text-xl font-medium leading-snug">{tidy(step.text)}</p>
        </>
      ) : (
        <>
          <div className="flex items-center gap-4">
            <div className="grid h-20 w-20 shrink-0 place-items-center rounded-2xl bg-white/15 ring-1 ring-white/25">
              <CueIcon cue={step.cue} className="h-12 w-12" />
            </div>
            <div className="min-w-0">
              {step.meters > 0.5 && <p className="text-base font-medium text-white/80 tabular-nums">{Math.round(step.meters)} m</p>}
              <h1 className="text-4xl font-semibold leading-tight tracking-tight">{cueLabel[step.cue]}</h1>
            </div>
          </div>
          <p className="mt-4 text-xl leading-snug text-white/95">{tidy(step.text)}</p>
        </>
      )}
      {next && !offRoute && (
        <p className="mt-4 flex items-center gap-2 border-t border-white/15 pt-3 text-base text-white/75">
          Then <CueIcon cue={next.cue} className="h-5 w-5" /> {tidy(next.text)}
        </p>
      )}
    </section>
  )
}
