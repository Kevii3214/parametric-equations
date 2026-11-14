import { describe, expect, it } from 'vitest'
import la from '../../../fixtures/buildings/233928/tour_sample.json'
import wt from '../../../fixtures/buildings/233903/tour_sample.json'
import jr from '../../../fixtures/buildings/jrr/tour_sample.json'
import {
  apiToSdk, calibrate, departAt, facingFor, gapPosition, matchSweep, moveFor, readTour, startInScan, stateAt, wrap180, yawIsFlipped, yawToward,
  type SdkPoint, type Tour,
} from './tour'

const tours = { '233928': readTour(la)!, '233903': readTour(wt)!, jrr: readTour(jr)! } as Record<string, Tour>

describe('readTour', () => {
  it('accepts the three sample tours', () => {
    for (const t of Object.values(tours)) expect(t.keyframes.length).toBeGreaterThan(3)
  })
  it('rejects a missing, null or empty tour so the app falls back to the route view', () => {
    expect(readTour(undefined)).toBeNull()
    expect(readTour(null)).toBeNull()
    expect(readTour({ keyframes: [], duration_ms: 0 })).toBeNull()
  })
})

describe.each(Object.entries(tours))('timing for %s', (_id, tour) => {
  it('arrives at every stop at its t_ms: departs after the previous stop and its dwell', () => {
    for (let i = 1; i < tour.keyframes.length; i++) {
      const prev = tour.keyframes[i - 1]
      expect(departAt(tour, i)).toBe(Math.min(prev.t_ms + prev.dwell_ms, tour.keyframes[i].t_ms))
      expect(stateAt(tour, tour.keyframes[i].t_ms).index).toBeGreaterThanOrEqual(i)
    }
  })
  it('ends at the last stop, with its dwell, at duration_ms', () => {
    const last = tour.keyframes.at(-1)!
    expect(tour.duration_ms).toBe(last.t_ms + last.dwell_ms)
    expect(stateAt(tour, tour.duration_ms).done).toBe(true)
    expect(stateAt(tour, tour.duration_ms).cue).toBe('ARRIVE')
  })
  it('keeps the last waypoint caption through in-between sweeps', () => {
    for (const k of tour.keyframes) {
      const s = stateAt(tour, k.t_ms)
      if (!k.waypoint) expect(s.caption).not.toBe('')
    }
  })
  it('never gives a move for a gap stop, and always moves to a sweep for a scanned one', () => {
    tour.keyframes.forEach((k, i) => {
      const m = moveFor(tour, i)
      if (k.kind === 'gap') expect(m).toBeNull()
      else expect(m?.sweepId).toBe(k.sweep_id)
    })
  })
})

describe('gap handling', () => {
  it.each(['233928', '233903'])('%s shows the map first, then cuts into the scan', (id) => {
    const tour = tours[id]
    expect(stateAt(tour, 0).inGap).toBe(true)
    const firstScan = tour.keyframes.findIndex((k) => k.kind === 'scanned')
    expect(firstScan).toBeGreaterThan(0)
    expect(stateAt(tour, departAt(tour, firstScan)).inGap).toBe(false)
    expect(moveFor(tour, firstScan)!.transition).toBe('fade')
    // The map marker moves along the gap stretch.
    expect(gapPosition(tour, 1000)).not.toBeNull()
  })

  it('Rabinowitz Hall is one continuous fly-through with a fade cut at the stairs, about 29 s', () => {
    const tour = tours.jrr
    expect(tour.keyframes.every((k) => k.kind === 'scanned')).toBe(true)
    expect(tour.duration_ms).toBeGreaterThan(20000)
    expect(tour.duration_ms).toBeLessThan(35000)
    const stairs = tour.keyframes.findIndex((k) => k.cue === 'FLOOR_UP')
    expect(moveFor(tour, stairs)!.transition).toBe('fade')
    const flights = tour.keyframes.map((_, i) => moveFor(tour, i)!.transition)
    expect(flights.filter((t) => t === 'fly').length).toBeGreaterThan(4)
  })
})

describe('compass calibration', () => {
  it('maps the opening bearing to the opening yaw, and turns the other way as the bearing grows', () => {
    const yaw = calibrate(55.5, 10)
    expect(yaw(55.5)).toBeCloseTo(10)
    expect(yaw(65.5)).toBeCloseTo(0)
    expect(yaw(55.5 + 360)).toBeCloseTo(10)
  })
  it('wraps into (-180, 180]', () => {
    expect(wrap180(190)).toBe(-170)
    expect(wrap180(-190)).toBe(170)
    expect(wrap180(180)).toBe(180)
  })
})

