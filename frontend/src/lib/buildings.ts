// Real data for the demo buildings, from fixtures/buildings/<id>/ (CoStar
// record, Vexcel imagery, Matterport models, interior graph). Read-only.
import laAerial from '../../../fixtures/buildings/233928/aerial.json'
import laOrtho from '../../../fixtures/buildings/233928/aerial.jpg'
import laGraph from '../../../fixtures/buildings/233928/graph.json'
import laEast from '../../../fixtures/buildings/233928/oblique-east.jpg'
import laNorth from '../../../fixtures/buildings/233928/oblique-north.jpg'
import laSouth from '../../../fixtures/buildings/233928/oblique-south.jpg'
import laWest from '../../../fixtures/buildings/233928/oblique-west.jpg'
import laRecord from '../../../fixtures/buildings/233928/record.json'
import wtAerial from '../../../fixtures/buildings/233903/aerial.json'
import wtOrtho from '../../../fixtures/buildings/233903/aerial.jpg'
import wtGraph from '../../../fixtures/buildings/233903/graph.json'
import wtEast from '../../../fixtures/buildings/233903/oblique-east.jpg'
import wtNorth from '../../../fixtures/buildings/233903/oblique-north.jpg'
import wtSouth from '../../../fixtures/buildings/233903/oblique-south.jpg'
import wtWest from '../../../fixtures/buildings/233903/oblique-west.jpg'
import wtRecord from '../../../fixtures/buildings/233903/record.json'
import jrAerial from '../../../fixtures/buildings/jrr/aerial.json'
import jrOrtho from '../../../fixtures/buildings/jrr/aerial.jpg'
import jrGraph from '../../../fixtures/buildings/jrr/graph.json'
import jrEast from '../../../fixtures/buildings/jrr/oblique-east.jpg'
import jrNorth from '../../../fixtures/buildings/jrr/oblique-north.jpg'
import jrSouth from '../../../fixtures/buildings/jrr/oblique-south.jpg'
import jrWest from '../../../fixtures/buildings/jrr/oblique-west.jpg'
import jrRecord from '../../../fixtures/buildings/jrr/record.json'
import buildingIndex from '../../../fixtures/buildings/index.json'
import type { BuildingGraph } from './contracts'

export type LngLat = [number, number]

export interface CostarRecord {
  building_id: string
  name: string
  address: string
  city: string
  state: string
  postcode: string
  latitude: number
  longitude: number
  property_type: string
  /** Missing for buildings that are not in the CoStar kit (record written by hand). */
  source?: string
  building_class?: number | null
  building_rating?: number | null
  stories_above_grade: number | null
  gross_area_sqft?: number | null
  typical_floor_sqft?: number | null
  data_quality_notes: string[]
  elevators: { type: string; count: number | null; exists: boolean }[]
  parking: { type: string; spaces: number | null; monthly_fee: number | null }[]
  matterport_model_ids: string[]
  current_tenants: { suite: string | null; floor_guess_from_suite: number | null; company: string | null }[]
}

export type Direction = 'north' | 'east' | 'south' | 'west'

export interface MatterportModel {
  id: string
  title: string
  subtitle: string
  destination?: boolean
}

export interface SiteMarker {
  node: string
  label: string
  at: LngLat
  /** Placed by eye from the imagery, not measured. */
  estimated: boolean
  /** Which side of the building the door faces, when known better than the pin's offset says. */
  side?: Direction
}

export interface Building {
  id: string
  record: CostarRecord
  graph: BuildingGraph
  ortho: string
  obliques: Record<Direction, string>
  obliqueCaptured: string | null
  /** What to look for in an oblique, checked by eye (e.g. a neighbour in front). */
  obliqueNotes: Partial<Record<Direction, string>>
  /** CSS object-position that frames this building in an oblique. */
  obliqueFocus: Partial<Record<Direction, string>>
  collection: string
  parcel: LngLat[]
  /** Lon/lat box the ortho image covers: the parcel's bounding box plus 10 m, padded square. */
  orthoBounds: { west: number; east: number; south: number; north: number }
  /**
   * False when the Vexcel parcel (and so the ortho, obliques and parcel
   * outline) is a different building from the CoStar record. The UI then
   * hides that imagery and shows `imageryNote` instead.
   */
  imageryMatches: boolean
  imageryNote?: string
  markers: SiteMarker[]
  matterport: MatterportModel[]
  /** The default patient node for the demo replay. */
  demoGoal?: string
  /**
   * With a single entrance pin the plan's rotation can't be fitted, so give
   * it: degrees clockwise from the plan's +y axis to true north.
   */
  graphRotationDeg?: number
}

