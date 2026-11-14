// Fly-through tour for a route (contracts/tour.schema.json, notes at the end
// of contracts/api.md). Pure timing and calibration logic: no DOM, no SDK, so
// it can be tested with the sample tours in fixtures/buildings/<id>/.
import type { Cue } from './contracts'

export interface TourPoint { x: number; y: number; z: number }

export interface TourKeyframe {
  i: number
  t_ms: number
  dwell_ms: number
  kind: 'scanned' | 'gap'
  frame: 'scan' | 'plan'
  node: string
  step_index: number
  waypoint: boolean
  model_id: string | null
  sweep_id: string | null
  position: TourPoint
  level: number
  bearing_deg: number
  pitch_deg: number
  transition: 'none' | 'fly' | 'fade'
  caption: string
  cue: Cue | null
}

export interface TourSegment {
  kind: 'scanned' | 'gap'
  from_step: number
  to_step: number
  model_id?: string | null
  reason?: string | null
}

export interface Tour {
  version?: number
  speed_up: number
  duration_ms: number
  segments: TourSegment[]
  keyframes: TourKeyframe[]
  models: Record<string, { position: TourPoint; bearing_deg: number; pitch_deg: number }>
}

/** A route's tour if it is usable; null when missing (no column yet), null, or malformed. */
export function readTour(value: unknown): Tour | null {
  if (!value || typeof value !== 'object') return null
  const t = value as Partial<Tour>
  if (!Array.isArray(t.keyframes) || t.keyframes.length === 0 || typeof t.duration_ms !== 'number') return null
  const keyframes = [...t.keyframes].sort((a, b) => a.t_ms - b.t_ms)
  return { speed_up: 1, segments: [], models: {}, ...t, keyframes } as Tour
}

/** When the viewer should leave for keyframe `i`: the previous stop's arrival plus its dwell. */
export function departAt(tour: Tour, i: number): number {
  if (i <= 0) return 0
  const prev = tour.keyframes[i - 1]
  return Math.min(prev.t_ms + prev.dwell_ms, tour.keyframes[i].t_ms)
}

export interface TourState {
  /** The keyframe being travelled to or held at (-1 before the first departure). */
  index: number
  keyframe: TourKeyframe | null
  /** True while that keyframe is not covered by a scan: show the map. */
  inGap: boolean
  /** The latest instruction (a waypoint's caption and cue), kept through in-between sweeps. */
  caption: string
  cue: Cue | null
  progress: number
  done: boolean
}

/** Where the tour is at time `t` (ms). */
export function stateAt(tour: Tour, t: number): TourState {
  const ks = tour.keyframes
  let index = -1
  for (let i = 0; i < ks.length; i++) if (departAt(tour, i) <= t) index = i
  const keyframe = index >= 0 ? ks[index] : null
  let caption = ''
  let cue: Cue | null = null
  for (let i = index; i >= 0; i--) {
    if (ks[i].waypoint && ks[i].caption) { caption = ks[i].caption; cue = ks[i].cue; break }
  }
  return {
    index,
    keyframe,
    inGap: keyframe ? keyframe.kind === 'gap' : false,
    caption,
    cue,
    progress: tour.duration_ms > 0 ? Math.min(1, Math.max(0, t / tour.duration_ms)) : 1,
    done: t >= tour.duration_ms,
  }
}

/** What the viewer has to do to reach keyframe `i` on time. */
export interface Move {
  sweepId: string
  modelId: string
  bearing: number
  pitch: number
  transition: 'fly' | 'fade' | 'instant'
  /** Milliseconds the move should take so it arrives at `t_ms`. */
  duration: number
}

/** The viewer move for keyframe `i`, or null for a gap stop. Entering a scan from a gap is always a cut. */
export function moveFor(tour: Tour, i: number): Move | null {
  const k = tour.keyframes[i]
  if (!k || k.kind !== 'scanned' || !k.sweep_id || !k.model_id) return null
  const prev = tour.keyframes[i - 1]
  const fromGap = !prev || prev.kind === 'gap' || prev.model_id !== k.model_id
  const transition = fromGap || k.transition === 'fade' ? 'fade' : k.transition === 'fly' ? 'fly' : 'instant'
  return {
    sweepId: k.sweep_id,
    modelId: k.model_id,
    bearing: k.bearing_deg,
    pitch: k.pitch_deg,
    transition: i === 0 ? 'instant' : transition,
    duration: Math.max(300, k.t_ms - departAt(tour, i)),
  }
}

