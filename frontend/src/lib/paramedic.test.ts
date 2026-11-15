import { describe, expect, it } from 'vitest'
import { routeGlance } from './briefing'
import { buildingById } from './buildings'
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


describe('floor plans from the scans', () => {
  it.each([['233928', 18], ['233903', 56], ['jrr', 2], ['jrr', 3]] as const)('%s floor %i has walls, doorways and rooms', async (id, floor) => {
    const { planFor } = await import('./floorplan')
    const b = buildingById(id)!
    const src = b.floorPlans![floor]
    const plan = planFor(await b.loadInterior!(), src.modelId, src.scanFloor)!
    expect(plan.walls.length).toBeGreaterThan(5)
    expect(plan.rooms.length).toBeGreaterThan(1)
    expect(plan.doorways.length).toBeGreaterThan(0)
  })
  it('returns null for a model that is not in the file', async () => {
    const { planFor } = await import('./floorplan')
    expect(planFor(await buildingById('233928')!.loadInterior!(), 'nope')).toBeNull()
  })
})

describe('room outlines', () => {
  it('chains the scan edges into closed rings for most rooms', async () => {
    const { planFor } = await import('./floorplan')
    const b = buildingById('233903')!
    const plan = planFor(await b.loadInterior!(), 'eJKnR3x44eh')!
    const closed = plan.rooms.filter((r) => r.ring.length > 2).length
    expect(closed / plan.rooms.length).toBeGreaterThan(0.8)
  })
})
