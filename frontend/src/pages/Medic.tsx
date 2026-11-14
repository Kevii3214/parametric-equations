import { useState } from 'react'
import CueIcon from '../components/CueIcon'
import FloorMap from '../components/FloorMap'
import type { Cue, RouteStep } from '../lib/contracts'
import { useDemo, useIncidentParam } from '../lib/demo'
import { closures, graphFor } from '../lib/incident'
import { useRouteReplay } from '../lib/replay'
import { cueLabel, formatSeconds, isFloorChange, nodeMap, positionPoint } from '../lib/route'
import { useIncidentLive } from '../lib/useIncidentLive'

export default function Medic() {
  const demo = useDemo()
  const [incidentId] = useIncidentParam()
  const live = useIncidentLive(incidentId, demo)
  const route = live.route
  const steps = route?.steps ?? []
  const graph = graphFor(steps)
  const replay = useRouteReplay(route, graph, live.source === 'fixtures')
  const position = replay?.position ?? live.position
  const [pickedFloor, setPickedFloor] = useState<number | null>(null)

  if (!route) {
    return (
      <div className="mx-auto max-w-md py-16 text-center text-slate-400">
        {incidentId
          ? 'Waiting for the route…'
          : <>No incident selected. Open this page from Dispatch, or add <code className="text-slate-300">?incident=&lt;id&gt;</code>.</>}
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
    <div className="mx-auto grid max-w-5xl gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div className="space-y-4">
        <NextTurn cue={cue} distance={distance} text={text} offRoute={offRoute}
          then={!arrived && !offRoute ? steps[stepIndex + 1] : undefined} />
        <div className="grid grid-cols-3 gap-2 text-center">
          <Stat label="Remaining" value={formatSeconds(remaining)} />
          <Stat label="Floor" value={currentFloor} />
          <Stat label="Step" value={`${stepIndex + 1} / ${steps.length}`} />
        </div>
        {replay && (
          <div className="flex items-center gap-2 rounded-lg border border-dashed border-slate-700 px-3 py-2 text-sm">
            <span className="text-xs text-amber-400">Demo replay</span>
            <div className="ml-auto flex gap-1">
              <CtlButton onClick={() => replay.jump(-1)} label="Previous step">‹</CtlButton>
              <CtlButton onClick={replay.toggle} label={replay.playing ? 'Pause' : 'Play'}>
                {replay.playing ? '❚❚' : '▶'}
              </CtlButton>
              <CtlButton onClick={() => replay.jump(1)} label="Next step">›</CtlButton>
              <CtlButton onClick={replay.restart} label="Restart">↺</CtlButton>
            </div>
          </div>
        )}
        <Upcoming steps={steps} current={stepIndex} arrived={arrived} />
      </div>

      <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
        <header className="mb-2 flex items-center gap-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Floor map</h2>
          <div className="ml-auto flex gap-1">
            {floors.map((f) => (
              <button key={f} type="button" onClick={() => setPickedFloor(f === currentFloor ? null : f)}
                className={`min-w-9 rounded px-2 py-1 text-xs font-semibold ${
                  f === floor ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>
                {f}{f === currentFloor && pickedFloor !== null && pickedFloor !== f ? ' •' : ''}
              </button>
            ))}
          </div>
        </header>
        {graph ? (
          <FloorMap graph={graph} floor={floor} steps={steps} currentStep={stepIndex}
            position={point} offRoute={offRoute} closures={closures(live.planSteps)}
            className="aspect-[4/3] w-full rounded-lg bg-slate-950" />
        ) : (
          <p className="py-16 text-center text-sm text-slate-500">No floor plan for this building yet.</p>
        )}
        {pickedFloor !== null && pickedFloor !== currentFloor && (
          <button type="button" onClick={() => setPickedFloor(null)}
            className="mt-2 text-xs text-sky-400 hover:underline">Follow my floor ({currentFloor})</button>
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
      className={`rounded-2xl border p-4 ${offRoute ? 'border-red-700 bg-red-950/60' : 'border-sky-800 bg-sky-950/40'}`}>
      <div className="flex items-center gap-4">
        <div className={`grid h-20 w-20 shrink-0 place-items-center rounded-xl ${offRoute ? 'bg-red-600' : 'bg-sky-600'} text-white`}>
          <CueIcon cue={cue} className="h-12 w-12" />
        </div>
        <div className="min-w-0">
          {showDist && <div className="text-sm font-medium text-slate-300">In {Math.round(distance)} m</div>}
          <div className="text-3xl font-bold leading-tight text-white">{cueLabel[cue]}</div>
        </div>
      </div>
      <p className="mt-3 text-base text-slate-100">{text}</p>
      {then && (
        <p className="mt-2 flex items-center gap-1.5 text-sm text-slate-400">
          Then <CueIcon cue={then.cue} className="h-4 w-4" /> {cueLabel[then.cue].toLowerCase()}
        </p>
      )}
    </section>
  )
}

function Upcoming({ steps, current, arrived }: { steps: RouteStep[]; current: number; arrived: boolean }) {
  return (
    <ol className="space-y-1">
      {steps.map((s) => {
        const state = arrived || s.index < current ? 'done' : s.index === current ? 'now' : 'next'
        return (
          <li key={s.index} className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm ${
            state === 'now' ? 'bg-slate-800 text-white' : state === 'done' ? 'text-slate-600' : 'text-slate-300'}`}>
            <CueIcon cue={s.cue} className={`h-4 w-4 shrink-0 ${state === 'now' ? 'text-sky-400' : ''}`} />
            <span className="min-w-0 flex-1 truncate">{s.text}</span>
          </li>
        )
      })}
    </ol>
  )
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="text-lg font-semibold text-slate-100">{value}</div>
    </div>
  )
}

function CtlButton({ onClick, label, children }: { onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-label={label} title={label}
      className="grid h-8 w-8 place-items-center rounded bg-slate-800 text-slate-200 hover:bg-slate-700">
      {children}
    </button>
  )
}
