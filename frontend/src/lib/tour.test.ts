import { describe, expect, it } from 'vitest'
import la from '../../../fixtures/buildings/233928/tour_sample.json'
import wt from '../../../fixtures/buildings/233903/tour_sample.json'
import jr from '../../../fixtures/buildings/jrr/tour_sample.json'
import { calibrate, departAt, gapPosition, moveFor, readTour, stateAt, wrap180, type Tour } from './tour'

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

  it('Rabinowitz Hall is one continuous fly-through with a fade cut at the stairs, about 17 s', () => {
    const tour = tours.jrr
    expect(tour.keyframes.every((k) => k.kind === 'scanned')).toBe(true)
    expect(tour.duration_ms).toBeGreaterThan(15000)
    expect(tour.duration_ms).toBeLessThan(19000)
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
