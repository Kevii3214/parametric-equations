import { describe, expect, it } from 'vitest'
import { buildingById } from './buildings'
import { placeGraph } from './geo3d'

const metres = (a: [number, number], b: [number, number]) =>
  Math.hypot((a[0] - b[0]) * 111_320 * Math.cos((a[1] * Math.PI) / 180), (a[1] - b[1]) * 111_320)

describe.each(['233928', '233903'])('placeGraph for building %s', (id) => {
  const b = buildingById(id)!
  const p = placeGraph(b)

  it('puts each ground-floor entrance on its map pin', () => {
    for (const m of b.markers) expect(metres(p.node(m.node)!, m.at)).toBeLessThan(0.5)
  })

  it('keeps the elevator shaft vertical across floors', () => {
    const lifts = b.graph.nodes.filter((n) => n.kind === 'elevator')
    expect(lifts.length).toBeGreaterThan(1)
    for (const l of lifts.slice(1)) expect(metres(p.node(l.id)!, p.node(lifts[0].id)!)).toBeLessThan(0.5)
  })

  it('fits the ground floor at a sane scale and keeps every node near the building', () => {
    const centre: [number, number] = [b.record.longitude, b.record.latitude]
    for (const n of b.graph.nodes) expect(metres(p.node(n.id)!, centre)).toBeLessThan(150)
  })
})

describe('routeFeatures', () => {
  it.each(['233928', '233903'])('builds one shape per step, with the shaft rising to the patient floor (%s)', async (id) => {
    const { routeFeatures } = await import('./geo3d')
    const { scenarioFor } = await import('./scenario')
    const b = buildingById(id)!
    const p = placeGraph(b)
    const nodes = new Map(b.graph.nodes.map((n) => [n.id, n]))
    const { route } = scenarioFor(id)
    const storey = 4
    const fc = routeFeatures(p, nodes, route.steps, storey, 2)
    expect(fc.features).toHaveLength(route.steps.length)
    const shaft = fc.features.find((f) => f.properties.kind === 'shaft')!
    const top = Math.max(...b.graph.nodes.map((n) => n.floor))
    expect(shaft.properties.base).toBe(0)
    expect(shaft.properties.top).toBeGreaterThan((top - 1) * storey)
    expect(fc.features.filter((f) => f.properties.done === 1)).toHaveLength(2)
  })
})