function parseWkt(wkt: string): LngLat[] {
  const inner = wkt.match(/\(\(\((.*?)\)\)\)/)?.[1] ?? ''
  return inner.split(',').map((p) => p.trim().split(/\s+/).map(Number) as LngLat)
}

/**
 * The ortho request was the parcel's bounding box plus a 10 m buffer, and
 * Vexcel returns a square image: the box is padded to a square around its
 * centre (cars come out the right shape only with padding, not stretching).
 */
function orthoBoundsFor(ring: LngLat[], metres: number) {
  const lats = ring.map((p) => p[1])
  const lngs = ring.map((p) => p[0])
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2
  const mPerLng = 111_320 * Math.cos((midLat * Math.PI) / 180)
  const w = (Math.max(...lngs) - Math.min(...lngs)) * mPerLng + 2 * metres
  const h = (Math.max(...lats) - Math.min(...lats)) * 111_320 + 2 * metres
  const half = Math.max(w, h) / 2
  const cx = (Math.max(...lngs) + Math.min(...lngs)) / 2
  const cy = (Math.max(...lats) + Math.min(...lats)) / 2
  return { west: cx - half / mPerLng, east: cx + half / mPerLng, south: cy - half / 111_320, north: cy + half / 111_320 }
}

/** Pixel fraction (0..1) on the ortho image for a lon/lat. */
export function orthoXY(b: Building, [lng, lat]: LngLat): [number, number] {
  const o = b.orthoBounds
  return [(lng - o.west) / (o.east - o.west), (o.north - lat) / (o.north - o.south)]
}

/** Lon/lat for a pixel fraction on an ortho image. */
function fromOrtho(o: Building['orthoBounds'], fx: number, fy: number): LngLat {
  return [o.west + fx * (o.east - o.west), o.north - fy * (o.north - o.south)]
}

/** A point `east`/`north` metres from a lon/lat. */
function offset([lng, lat]: LngLat, east: number, north: number): LngLat {
  return [lng + east / (111_320 * Math.cos((lat * Math.PI) / 180)), lat + north / 111_320]
}

const laParcel = parseWkt(laAerial.parcel_wkt)
const laBounds = orthoBoundsFor(laParcel, 10)
const wtParcel = parseWkt(wtAerial.parcel_wkt)
const wtRec = wtRecord as CostarRecord
// Williams Tower's centre in the OpenStreetMap footprint (the CoStar point is inside it).
const wtCentre: LngLat = [-95.46134, 29.73727]

const louisiana: Building = {
  id: '233928',
  record: laRecord as CostarRecord,
  graph: laGraph as BuildingGraph,
  ortho: laOrtho,
  obliques: { north: laNorth, east: laEast, south: laSouth, west: laWest },
  obliqueCaptured: laAerial.images['oblique-north']?.captured ?? null,
  obliqueNotes: {
    east: 'The rounded glass tower in front is a neighbour. 1415 Louisiana is the dark brown tower behind it, on the left.',
  },
  obliqueFocus: { east: '22% 55%' },
  collection: laAerial.collection,
  parcel: laParcel,
  orthoBounds: laBounds,
  imageryMatches: true,
  demoGoal: 'phone_door',
  // The graph's entrance positions are estimates (see GRAPH_NOTES.md); these
  // map pins are placed by eye on the Vexcel ortho to match.
  markers: [
    { node: 'st_main', label: 'Louisiana St main entrance', at: fromOrtho(laBounds, 0.69, 0.66), estimated: true },
    { node: 'gar1', label: 'Parking garage lobby', at: fromOrtho(laBounds, 0.3, 0.44), estimated: true },
  ],
  matterport: [
    { id: 'LJn59uoV759', title: 'Regus Suite 1800', subtitle: 'Reception and phone room, floor 18', destination: true },
    { id: 'tMswvfbZK8C', title: 'Suite 2350', subtitle: '5,914 sq ft, floor 23' },
    { id: 'qgHrw7d3MJ1', title: 'Corner office', subtitle: 'Typical office floor' },
    { id: 'vh1XhRJyZPW', title: 'Interior office', subtitle: 'Typical office floor' },
    { id: 'yPnykGhkJf6', title: 'Conference room', subtitle: 'Typical office floor' },
    { id: 'sEmBqaiPBba', title: 'Strato', subtitle: 'Tenant space' },
  ],
}

