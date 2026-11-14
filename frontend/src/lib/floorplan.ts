// Floor layouts from the Matterport scans (fixtures/buildings/<id>/interior.json):
// rooms, walls with their thickness, and doorway gaps, in the scan's metres.
// The route graph for a scanned floor uses the same frame, so the route can
// be traced over the walls. Pure: tested without the DOM.

export type XY = [number, number]

export interface Wall { a: XY; b: XY; thickness: number }
export interface Doorway { a: XY; b: XY }
export interface Room { id: string; name: string; isVoid: boolean; ring: XY[]; centre: XY }
export interface Plan { walls: Wall[]; doorways: Doorway[]; rooms: Room[] }

interface RawVertex { id?: string; position: { x: number; y: number } }
interface RawOpening { type?: string; width?: number; relativeCenter?: number }
interface RawEdge { type?: string; thickness?: number; openings?: RawOpening[]; vertices: RawVertex[] }
interface RawRoom {
  id: string
  label?: string
  classifications?: { label: string }[]
  floor?: { label?: string } | null
  boundary: { edges: RawEdge[] }
}
interface RawModel { id: string; rooms: RawRoom[] }

const lerp = (a: XY, b: XY, f: number): XY => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]

/** The layout of one scanned floor, or null if the model or floor is missing. */
export function planFor(interior: unknown, modelId: string, scanFloor?: string): Plan | null {
  const models = (interior as { models?: RawModel[] } | null)?.models
  const model = models?.find((m) => m.id === modelId)
  if (!model) return null
  const rooms = model.rooms.filter((r) => !scanFloor || !r.floor?.label || r.floor.label === scanFloor)
  if (!rooms.length) return null
  const plan: Plan = { walls: [], doorways: [], rooms: [] }
  for (const r of rooms) {
    for (const e of r.boundary.edges) {
      const vs = e.vertices.map((v) => [v.position.x, v.position.y] as XY)
      for (let i = 0; i + 1 < vs.length; i++) splitWall(vs[i], vs[i + 1], e, plan)
    }
    const ring = chainRing(r.boundary.edges)
    const classes = (r.classifications ?? []).map((c) => c.label)
    const isVoid = classes.includes('Void')
    // Label at the outline's centre, or the corners' average when the outline does not close.
    const pts: XY[] = ring.length ? ring : r.boundary.edges.flatMap((e) => e.vertices.map((v) => [v.position.x, v.position.y] as XY))
    const centre: XY = [pts.reduce((t, p) => t + p[0], 0) / pts.length, pts.reduce((t, p) => t + p[1], 0) / pts.length]
    plan.rooms.push({ id: r.id, name: isVoid ? '' : (r.label || classes[0] || ''), isVoid, ring, centre })
  }
  return plan
}

/**
 * A room's outline in order. The scan stores a room's edges unordered, but
 * neighbouring edges share vertex ids, so walk from edge to edge. Returns an
 * empty ring when the edges do not close up.
 */
export function chainRing(edges: RawEdge[]): XY[] {
  const usable = edges.filter((e) => e.vertices.length >= 2 && e.vertices.every((v) => v.id))
  if (usable.length < 3) return []
  const pos = new Map<string, XY>()
  const next = new Map<string, string[]>()
  for (const e of usable) {
    const ids = e.vertices.map((v) => { pos.set(v.id!, [v.position.x, v.position.y]); return v.id! })
    for (let i = 0; i + 1 < ids.length; i++) {
      next.set(ids[i], [...(next.get(ids[i]) ?? []), ids[i + 1]])
      next.set(ids[i + 1], [...(next.get(ids[i + 1]) ?? []), ids[i]])
    }
  }
  const start = usable[0].vertices[0].id!
  const ring: string[] = [start]
  let prev = '', at = start
  for (let guard = 0; guard < pos.size + 1; guard++) {
    const to = (next.get(at) ?? []).find((n) => n !== prev && (n === start ? ring.length > 2 : !ring.includes(n)))
    if (!to) return []
    if (to === start) return ring.map((id) => pos.get(id)!)
    ring.push(to); prev = at; at = to
  }
  return []
}

/** A wall edge, cut where its doorways are (relativeCenter is the fraction along the edge). */
function splitWall(a: XY, b: XY, e: RawEdge, plan: Plan) {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1])
  const thickness = e.thickness ?? 0.15
  const gaps = (e.openings ?? [])
    .filter((o) => o.width && o.relativeCenter != null && len > 0)
    .map((o) => [o.relativeCenter! - o.width! / 2 / len, o.relativeCenter! + o.width! / 2 / len] as XY)
    .map(([s, t]) => [Math.max(0, s), Math.min(1, t)] as XY)
    .sort((x, y) => x[0] - y[0])
  let at = 0
  for (const [s, t] of gaps) {
    if (s > at) plan.walls.push({ a: lerp(a, b, at), b: lerp(a, b, s), thickness })
    plan.doorways.push({ a: lerp(a, b, s), b: lerp(a, b, t) })
    at = Math.max(at, t)
  }
  if (at < 1) plan.walls.push({ a: lerp(a, b, at), b, thickness })
}

/** Bounding box of a plan's walls plus extra points, padded. */
export function bounds(plan: Plan | null, extra: XY[], pad = 2): { x0: number; y0: number; x1: number; y1: number } {
  const pts: XY[] = [...extra, ...(plan?.walls.flatMap((w) => [w.a, w.b]) ?? [])]
  if (!pts.length) return { x0: -10, y0: -10, x1: 10, y1: 10 }
  const xs = pts.map((p) => p[0])
  const ys = pts.map((p) => p[1])
  return { x0: Math.min(...xs) - pad, y0: Math.min(...ys) - pad, x1: Math.max(...xs) + pad, y1: Math.max(...ys) + pad }
}