describe('demo routes carry the matching sample tour', () => {
  it.each(['233928', '233903', 'jrr'])('%s: the tour follows the demo route step by step', async (id) => {
    const { scenarioFor } = await import('./scenario')
    const { route } = scenarioFor(id)
    const tour = readTour(route.tour)!
    expect(tour).not.toBeNull()
    for (const k of tour.keyframes.filter((k) => k.step_index >= 0)) {
      const step = route.steps[k.step_index]
      expect(step, `step ${k.step_index}`).toBeDefined()
      expect([step.from_node, step.to_node]).toContain(k.node)
    }
  })
})

describe('walking direction', () => {
  const o = { x: 0, y: 0, z: 0 }
  it('faces each compass direction (y up, yaw 0 looks down -z, positive yaw turns left)', () => {
    expect(yawToward(o, { x: 0, y: 0, z: -1 })).toBeCloseTo(0)
    expect(yawToward(o, { x: -1, y: 0, z: 0 })).toBeCloseTo(90)
    expect(Math.abs(yawToward(o, { x: 0, y: 0, z: 1 }))).toBeCloseTo(180)
    expect(yawToward(o, { x: 1, y: 0, z: 0 })).toBeCloseTo(-90)
    expect(yawToward(o, { x: -1, y: 0, z: 0 }, true)).toBeCloseTo(-90)
  })
  it('maps the plan frame to the viewer frame so a plan bearing and a viewer yaw agree', () => {
    // plan bearing 90 (east, +x) is yaw -90 in the viewer
    const east = apiToSdk({ x: 1, y: 0, z: 0 })
    expect(yawToward(apiToSdk({ x: 0, y: 0, z: 0 }), east)).toBeCloseTo(-90)
    // plan bearing 0 (+y, north) is yaw 0
    expect(yawToward(apiToSdk({ x: 0, y: 0, z: 0 }), apiToSdk({ x: 0, y: 1, z: 0 }))).toBeCloseTo(0)
  })
  it('reads which way yaw turns from the opening view', () => {
    expect(yawIsFlipped(90, -90)).toBe(false)
    expect(yawIsFlipped(90, 90)).toBe(true)
    expect(yawIsFlipped(0, 0)).toBe(false)
  })
  it('faces the next scanned stop, and keeps the last heading at the end', () => {
    for (const tour of Object.values(tours)) {
      const pos = new Map<string, SdkPoint>()
      for (const k of tour.keyframes) if (k.sweep_id) pos.set(k.sweep_id, apiToSdk(k.position))
      const where = (id: string) => pos.get(id) ?? null
      const scanned = tour.keyframes.map((k, i) => [k, i] as const).filter(([k]) => k.kind === 'scanned')
      for (const [, i] of scanned) expect(facingFor(tour, i, where)).not.toBeNull()
      expect(facingFor(tour, scanned[0][1], () => null)).toBeNull()
    }
  })
})

describe('matchSweep', () => {
  const viewer = new Map<string, SdkPoint>([['a', { x: 1, y: 0, z: -2 }], ['b', { x: 9, y: 0, z: 9 }]])
  it('uses the same id when the viewer has it', () => expect(matchSweep('b', { x: 0, y: 0, z: 0 }, viewer)).toBe('b'))
  it('falls back to the nearest sweep within range, else nothing', () => {
    expect(matchSweep('zz', { x: 1.2, y: 2.1, z: 0 }, viewer)).toBe('a')
    expect(matchSweep('zz', { x: 40, y: 40, z: 0 }, viewer)).toBeNull()
  })
})

describe('startInScan', () => {
  it('cuts the unscanned opening of the Houston tours and starts the clock in the scan', () => {
    for (const id of ['233928', '233903']) {
      const { tour, skipped } = startInScan(tours[id])
      expect(skipped.length).toBeGreaterThan(0)
      expect(tour.keyframes[0].kind).toBe('scanned')
      expect(tour.keyframes[0].t_ms).toBe(0)
      expect(tour.keyframes.every((k) => k.kind === 'scanned')).toBe(true)
      expect(tour.duration_ms).toBeLessThan(tours[id].duration_ms)
      const last = tour.keyframes.at(-1)!
      expect(tour.duration_ms).toBe(last.t_ms + last.dwell_ms)
      expect(stateAt(tour, 0).inGap).toBe(false)
    }
  })
  it('leaves a fully scanned tour alone', () => {
    const { tour, skipped } = startInScan(tours.jrr)
    expect(tour).toBe(tours.jrr)
    expect(skipped).toEqual([])
  })
})
