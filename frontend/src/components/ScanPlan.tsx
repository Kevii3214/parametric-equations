import type { MpSdk } from '@matterport/sdk'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { Building } from '../lib/buildings'
import type { BuildingGraph, RouteStep } from '../lib/contracts'
import type { Point } from '../lib/route'
import { apiToSdk } from '../lib/tour'

/** Matterport SDK key (VITE_MATTERPORT_SDK_KEY). Without it this view is not offered. */
const SCAN_PLAN_KEY = (import.meta.env.VITE_MATTERPORT_SDK_KEY as string | undefined) || ''

interface Props {
  building: Building
  graph: BuildingGraph
  floor: number
  steps: RouteStep[]
  currentStep: number
  position?: Point | null
  /** Called if the scan cannot be shown, so the page can fall back to the drawn plan. */
  onFail: (reason: string) => void
  /** True when this floor is ahead on the route, not the floor the medic is on. */
  heading?: boolean
  className?: string
}

type Pose = MpSdk.Camera.Pose

/**
 * The floor in the Matterport scan's dollhouse view (the 3D model seen from
 * above at an angle), with the route drawn over it. Route points are in the scan's own
 * frame, so each is projected to the screen with the SDK's worldToScreen on
 * every camera move, staying aligned while the user pans or zooms.
 */
export default function ScanPlan({ building, graph, floor, steps, currentStep, position, onFail, heading, className }: Props) {
  const src = building.floorPlans?.[floor]
  const frame = useRef<HTMLIFrameElement>(null)
  const box = useRef<HTMLDivElement>(null)
  const [pose, setPose] = useState<Pose | null>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  // The connected SDK; null until the scan is in its floor-plan view.
  const [sdk, setSdk] = useState<MpSdk | null>(null)
  const ready = sdk !== null
  const failRef = useRef(onFail)
  useEffect(() => { failRef.current = onFail }, [onFail])

  // Height of this floor in the scan: about 4 m per level above the scan's lowest level on the route.
  const height = useMemo(() => {
    const idx = Object.values(building.floorPlans ?? {}).map((f) => f.scanFloorIndex ?? 0)
    const lowest = idx.length ? Math.min(...idx) : 0
    return ((src?.scanFloorIndex ?? 0) - lowest) * 4
  }, [building, src])

  // Connect once per model, switch to the floor-plan view, then follow the camera.
  useEffect(() => {
    if (!SCAN_PLAN_KEY || !src || !frame.current) return
    const iframe = frame.current
    let alive = true
    let sub: { cancel(): void } | null = null
    void (async () => {
      try {
        const { setupSdk } = await import('@matterport/sdk')
        const sdk = await setupSdk(SCAN_PLAN_KEY, { iframe, space: src.modelId })
        await Promise.race([
          sdk.App.state.waitUntil((st) => st.phase === sdk.App.Phase.PLAYING),
          new Promise((_, rej) => setTimeout(() => rej(new Error('the scan did not start in 20 s')), 20_000)),
        ])
        if (!alive) return
        await sdk.Mode.moveTo(sdk.Mode.Mode.DOLLHOUSE, { transition: sdk.Camera.TransitionType.INSTANT })
        if (src.scanFloorIndex != null) await sdk.Floor.moveTo(src.scanFloorIndex).catch(() => undefined)
        sub = sdk.Camera.pose.subscribe((p) => { if (alive) setPose(p) })
        if (alive) setSdk(sdk)
      } catch (err) {
        if (alive) failRef.current(err instanceof Error ? err.message : String(err))
      }
    })()
    return () => { alive = false; sub?.cancel() }
  }, [src])

  // Follow the floor when the medic moves between the scan's levels.
  useEffect(() => {
    if (sdk && src?.scanFloorIndex != null) void sdk.Floor.moveTo(src.scanFloorIndex).catch(() => undefined)
  }, [sdk, src])

  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const toScreen = (x: number, y: number) => {
    if (!sdk || !pose || !size.w) return null
    const p = sdk.Conversion.worldToScreen(apiToSdk({ x, y, z: height }), pose, size)
    return Number.isFinite(p.x) && Number.isFinite(p.y) ? { x: p.x, y: p.y } : null
  }
  const nodes = new Map(graph.nodes.map((n) => [n.id, n]))
  const segs = steps
    .map((s) => ({ s, a: nodes.get(s.from_node), b: nodes.get(s.to_node) }))
    .filter((x) => x.a?.floor === floor && x.b?.floor === floor)
    .map(({ s, a, b }) => ({ s, a: toScreen(a!.x, a!.y), b: toScreen(b!.x, b!.y) }))
  const goal = nodes.get(steps.at(-1)?.to_node ?? '')
  const goalPt = goal?.floor === floor ? toScreen(goal.x, goal.y) : null
  const herePt = position && position.floor === floor ? toScreen(position.x, position.y) : null

  return (
    <div ref={box} className={`relative overflow-hidden bg-ink ${className ?? ''}`}>
      {src && (
        <iframe ref={frame} title="Floor from the scan" className="absolute inset-0 h-full w-full border-0"
          allow="fullscreen; xr-spatial-tracking"
          src={`https://my.matterport.com/show/?${new URLSearchParams({
            m: src.modelId, play: '1', qs: '1', help: '0', brand: '0', mls: '0', title: '0', hr: '0',
            // Hide Matterport's own buttons and tips so the route stays visible.
            gt: '0', hl: '0', mt: '0', f: '0', search: '0', vr: '0', pin: '0', portal: '0', tour: '0', nt: '1',
            applicationKey: SCAN_PLAN_KEY,
          })}`} />
      )}
      {ready && (
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${size.w} ${size.h}`}>
          {segs.map(({ s, a, b }) => a && b && (
            <line key={s.index} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeLinecap="round"
              stroke={s.index < currentStep ? '#9fb7ef' : '#2357d6'} strokeWidth={s.index === currentStep ? 9 : 6}
              style={{ filter: 'drop-shadow(0 0 2px white)' }} />
          ))}
          {goalPt && (
            <g transform={`translate(${goalPt.x} ${goalPt.y})`}>
              <circle r={14} fill="#c93c3c" opacity={0.25} />
              <circle r={7} fill="#c93c3c" stroke="white" strokeWidth={2.5} />
            </g>
          )}
          {herePt && (
            <g transform={`translate(${herePt.x} ${herePt.y})`}>
              <circle r={14} fill="#2357d6" opacity={0.25}><animate attributeName="r" values="9;17;9" dur="1.6s" repeatCount="indefinite" /></circle>
              <circle r={7} fill="#2357d6" stroke="white" strokeWidth={2.5} />
            </g>
          )}
        </svg>
      )}
      <div className="pointer-events-none absolute top-2 left-2 rounded-full bg-card/90 px-2.5 py-1 text-[11px] font-medium text-ink-2 shadow-card">
        Floor {floor} · {ready ? (heading ? "where you're heading" : '3D scan') : 'loading the scan…'}
      </div>
    </div>
  )
}
