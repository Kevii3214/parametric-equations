import { describe, expect, it } from 'vitest'
import { routeGlance } from './briefing'
import { buildingById } from './buildings'
import { replanAround } from './replan'
import { scenarioFor } from './scenario'
import { moveCursor, type Cursor } from './stepCursor'

const start: Cursor = { key: 'r1', index: 0, lastLive: -1 }

describe('step cursor', () => {
  it('moves with Next and Back and stays within the route', () => {
    let c = moveCursor(start, { type: 'back' }, 7)
    expect(c.index).toBe(0)
    for (let i = 0; i < 10; i++) c = moveCursor(c, { type: 'next' }, 7)
    expect(c.index).toBe(6)
    expect(moveCursor(c, { type: 'back' }, 7).index).toBe(5)
  })
  it('follows a live position forward, but Back is not undone by the same report', () => {
    let c = moveCursor(start, { type: 'live', step: 3 }, 7)
    expect(c.index).toBe(3)
    c = moveCursor(c, { type: 'back' }, 7)
    c = moveCursor(c, { type: 'live', step: 3 }, 7)
    expect(c.index).toBe(2)
    expect(moveCursor(c, { type: 'live', step: 4 }, 7).index).toBe(4)
  })
  it('starts again at step 0 on a new route', () => {
    const c = moveCursor({ key: 'r1', index: 4, lastLive: 4 }, { type: 'route', key: 'r2' }, 7)
    expect(c).toEqual({ key: 'r2', index: 0, lastLive: -1 })
  })
})

describe('briefing', () => {
  const { route } = scenarioFor('233928')
  it('sums up the route', () => {
    const g = routeGlance(route.steps)
    expect(g.seconds).toBe(route.total_seconds)
    expect(g.climb).toBe('elevator')
    expect(g.floors).toContain(18)
  })
})

describe('demo re-plan', () => {
  const { route } = scenarioFor('233928')
  const graph = buildingById('233928')!.graph
  it('elevator out sends 1415 Louisiana up the stairs', () => {
    const r = replanAround(graph, route.steps, 0, 'elevator_out')!
    expect(r).not.toBeNull()
    expect(r.steps.some((s) => /stairs/i.test(s.text))).toBe(true)
    expect(r.steps.reduce((t, s) => t + s.seconds, 0)).toBeGreaterThan(route.total_seconds)
  })
  it('returns null when there is no elevator left to close', () => {
    const last = route.steps.length - 1
    expect(replanAround(graph, route.steps, last, 'elevator_out')).toBeNull()
  })
})