/** Plan position at time `t` during a gap stretch, interpolated between gap stops (for the map marker). */
export function gapPosition(tour: Tour, t: number): { x: number; y: number; floor: number } | null {
  const s = stateAt(tour, t)
  const k = s.keyframe
  if (!k || k.kind !== 'gap') return null
  const prev = tour.keyframes[s.index - 1]
  if (!prev || prev.kind !== 'gap' || prev.level !== k.level) return { x: k.position.x, y: k.position.y, floor: k.level }
  const start = departAt(tour, s.index)
  const f = k.t_ms > start ? Math.min(1, Math.max(0, (t - start) / (k.t_ms - start))) : 1
  return { x: prev.position.x + (k.position.x - prev.position.x) * f, y: prev.position.y + (k.position.y - prev.position.y) * f, floor: k.level }
}

/**
 * The scan plan's compass (0 = +y, clockwise) is not the viewer's yaw. The
 * viewer opens facing `models[id].bearing_deg`; read its yaw then and keep
 * the offset. `sign` is how yaw turns as the bearing grows clockwise: the SDK
 * uses a right-handed, y-up camera, where a positive yaw turns left, so -1.
 */
export const YAW_SIGN = -1

export function calibrate(openingBearing: number, openingYaw: number, sign = YAW_SIGN) {
  const offset = openingYaw - sign * openingBearing
  return (bearing: number) => wrap180(offset + sign * bearing)
}

/** An angle in degrees in (-180, 180]. */
export function wrap180(a: number): number {
  const r = ((a % 360) + 360) % 360
  return r > 180 ? r - 360 : r
}

/** A position in the viewer's frame (y up). */
export interface SdkPoint { x: number; y: number; z: number }

/** The scan's plan frame (z up, as the Model API reports it) in the viewer's frame (y up, -z is north). */
export const apiToSdk = (p: TourPoint): SdkPoint => ({ x: p.x, y: p.z, z: -p.y })

/**
 * The viewer yaw (degrees) that faces `to` from `from`. A y-up camera at yaw 0
 * looks down -z and a positive yaw turns left. `flip` is for a viewer whose
 * positive yaw turns right.
 */
export function yawToward(from: SdkPoint, to: SdkPoint, flip = false): number {
  const yaw = (Math.atan2(-(to.x - from.x), -(to.z - from.z)) * 180) / Math.PI
  return wrap180(flip ? -yaw : yaw)
}

/**
 * Which way yaw turns, read from the opening view: the viewer opens facing
 * `openingBearing` (plan compass, clockwise) at `openingYaw`. Returns true when
 * positive yaw turns right (then `yawToward` must flip). Ambiguous views keep
 * the documented convention.
 */
export function yawIsFlipped(openingBearing: number, openingYaw: number): boolean {
  const left = Math.abs(wrap180(openingYaw + openingBearing))
  const right = Math.abs(wrap180(openingYaw - openingBearing))
  return right + 5 < left
}

/**
 * Where the camera should look on arriving at keyframe `i`: toward the next
 * scanned stop (the direction of travel, like a video of someone walking), or
 * keep the previous heading at the last stop. `where` maps a sweep id to its
 * position in the viewer; null when a stop cannot be placed, so the caller
 * falls back to the plan's bearing.
 */
export function facingFor(
  tour: Tour, i: number, where: (sweepId: string) => SdkPoint | null, flip = false,
): number | null {
  const here = tour.keyframes[i]?.sweep_id
  const a = here ? where(here) : null
  if (!a) return null
  for (let j = i + 1; j < tour.keyframes.length; j++) {
    const k = tour.keyframes[j]
    if (k.kind !== 'scanned' || !k.sweep_id || k.model_id !== tour.keyframes[i].model_id) return facingBefore(tour, i, where, flip)
    const b = where(k.sweep_id)
    if (b && Math.hypot(b.x - a.x, b.z - a.z) > 0.05) return yawToward(a, b, flip)
  }
  return facingBefore(tour, i, where, flip)
}

