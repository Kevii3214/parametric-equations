import { lazy, Suspense, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import AlertBanner from '../components/AlertBanner'
import CueIcon from '../components/CueIcon'
import FloorPlan from '../components/FloorPlan'
import Icon from '../components/Icon'
import type { RouteStep } from '../lib/contracts'
import { useRouteReplay } from '../lib/replay'
import { cueLabel, formatSeconds, isFloorChange, nodeMap, positionPoint, tidy, type Point } from '../lib/route'
import { useStepCursor } from '../lib/stepCursor'
import { useIncident } from '../lib/useIncident'

const TourPlayer = lazy(() => import('../components/tour/TourPlayer'))
const SiteFlyover = lazy(() => import('../components/site/SiteFlyover'))
// The scan-from-above view loads the Matterport SDK, so it is split out too.
const ScanPlan = lazy(() => import('../components/ScanPlan'))
const SCAN_KEY = (import.meta.env.VITE_MATTERPORT_SDK_KEY as string | undefined) || ''

/** Inside the building: one instruction at a time, with Next / Back and the floor in the 3D scan. */
export default function Arrival() {
  const inc = useIncident()
  const { search } = useLocation()
  const [preview, setPreview] = useState(false)
  // Scanned floors show the 3D scan; unscanned ones (or a scan that fails) show the route on a plain corridor.
  const [scanFailed, setScanFailed] = useState(false)
  const route = inc.route
  const baseKey = route ? `${route.id}-${route.version}` : ''
  const steps = route?.steps ?? []
  const graph = inc.graph
  const nodes = graph ? nodeMap(graph) : null
  const replay = useRouteReplay(route, graph, inc.live.source === 'fixtures')
  const position = replay?.playing || replay?.done ? replay.position : inc.live.position
  const cursor = useStepCursor(baseKey, steps.length, position?.step_index ?? null)

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
  // The dollhouse shows the current floor when it is scanned; otherwise the next scanned floor ahead
  // on the route (where the medic is heading), so the 3D scan is on screen from the first step.
  const plans = inc.site?.floorPlans ?? {}
  const aheadFloor = steps.slice(i).map((s) => s.floor).find((f) => plans[f]) ?? steps.map((s) => s.floor).findLast((f) => plans[f])
  const scanFloor = plans[floor] ? floor : aheadFloor ?? null
  const scanned = !!SCAN_KEY && scanFloor != null





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
      <AlertBanner alerts={inc.live.alerts} />
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
          {scanned && !scanFailed && inc.site ? (
            <Suspense fallback={<div className="grid aspect-[4/3] w-full place-items-center bg-sunk text-sm text-ink-3">Loading the scan…</div>}>
              <ScanPlan key={`${inc.site.id}:${scanFloor}`} building={inc.site} graph={graph} floor={scanFloor!} steps={steps}
                heading={scanFloor !== floor}
                currentStep={i} position={point} className="aspect-[4/3] w-full"
                onFail={() => setScanFailed(true)} />
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