const williams: Building = {
  id: '233903',
  record: wtRec,
  graph: wtGraph as BuildingGraph,
  ortho: wtOrtho,
  obliques: { north: wtNorth, east: wtEast, south: wtSouth, west: wtWest },
  obliqueCaptured: wtAerial.images['oblique-north']?.captured ?? null,
  obliqueNotes: {},
  obliqueFocus: {},
  collection: wtAerial.collection,
  parcel: wtParcel,
  orthoBounds: orthoBoundsFor(wtParcel, 10),
  // The Vexcel parcel in this snapshot is centred about 95 m north of the
  // tower, on the ~110 m neighbour: the CoStar point sits inside Williams
  // Tower's OpenStreetMap footprint (275 m), and the obliques centre on the
  // neighbouring white building.
  imageryMatches: false,
  imageryNote: 'The Vexcel imagery in this snapshot is of the neighbouring building, so it is hidden until it is pulled again for Williams Tower.',
  // Entrances placed on the tower's OpenStreetMap footprint: Post Oak Blvd
  // runs along the east side; the garage is to the west. Both estimated.
  markers: [
    { node: 'st_main', label: 'Post Oak Blvd main entrance', at: offset(wtCentre, 30, 0), estimated: true },
    { node: 'gar1', label: 'Parking garage lobby', at: offset(wtCentre, -28, 8), estimated: true },
  ],
  matterport: [
    { id: 'eJKnR3x44eh', title: 'Titan Global Advisory, Suite 5600', subtitle: 'Reception and offices, floor 56', destination: true },
  ],
  demoGoal: 'room29',
}

// Rabinowitz Hall is not in the CoStar kit: the record is written by hand,
// and the graph comes from the Matterport scan (see its GRAPH_NOTES.md). The
// scan origin is taken as the record's point; the notes put the stairs at
// compass bearing 20 degrees where the plan says 16.8, so the plan is turned
// 3.2 degrees clockwise. The entrance (east wall of the atrium) is then placed
// from its plan position. Estimated to a few metres.
const jrRec = jrRecord as unknown as CostarRecord
const jrParcel = parseWkt(jrAerial.parcel_wkt)
const JR_ROT = 3.2
const jrPlan = (x: number, y: number): LngLat => {
  const t = (JR_ROT * Math.PI) / 180
  return offset([jrRec.longitude, jrRec.latitude], x * Math.cos(t) + y * Math.sin(t), -x * Math.sin(t) + y * Math.cos(t))
}
const rabinowitz: Building = {
  id: 'jrr',
  record: jrRec,
  graph: jrGraph as BuildingGraph,
  ortho: jrOrtho,
  obliques: { north: jrNorth, east: jrEast, south: jrSouth, west: jrWest },
  obliqueCaptured: (jrAerial as { images?: Record<string, { captured?: string }> }).images?.['oblique-north']?.captured ?? null,
  obliqueNotes: {},
  obliqueFocus: {},
  collection: jrAerial.collection,
  parcel: jrParcel,
  orthoBounds: orthoBoundsFor(jrParcel, 10),
  imageryMatches: true,
  markers: [
    { node: 'entrance1', label: 'Glass entrance', at: jrPlan(15.2, 4.4), estimated: true, side: 'east' },
  ],
  matterport: [
    { id: 'P3S6VUTP3qB', title: 'Rabinowitz Hall', subtitle: 'Atrium hall and upper corridor', destination: true },
  ],
  demoGoal: 's20',
  graphRotationDeg: JR_ROT,
}

const buildings: Record<string, Building> = {
  [louisiana.id]: louisiana, [williams.id]: williams, [rabinowitz.id]: rabinowitz,
}

/** Whether the record came from CoStar (not written by hand). */
export const inCostar = (b: Building) => !/not in the CoStar kit/i.test(b.record.source ?? '')

/** Storeys above grade: CoStar's count, else the highest floor in the graph. */
export const storiesOf = (b: Building) =>
  b.record.stories_above_grade ?? Math.max(...b.graph.nodes.map((n) => n.floor))

