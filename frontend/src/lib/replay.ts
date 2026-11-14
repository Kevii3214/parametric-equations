import { useEffect, useState } from 'react'
import type { BuildingGraph, PositionRow, RouteRow } from './contracts'
import { nodeMap } from './route'

/** Replay runs this many times faster than the route's own timings. */
const SPEEDUP = 3
const TICK_MS = 250
/** Seconds (route time) the replay waits at the entrance, so the door photo can be seen. */
const ARRIVAL_HOLD = 18

interface Walk {
  step: number
  /** Seconds spent in the current step. */
  elapsed: number
  playing: boolean
}

/**
 * Demo-mode stand-in for the positions table: walks the route at its own
 * pace (sped up) so the medic view can be seen moving with no server and no
 * wearable. Returns null when disabled.
 */
export function useRouteReplay(route: RouteRow | null, graph: BuildingGraph | null, enabled: boolean) {
  const [walk, setWalk] = useState<Walk>({ step: 0, elapsed: -ARRIVAL_HOLD, playing: true })
  const steps = route?.steps ?? []
  const running = enabled && walk.playing && steps.length > 0

  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      setWalk((w) => {
        const elapsed = w.elapsed + (TICK_MS / 1000) * SPEEDUP
        const all = route?.steps ?? []
        const s = all[w.step]
        if (!s || elapsed < s.seconds) return { ...w, elapsed }
        if (w.step >= all.length - 1) return { step: w.step, elapsed: s.seconds, playing: false }
        return { ...w, step: w.step + 1, elapsed: 0 }
      })
    }, TICK_MS)
    return () => clearInterval(id)
  }, [running, route])

  if (!enabled || !route || !graph || !steps.length) return null

  const s = steps[walk.step]
  const f = s.seconds > 0 ? Math.min(1, Math.max(0, walk.elapsed) / s.seconds) : 1
  const from = nodeMap(graph).get(s.from_node)
  const position: PositionRow = {
    id: walk.step * 10_000 + Math.round(walk.elapsed * 10),
    incident_id: route.incident_id,
    route_version: route.version,
    step_index: walk.step,
    progress_m: s.meters * f,
    // Floor changes land halfway through the ride.
    floor: from && f < 0.5 ? from.floor : s.floor,
    off_route: false,
    created_at: route.created_at,
  }

  return {
    position,
    playing: walk.playing,
    done: !walk.playing && walk.step === steps.length - 1 && f >= 1,
    toggle: () => setWalk((w) => (w.playing || !(w.step === steps.length - 1 && f >= 1)
      ? { ...w, playing: !w.playing }
      : { step: 0, elapsed: -ARRIVAL_HOLD, playing: true })),
    restart: () => setWalk({ step: 0, elapsed: -ARRIVAL_HOLD, playing: true }),
    jump: (d: number) => setWalk((w) => ({
      ...w,
      step: Math.min(steps.length - 1, Math.max(0, w.step + d)),
      elapsed: 0,
    })),
  }
}
