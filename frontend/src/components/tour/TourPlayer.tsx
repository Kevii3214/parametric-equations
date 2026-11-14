import type { MpSdk } from '@matterport/sdk'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { matterportUrl, type Building } from '../../lib/buildings'
import type { RouteStep } from '../../lib/contracts'
import { tidy } from '../../lib/route'
import { calibrate, gapPosition, moveFor, stateAt, type Tour } from '../../lib/tour'
import CueIcon from '../CueIcon'
import Icon from '../Icon'

// MapLibre is large, so the map for unscanned stretches loads on demand.
const SiteFlyover = lazy(() => import('../site/SiteFlyover'))

/** Matterport SDK key (VITE_MATTERPORT_SDK_KEY). Without it the player falls back to plain embeds. */
const SDK_KEY = (import.meta.env.VITE_MATTERPORT_SDK_KEY as string | undefined) || ''

/** The showcase URL the SDK connects to; https always (the SDK's own default is protocol-relative). */
const sdkEmbedUrl = (modelId: string) => `https://my.matterport.com/show/?${new URLSearchParams({
  m: modelId, play: '1', qs: '1', help: '0', brand: '0', mls: '0', title: '0', dh: '0', hr: '0', applicationKey: SDK_KEY,
})}`

type Viewer =
  | { kind: 'loading' }
  | { kind: 'sdk'; sdk: MpSdk; yaw: (bearing: number) => number }
  | { kind: 'plain'; reason: string }

/**
 * Automatic fly-through of a route's tour in the Matterport viewer. Scanned
 * stops fly the viewer to each sweep, facing the stop's bearing, arriving at
 * `t_ms` and holding for `dwell_ms`. Unscanned (gap) stretches show the 3D
 * map instead and cut into the scan when it starts. The user only watches.
 */
