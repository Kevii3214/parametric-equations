// Place a building's interior graph (metres on each floor's own plan) onto
// the map, so the route can be drawn in 3D. This is approximate by design:
// - Ground floor: a similarity transform fitted to the entrance pins (their
//   graph positions and their map positions), which fixes scale and rotation.
// - Upper floors: same rotation at true scale (those plans are measured or
//   drawn in metres), lined up so each floor's elevator sits over the ground
//   floor's elevator, i.e. the shaft is vertical.
import type { Building, LngLat } from './buildings'
import type { GraphNode, RouteStep } from './contracts'

const M_PER_DEG = 111_320

export interface Placer {
  /** Map position of a point on a floor's plan. */
  at(x: number, y: number, floor: number): LngLat
  node(id: string): LngLat | null
  groundFloor: number
}

export function placeGraph(b: Building): Placer {
  const nodes = new Map(b.graph.nodes.map((n) => [n.id, n]))
  const ground = Math.min(...b.graph.nodes.map((n) => n.floor))
  const origin = b.markers[0]?.at ?? [b.record.longitude, b.record.latitude]
  const mPerLng = M_PER_DEG * Math.cos((origin[1] * Math.PI) / 180)
  const toLocal = ([lng, lat]: LngLat): [number, number] => [(lng - origin[0]) * mPerLng, (lat - origin[1]) * M_PER_DEG]
  const toLngLat = ([e, n]: [number, number]): LngLat => [origin[0] + e / mPerLng, origin[1] + n / M_PER_DEG]

  // Anchors: entrance pins whose node is on the ground floor.
  const anchors = b.markers
    .map((m) => ({ g: nodes.get(m.node), m: toLocal(m.at) }))
    .filter((a): a is { g: GraphNode; m: [number, number] } => !!a.g && a.g.floor === ground)

  let scale = 1
  let theta = 0
  let gA: [number, number] = [0, 0]
  let mA: [number, number] = [0, 0]
  if (anchors.length >= 1) {
    gA = [anchors[0].g.x, anchors[0].g.y]
    mA = anchors[0].m
  }
  // One anchor: rotation comes from the building (compass), at true scale.
  if (anchors.length < 2 && b.graphRotationDeg) theta = (-b.graphRotationDeg * Math.PI) / 180
  if (anchors.length >= 2) {
    const gv = [anchors[1].g.x - gA[0], anchors[1].g.y - gA[1]]
    const mv = [anchors[1].m[0] - mA[0], anchors[1].m[1] - mA[1]]
    const gl = Math.hypot(gv[0], gv[1])
    if (gl > 0) {
      scale = Math.hypot(mv[0], mv[1]) / gl
      theta = Math.atan2(mv[1], mv[0]) - Math.atan2(gv[1], gv[0])
    }
  }
  const rot = ([x, y]: [number, number], k: number): [number, number] =>
    [k * (x * Math.cos(theta) - y * Math.sin(theta)), k * (x * Math.sin(theta) + y * Math.cos(theta))]
  const groundLocal = (x: number, y: number): [number, number] => {
    const [dx, dy] = rot([x - gA[0], y - gA[1]], scale)
    return [mA[0] + dx, mA[1] + dy]
  }

  // Each upper floor hangs off its own elevator (or stairs) over the ground one.
  const shaftOn = (floor: number) =>
    b.graph.nodes.find((n) => n.floor === floor && n.kind === 'elevator')
    ?? b.graph.nodes.find((n) => n.floor === floor && n.kind === 'stairs')
  const groundShaft = shaftOn(ground)

  const at = (x: number, y: number, floor: number): LngLat => {
    if (floor === ground) return toLngLat(groundLocal(x, y))
    const s = shaftOn(floor)
    if (!s || !groundShaft) return toLngLat(groundLocal(x, y))
    const base = groundLocal(groundShaft.x, groundShaft.y)
    const [dx, dy] = rot([x - s.x, y - s.y], 1)
    return toLngLat([base[0] + dx, base[1] + dy])
  }

  return {
    at,
    node: (id) => {
      const n = nodes.get(id)
      return n ? at(n.x, n.y, n.floor) : null
    },
    groundFloor: ground,
  }
}

/** A flat rectangle `w` metres wide along a→b, as a closed ring. */
export function ribbon(a: LngLat, b: LngLat, w: number): LngLat[] {
  const mPerLng = M_PER_DEG * Math.cos((a[1] * Math.PI) / 180)
  const dx = (b[0] - a[0]) * mPerLng
  const dy = (b[1] - a[1]) * M_PER_DEG
  const len = Math.hypot(dx, dy) || 1
  const ox = (-dy / len) * (w / 2) / mPerLng
  const oy = (dx / len) * (w / 2) / M_PER_DEG
  // Extend each end by half a width so consecutive segments join cleanly.
  const ex = (dx / len) * (w / 2) / mPerLng
  const ey = (dy / len) * (w / 2) / M_PER_DEG
  const a2: LngLat = [a[0] - ex, a[1] - ey]
  const b2: LngLat = [b[0] + ex, b[1] + ey]
  return [[a2[0] + ox, a2[1] + oy], [b2[0] + ox, b2[1] + oy], [b2[0] - ox, b2[1] - oy], [a2[0] - ox, a2[1] - oy], [a2[0] + ox, a2[1] + oy]]
}

/** A square `w` metres across centred on a point, as a closed ring. */
export function square(c: LngLat, w: number): LngLat[] {
  const h = w / 2
  const dLng = h / (M_PER_DEG * Math.cos((c[1] * Math.PI) / 180))
  const dLat = h / M_PER_DEG
  return [[c[0] - dLng, c[1] - dLat], [c[0] + dLng, c[1] - dLat], [c[0] + dLng, c[1] + dLat], [c[0] - dLng, c[1] + dLat], [c[0] - dLng, c[1] - dLat]]
}

/** Compass bearing (degrees) from a to b. */
export function bearing(a: LngLat, b: LngLat): number {
  const dx = (b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180)
  const dy = b[1] - a[1]
  return ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360
}

type Feature = { type: 'Feature'; properties: Record<string, number | string>; geometry: { type: 'Polygon'; coordinates: LngLat[][] } }

/**
 * The route as 3D shapes: a ribbon per walk segment at its floor's height and
 * a shaft for each floor change. `storey` is metres per floor.
 */
export function routeFeatures(p: Placer, nodes: Map<string, GraphNode>, steps: RouteStep[], storey: number, currentStep: number) {
  const features: Feature[] = []
  const alt = (floor: number) => (floor - p.groundFloor) * storey
  for (const s of steps) {
    const a = nodes.get(s.from_node)
    const b = nodes.get(s.to_node)
    if (!a || !b) continue
    const done = s.index < currentStep ? 1 : 0
    if (a.floor === b.floor) {
      const base = alt(a.floor) + 0.3
      features.push({ type: 'Feature', properties: { base, top: base + 1.1, done, kind: 'walk' },
        geometry: { type: 'Polygon', coordinates: [ribbon(p.at(a.x, a.y, a.floor), p.at(b.x, b.y, b.floor), 1.6)] } })
    } else {
      const lo = Math.min(alt(a.floor), alt(b.floor))
      const hi = Math.max(alt(a.floor), alt(b.floor))
      features.push({ type: 'Feature', properties: { base: lo, top: hi + 1.4, done, kind: 'shaft' },
        geometry: { type: 'Polygon', coordinates: [square(p.at(a.x, a.y, a.floor), 2.4)] } })
    }
  }
  return { type: 'FeatureCollection' as const, features }
}