export function buildingById(id: string | null | undefined): Building | null {
  return (id && buildings[id]) || null
}

/** The building whose graph contains every node of a route, if any. */
export function buildingForRoute(nodeIds: string[]): Building | null {
  if (!nodeIds.length) return null
  return Object.values(buildings).find((b) => {
    const ids = new Set(b.graph.nodes.map((n) => n.id))
    return nodeIds.every((id) => ids.has(id))
  }) ?? null
}

export const demoBuilding = louisiana

const OPPOSITE: Record<Direction, Direction> = { north: 'south', south: 'north', east: 'west', west: 'east' }

/** Centre of the parcel. */
export function parcelCentre(b: Building): LngLat {
  const ring = b.parcel.slice(0, -1)
  return [ring.reduce((t, p) => t + p[0], 0) / ring.length, ring.reduce((t, p) => t + p[1], 0) / ring.length]
}

/** Centre of the building: the parcel when its imagery matches, else the CoStar point. */
export function siteCentre(b: Building): LngLat {
  return b.imageryMatches ? parcelCentre(b) : [b.record.longitude, b.record.latitude]
}

/** Which side of the building a point is on (largest offset from the building centre). */
export function sideOf(b: Building, at: LngLat): Direction {
  const [cx, cy] = siteCentre(b)
  const east = (at[0] - cx) * Math.cos((cy * Math.PI) / 180)
  const north = at[1] - cy
  if (Math.abs(east) > Math.abs(north)) return east > 0 ? 'east' : 'west'
  return north > 0 ? 'north' : 'south'
}

/** The side of the building an entrance is on. */
export const entranceSide = (b: Building, m: SiteMarker): Direction => m.side ?? sideOf(b, m.at)

/**
 * Vexcel names each oblique by the direction the camera looks (checked
 * against the camera GPS in the EXIF: the "east" image was shot from the
 * west). So the photo that shows a building's west side is the "east" one.
 */
export const obliqueShowing = (side: Direction): Direction => OPPOSITE[side]
/** Where the camera stood for an oblique: the "east" image is seen from the west. */
export const viewedFrom = (oblique: Direction): Direction => OPPOSITE[oblique]

/** Floor the patient is on: from the suite's CoStar tenant row, else the parsed note. */
export function patientFloor(b: Building, parsed: Record<string, unknown> | null): number | null {
  const suite = parsed?.suite != null ? String(parsed.suite) : null
  const fromTenant = b.record.current_tenants.find((t) => t.suite === suite)?.floor_guess_from_suite
  if (fromTenant) return fromTenant
  return typeof parsed?.floor === 'number' ? parsed.floor : null
}

/** Matterport Showcase embed URL. Models here are public, so no SDK key. */
export function matterportUrl(id: string, opts: { autoplay?: boolean; tour?: boolean } = {}) {
  const p = new URLSearchParams({ m: id, play: opts.autoplay ? '1' : '0', qs: '1', brand: '0', help: '0', mls: '0' })
  // ts = seconds before the guided tour (the highlight reel) starts on its own.
  if (opts.tour) { p.set('ts', '3'); p.set('lp', '1') }
  return `https://my.matterport.com/show/?${p}`
}

export const matterportThumb = (id: string) => `https://my.matterport.com/api/v1/player/models/${id}/thumb`

/**
 * Which demo building a call note is about, using the same aliases the
 * server matches (fixtures/buildings/index.json).
 */
export function buildingForNote(note: string): string | null {
  const text = note.toLowerCase()
  const index = buildingIndex as Record<string, { name: string; aliases: string[] }>
  for (const [id, entry] of Object.entries(index)) {
    if ([entry.name, ...entry.aliases].some((a) => text.includes(a.toLowerCase()))) return id
  }
  return null
}

/** One ready-made call per demo building, written to match the server's aliases. */
export const SAMPLE_CALLS: { building: string; label: string; note: string }[] = [
  { building: '233928', label: '1415 Louisiana', note: '65M chest pain, Suite 1800, 1415 Louisiana St, Houston, patient is in the phone room' },
  { building: '233903', label: 'Williams Tower', note: '58F fall with head injury, Suite 5600, Williams Tower, 2800 Post Oak Blvd, Houston, patient is in the conference room' },
  // Rabinowitz Hall (jrr) is left out: its scan data is too rough to demo.
]