export default function TourPlayer({ tour, building, steps, patientFloor }: {
  tour: Tour; building: Building; steps: RouteStep[]; patientFloor: number | null
}) {
  const [t, setT] = useState(0)
  const [wantPlay, setPlaying] = useState(true)
  const [viewer, setViewer] = useState<Viewer>(SDK_KEY ? { kind: 'loading' } : { kind: 'plain', reason: 'no SDK key' })
  const [skipped, setSkipped] = useState(0)
  const frame = useRef<HTMLIFrameElement>(null)
  // React's development double-run would connect twice; connect once per model.
  const connectedFor = useRef<string | null>(null)
  const s = stateAt(tour, t)
  // The clock stops by itself at the end of the tour.
  const playing = wantPlay && !s.done
  const modelId = useMemo(() => tour.keyframes.find((k) => k.model_id)?.model_id ?? null, [tour])

  // The clock: real time while playing, held at the end.
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    let raf = 0
    const tick = (now: number) => {
      setT((v) => Math.min(tour.duration_ms, v + (now - last)))
      last = now
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, tour.duration_ms])

  // Connect the Matterport SDK once, then calibrate the compass from the opening view.
  useEffect(() => {
    if (!SDK_KEY || !modelId || !frame.current || connectedFor.current === modelId) return
    connectedFor.current = modelId
    const iframe = frame.current
    let cancelled = false
    let sdk: MpSdk | null = null
    void (async () => {
      try {
        const { setupSdk } = await import('@matterport/sdk')
        // With an existing iframe, setupSdk only connects: the iframe's src (with the key) is set below.
        sdk = await setupSdk(SDK_KEY, { iframe, space: modelId })
        // Never stall: if the scan has not started in 20 s, use the plain embed instead.
        await Promise.race([
          sdk.App.state.waitUntil((st) => st.phase === sdk!.App.Phase.PLAYING),
          new Promise((_, rej) => setTimeout(() => rej(new Error('scan did not start in 20 s')), 20_000)),
        ])
        // The viewer opens at the scan's start pose, which faces models[id].bearing_deg.
        const pose = await new Promise<MpSdk.Camera.Pose>((res) => {
          const sub = sdk!.Camera.pose.subscribe((p) => { sub.cancel(); res(p) })
        })
        const opening = tour.models[modelId]?.bearing_deg ?? 0
        if (!cancelled) setViewer({ kind: 'sdk', sdk, yaw: calibrate(opening, pose.rotation.y) })
      } catch (err) {
        console.warn('Matterport SDK:', err)
        if (!cancelled) setViewer({ kind: 'plain', reason: 'SDK could not connect' })
      }
    })()
    return () => {
      // Under the development double-run the same iframe stays: keep the connection.
      if (iframe.isConnected) return
      cancelled = true
      connectedFor.current = null
      try { sdk?.disconnect() } catch { /* already gone */ }
    }
  }, [modelId, tour.models])

  // Drive the viewer: each time a new scanned stop becomes the target, move to it.
  useEffect(() => {
    if (viewer.kind !== 'sdk' || s.index < 0) return
    const move = moveFor(tour, s.index)
    if (!move) return
    const { sdk, yaw } = viewer
    const transition = move.transition === 'fly' ? sdk.Camera.TransitionType.FLY
      : move.transition === 'fade' ? sdk.Camera.TransitionType.FADEOUT : sdk.Camera.TransitionType.INSTANT
    sdk.Sweep.moveTo(move.sweepId, {
      rotation: { x: move.pitch, y: yaw(move.bearing) },
      transition,
      transitionTime: move.transition === 'fade' ? Math.min(move.duration, 800) : move.duration,
    }).catch((err: unknown) => {
      // A sweep that will not load is skipped; the clock keeps the tour going.
      console.warn('Matterport sweep skipped:', move.sweepId, err)
      setSkipped((n) => n + 1)
    })
  }, [s.index, viewer, tour])

  // Without the SDK: a plain embed opened at the current stop's sweep (jumps between stops).
  const plainSweep = viewer.kind === 'plain' && s.keyframe?.kind === 'scanned' ? s.keyframe.sweep_id : null
  const plainUrl = plainSweep && modelId ? `${matterportUrl(modelId, { autoplay: true })}&ss=${plainSweep}` : null

  const restart = () => { setT(0); setPlaying(true) }
  const secs = (ms: number) => `${Math.floor(ms / 1000)}`.padStart(2, '0')
  const position = s.inGap ? gapPosition(tour, t) : null
  const showScan = !s.inGap && s.index >= 0

  return (
    <div className="relative h-full w-full overflow-hidden bg-ink">
      {/* The 3D map, under the scan; it shows through during unscanned stretches. */}
      <div className={`absolute inset-0 transition-opacity duration-500 ${showScan ? 'opacity-0' : 'opacity-100'}`}>
        <Suspense fallback={<div className="grid h-full place-items-center bg-sunk text-sm text-ink-3">Loading map…</div>}>
          <SiteFlyover building={building} entranceNode={steps[0]?.from_node ?? null} mode="medic"
            patientFloor={patientFloor} steps={steps} currentStep={Math.max(0, s.keyframe?.step_index ?? 0)} position={position}
            chrome={false} />
        </Suspense>
      </div>

      {/* The Matterport viewer: SDK-driven, or a plain embed per stop. */}
      <div className={`absolute inset-0 transition-opacity duration-500 ${showScan ? 'opacity-100' : 'pointer-events-none opacity-0'}`}>
        {viewer.kind !== 'plain'
          ? modelId && <iframe ref={frame} title="Matterport fly-through" className="h-full w-full border-0"
            allow="fullscreen; xr-spatial-tracking; autoplay" src={sdkEmbedUrl(modelId)} />
          : plainUrl && <iframe key={plainUrl} title="Matterport fly-through" src={plainUrl} className="h-full w-full border-0"
            allow="fullscreen; xr-spatial-tracking" />}
      </div>

      {/* Instruction banner */}
      <div className="pointer-events-none absolute inset-x-3 top-3 flex flex-col items-start gap-2">
        {s.caption && (
          <div key={s.caption} className="trace-in flex max-w-full items-center gap-2.5 rounded-2xl bg-azure/95 py-2 pr-3.5 pl-2 text-white shadow-card">
            {s.cue && <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-white/15"><CueIcon cue={s.cue} className="h-5 w-5" /></span>}
            <span className="min-w-0 text-sm font-medium leading-snug">{tidy(s.caption)}</span>
          </div>
        )}
        {s.inGap && (
          <span className="rounded-full bg-ink/80 px-3 py-1 text-xs font-medium text-white backdrop-blur">
            No scan here, showing map
          </span>
        )}
        {viewer.kind === 'loading' && showScan && (
          <span className="rounded-full bg-ink/80 px-3 py-1 text-xs font-medium text-white">Loading the scan…</span>
        )}
      </div>

      {/* Controls */}
      <div className="absolute inset-x-3 bottom-3 flex items-center gap-2 rounded-full bg-card/95 p-1.5 shadow-card">
        <button type="button" onClick={() => (s.done ? restart() : setPlaying((p) => !p))} aria-label={playing ? 'Pause' : 'Play'}
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-azure text-white hover:bg-azure-deep">
          <Icon name={playing ? 'pause' : 'play'} className="h-3.5 w-3.5" />
        </button>
        <button type="button" onClick={restart} aria-label="Restart"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-ink-2 hover:bg-sunk hover:text-azure">
          <Icon name="restart" className="h-4 w-4" />
        </button>
        <div className="relative h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-sunk" role="progressbar"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(s.progress * 100)}>
          {/* Scanned stretches tinted, so the gap-to-scan cut is visible on the bar. */}
          {tour.keyframes.map((k, i) => {
            const next = tour.keyframes[i + 1]
            if (k.kind !== 'scanned') return null
            const a = (k.t_ms / tour.duration_ms) * 100
            const b = ((next?.t_ms ?? tour.duration_ms) / tour.duration_ms) * 100
            return <span key={i} className="absolute inset-y-0 bg-azure-line" style={{ left: `${a}%`, width: `${b - a}%` }} />
          })}
          <span className="absolute inset-y-0 left-0 bg-azure" style={{ width: `${s.progress * 100}%` }} />
        </div>
        <span className="shrink-0 pr-2 font-mono text-[11px] text-ink-2 tabular-nums">
          0:{secs(t)} / 0:{secs(tour.duration_ms)}
        </span>
      </div>

      {(viewer.kind === 'plain' || skipped > 0) && (
        <span className="absolute right-3 bottom-[3.75rem] rounded-full bg-card/90 px-2.5 py-1 text-[11px] text-ink-3 shadow-card">
          {viewer.kind === 'plain' ? `Basic mode (${viewer.reason}): the scan jumps between stops` : `${skipped} stop${skipped > 1 ? 's' : ''} skipped`}
        </span>
      )}
    </div>
  )
}