/** At the last stop: face the way the previous hop was going. */
function facingBefore(tour: Tour, i: number, where: (id: string) => SdkPoint | null, flip: boolean): number | null {
  const a = tour.keyframes[i].sweep_id ? where(tour.keyframes[i].sweep_id!) : null
  for (let j = i - 1; a && j >= 0; j--) {
    const k = tour.keyframes[j]
    if (k.kind !== 'scanned' || !k.sweep_id || k.model_id !== tour.keyframes[i].model_id) return null
    const b = where(k.sweep_id)
    if (b && Math.hypot(a.x - b.x, a.z - b.z) > 0.05) return yawToward(b, a, flip)
  }
  return null
}

/**
 * Where the camera should look on arriving at keyframe `i` when the flight is meant to flow: halfway
 * between the way it came in and the way it leaves, so a corner is taken as a gradual turn over two hops
 * instead of a snap at the sweep. Straight stretches are unchanged; null when the stop cannot be placed.
 */
export function flowFacing(
  tour: Tour, i: number, where: (sweepId: string) => SdkPoint | null, flip = false,
): number | null {
  const out = facingFor(tour, i, where, flip)
  if (out === null) return null
  const into = facingBefore(tour, i, where, flip)
  return into === null ? out : wrap180(into + wrap180(out - into) / 2)
}

/** The viewer sweep id for a tour sweep: the same id if the viewer has it, else the nearest sweep within `maxM`. */
export function matchSweep(
  sweepId: string, planPos: TourPoint, viewer: Map<string, SdkPoint>, maxM = 1.5,
): string | null {
  if (viewer.has(sweepId)) return sweepId
  const want = apiToSdk(planPos)
  let best: string | null = null
  let bestD = maxM
  for (const [id, p] of viewer) {
    const d = Math.hypot(p.x - want.x, p.y - want.y, p.z - want.z)
    if (d <= bestD) { best = id; bestD = d }
  }
  return best
}

/**
 * A tour that opens inside the scan: the unscanned stops at the start (street,
 * lobby, lift) are cut and the clock starts at the first scanned stop. Their
 * captions are returned so the player can list them on a title card.
 */
export function startInScan(tour: Tour): { tour: Tour; skipped: string[] } {
  const first = tour.keyframes.findIndex((k) => k.kind === 'scanned')
  if (first <= 0) return { tour, skipped: [] }
  const t0 = tour.keyframes[first].t_ms
  const skipped = tour.keyframes.slice(0, first).filter((k) => k.waypoint && k.caption).map((k) => k.caption)
  const keyframes = tour.keyframes.slice(first).map((k) => ({ ...k, t_ms: k.t_ms - t0 }))
  // The first stop can carry the lift/stairs instruction that led here; keep its caption on screen.
  return { tour: { ...tour, keyframes, duration_ms: tour.duration_ms - t0 }, skipped }
}

/**
 * A tour for a camera that keeps moving: inside a scan the pause at each turn is dropped, so the viewer
 * flies hop after hop like a drone and only rests at the very end. Every hop keeps its length, so the
 * speed does not change. Map stretches (no scan) keep their pauses, and so does the final hold.
 */
export function smoothTour(tour: Tour): Tour {
  const ks = tour.keyframes
  let saved = 0
  const keyframes = ks.map((k, i) => {
    const next = ks[i + 1]
    const inScan = k.kind === 'scanned' && next?.kind === 'scanned' && next.model_id === k.model_id
    const moved = { ...k, t_ms: k.t_ms - saved, dwell_ms: inScan ? 0 : k.dwell_ms }
    if (inScan) saved += k.dwell_ms
    return moved
  })
  return { ...tour, keyframes, duration_ms: tour.duration_ms - saved }
}
