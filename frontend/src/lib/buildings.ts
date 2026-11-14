// Real data for the demo building, from fixtures/buildings/<id>/ (CoStar
// record, Vexcel imagery, Matterport models, interior graph). Read-only.
import aerialJson from '../../../fixtures/buildings/233928/aerial.json'
import orthoUrl from '../../../fixtures/buildings/233928/aerial.jpg'
import graphJson from '../../../fixtures/buildings/233928/graph.json'
import obliqueEast from '../../../fixtures/buildings/233928/oblique-east.jpg'
import obliqueNorth from '../../../fixtures/buildings/233928/oblique-north.jpg'
import obliqueSouth from '../../../fixtures/buildings/233928/oblique-south.jpg'
import obliqueWest from '../../../fixtures/buildings/233928/oblique-west.jpg'
import recordJson from '../../../fixtures/buildings/233928/record.json'
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
  building_class: number
  building_rating: number
  stories_above_grade: number
  gross_area_sqft: number
  typical_floor_sqft: number
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
  /** Lon/lat box the ortho image covers: the parcel's bounding box plus 10 m. */
  orthoBounds: { west: number; east: number; south: number; north: number }
  markers: SiteMarker[]
  matterport: MatterportModel[]
}

function parseWkt(wkt: string): LngLat[] {
  const inner = wkt.match(/\(\(\((.*?)\)\)\)/)?.[1] ?? ''
  return inner.split(',').map((p) => p.trim().split(/\s+/).map(Number) as LngLat)
}

function bufferedBounds(ring: LngLat[], metres: number) {
  const lats = ring.map((p) => p[1])
  const lngs = ring.map((p) => p[0])
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2
  const dLat = metres / 111_320
  const dLng = metres / (111_320 * Math.cos((midLat * Math.PI) / 180))
  return {
    west: Math.min(...lngs) - dLng,
    east: Math.max(...lngs) + dLng,
    south: Math.min(...lats) - dLat,
    north: Math.max(...lats) + dLat,
  }
}

const parcel = parseWkt(aerialJson.parcel_wkt)
const orthoBounds = bufferedBounds(parcel, 10)

/** Pixel fraction (0..1) on the ortho image for a lon/lat. */
export function orthoXY(b: Building, [lng, lat]: LngLat): [number, number] {
  const o = b.orthoBounds
  return [(lng - o.west) / (o.east - o.west), (o.north - lat) / (o.north - o.south)]
}

/** Lon/lat for a pixel fraction on the ortho image. */
function fromOrtho(fx: number, fy: number): LngLat {
  const o = orthoBounds
  return [o.west + fx * (o.east - o.west), o.north - fy * (o.north - o.south)]
}

const louisiana: Building = {
  id: '233928',
  record: recordJson as CostarRecord,
  graph: graphJson as BuildingGraph,
  ortho: orthoUrl,
  obliques: { north: obliqueNorth, east: obliqueEast, south: obliqueSouth, west: obliqueWest },
  obliqueCaptured: aerialJson.images['oblique-north']?.captured ?? null,
  obliqueNotes: {
    east: 'The rounded glass tower in front is a neighbour. 1415 Louisiana is the dark brown tower behind it, on the left.',
  },
  obliqueFocus: { east: '22% 55%' },
  collection: aerialJson.collection,
  parcel,
  orthoBounds,
  // The graph's entrance positions are estimates (see GRAPH_NOTES.md); these
  // map pins are placed by eye on the Vexcel ortho to match.
  markers: [
    { node: 'st_main', label: 'Louisiana St main entrance', at: fromOrtho(0.69, 0.66), estimated: true },
    { node: 'gar1', label: 'Parking garage lobby', at: fromOrtho(0.3, 0.44), estimated: true },
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

const buildings: Record<string, Building> = { [louisiana.id]: louisiana }

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

/** Which side of the building a point is on (largest offset from the parcel centre). */
export function sideOf(b: Building, at: LngLat): Direction {
  const [cx, cy] = parcelCentre(b)
  const east = (at[0] - cx) * Math.cos((cy * Math.PI) / 180)
  const north = at[1] - cy
  if (Math.abs(east) > Math.abs(north)) return east > 0 ? 'east' : 'west'
  return north > 0 ? 'north' : 'south'
}

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
