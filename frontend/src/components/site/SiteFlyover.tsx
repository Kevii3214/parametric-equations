import maplibregl, { type GeoJSONSource, type Map as MlMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useMemo, useRef, useState } from 'react'
import { siteCentre, type Building, type LngLat } from '../../lib/buildings'
import type { RouteStep } from '../../lib/contracts'
import { bearing, placeGraph, routeFeatures, square } from '../../lib/geo3d'
import { cueLabel, type Point } from '../../lib/route'

// Free vector tiles with building heights (OpenStreetMap data), no API key.
const STYLE = 'https://tiles.openfreemap.org/styles/liberty'
const FLOOR_M = 4 // fallback storey height when the map has no building height
const EMPTY = { type: 'FeatureCollection' as const, features: [] }

type Ring = LngLat[]

/** Ray-casting point-in-polygon on the outer ring. */
function inside([x, y]: LngLat, ring: Ring): boolean {
  let hit = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit
  }
  return hit
}

/** Grow a ring about its centre, so a floor band pokes out of the tower walls. */
function grow(ring: Ring, k: number): Ring {
  const cx = ring.reduce((t, p) => t + p[0], 0) / ring.length
  const cy = ring.reduce((t, p) => t + p[1], 0) / ring.length
  return ring.map(([x, y]) => [cx + (x - cx) * k, cy + (y - cy) * k])
}

const poly = (ring: Ring) => ({ type: 'Feature' as const, properties: {}, geometry: { type: 'Polygon' as const, coordinates: [ring] } })

type Phase = 'idle' | 'city' | 'approach' | 'orbit' | 'floor' | 'entrance' | 'route' | 'done'

interface Props {
  building: Building
  entranceNode: string | null
  patientFloor: number | null
  /** The route to draw in 3D, and the step being walked. */
  steps?: RouteStep[]
  currentStep?: number
  /** The crew's position on the floor plans (graph coordinates). */
  position?: Point | null
  /** 'dispatch' plays the city flyover on load; 'medic' frames the route and waits. */
  mode?: 'dispatch' | 'medic'
}

/**
 * The site in 3D: the tower with the patient's floor highlighted, the route
 * drawn through the building (street to entrance, up the shaft, along the
 * floor), the crew's position, and camera flights over all of it.
 */
export default function SiteFlyover({ building, entranceNode, patientFloor, steps = [], currentStep = 0, position, mode = 'dispatch' }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MlMap | null>(null)
  const run = useRef(0)
  const [ready, setReady] = useState(false)
  const [storey, setStorey] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')
  const [caption, setCaption] = useState('')

  const stories = building.record.stories_above_grade
  const center: LngLat = siteCentre(building)
  const entrance = building.markers.find((m) => m.node === entranceNode) ?? building.markers[0]
  const placer = useMemo(() => placeGraph(building), [building])
  const nodes = useMemo(() => new Map(building.graph.nodes.map((n) => [n.id, n])), [building])
  const alt = (floor: number) => (floor - placer.groundFloor) * (storey ?? FLOOR_M)

  useEffect(() => {
    const runs = run
    if (!box.current) return
    let map: MlMap
    try {
      map = new maplibregl.Map({
        container: box.current,
        style: STYLE,
        center: mode === 'medic' ? entrance?.at ?? center : center,
        zoom: mode === 'medic' ? 17.6 : 16.2,
        pitch: mode === 'medic' ? 62 : 58,
        bearing: -28,
        attributionControl: { compact: true },
        canvasContextAttributes: { antialias: true },
      })
    } catch (err) {
      console.warn('map:', err)
      setFailed(true)
      return
    }
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    // Let the camera centre sit at a floor's height for the route flight.
    map.setCenterClampedToGround(false)

    // Set up as soon as the style is ready; tiles keep streaming in after.
    map.once('style.load', () => {
      if (mapRef.current !== map) return
      try {
        // Warm the 3D buildings into the app's cream palette.
        for (const layer of map.getStyle().layers ?? []) {
          if (layer.type === 'fill-extrusion') {
            map.setPaintProperty(layer.id, 'fill-extrusion-color', '#e9e0c9')
            map.setPaintProperty(layer.id, 'fill-extrusion-opacity', 0.92)
          }
        }
        if (building.imageryMatches) {
          map.addSource('parcel', { type: 'geojson', data: poly([...building.parcel]) })
          map.addLayer({ id: 'parcel-fill', type: 'fill', source: 'parcel', paint: { 'fill-color': '#2357d6', 'fill-opacity': 0.18 } })
          map.addLayer({ id: 'parcel-line', type: 'line', source: 'parcel', paint: { 'line-color': '#2357d6', 'line-width': 3 } })
        }
        // Route and position layers are added after the tower: each extrusion
        // layer is drawn over the ones before it, so the route shows through.
        map.addSource('route-3d', { type: 'geojson', data: EMPTY })
        map.addSource('me', { type: 'geojson', data: EMPTY })
        map.addSource('goal', { type: 'geojson', data: EMPTY })
        const pins: HTMLElement[] = []
        for (const m of building.markers) {
          const chosen = m.node === entrance?.node
          const el = document.createElement('div')
          el.className = 'flex flex-col items-center'
          el.innerHTML = `
            <span class="mb-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold shadow-card ${
              chosen ? 'bg-fern text-white' : 'bg-card text-ink'}">${chosen ? 'Stop here · ' : ''}${m.label}</span>
            <span class="block rounded-full border-[3px] border-white ${chosen ? 'h-4 w-4 bg-fern' : 'h-3 w-3 bg-ink-2'}"
              style="box-shadow:0 0 0 ${chosen ? 6 : 0}px rgb(14 138 95 / .25)"></span>`
          new maplibregl.Marker({ element: el, anchor: 'bottom' }).setLngLat(m.at).addTo(map)
          pins.push(el)
        }
        // Entrance pins sit metres apart, so show them only once zoomed in.
        const togglePins = () => pins.forEach((p) => { p.style.visibility = map.getZoom() >= 17.2 ? 'visible' : 'hidden' })
        map.on('zoom', togglePins)
        togglePins()
        const tag = document.createElement('div')
        tag.innerHTML = `<div class="rounded-2xl bg-azure px-3 py-2 text-white shadow-card">
          <div class="text-[13px] font-semibold leading-tight">${building.record.name}</div>
          <div class="text-[11px] text-white/80">${stories} stories${patientFloor ? ` · Patient on floor ${patientFloor}` : ''}</div></div>`
        new maplibregl.Marker({ element: tag, anchor: 'bottom', offset: [0, -24] }).setLngLat(center).addTo(map)
        findTower(map)
      } catch (err) {
        console.warn('map setup:', err)
      }
      setReady(true)
    })
    map.on('error', (e) => console.warn('map:', e.error?.message))
    // Any manual drag or zoom stops a running flight.
    const stop = () => { run.current++; setPhase('idle'); setCaption('') }
    map.on('dragstart', stop)
    map.on('wheel', stop)
    return () => { runs.current++; map.remove(); mapRef.current = null }
    // The building is fixed for the life of this view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * Find the tower in the map's OpenStreetMap buildings (the footprint that
   * contains the site centre, tallest first), wash it blue, draw the patient's
   * floor as a green band, and work out metres per storey for the route.
   * Falls back to a square at the CoStar height.
   */
  function findTower(map: MlMap) {
    let done = false
    const draw = (ring: Ring, height: number) => {
      done = true
      const perStorey = height / stories
      map.addSource('tower', { type: 'geojson', data: poly(ring) })
      map.addLayer({ id: 'tower-wash', type: 'fill-extrusion', source: 'tower', paint: {
        'fill-extrusion-color': '#c4d4f6', 'fill-extrusion-height': height + 0.5, 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.45 } })
      if (patientFloor) {
        map.addSource('patient-floor', { type: 'geojson', data: poly(grow(ring, 1.08)) })
        map.addLayer({ id: 'patient-floor', type: 'fill-extrusion', source: 'patient-floor', paint: {
          'fill-extrusion-color': '#0e8a5f', 'fill-extrusion-base': (patientFloor - 1) * perStorey,
          'fill-extrusion-height': patientFloor * perStorey, 'fill-extrusion-opacity': 0.55 } })
      }
      map.addLayer({ id: 'route-3d', type: 'fill-extrusion', source: 'route-3d', paint: {
        'fill-extrusion-color': ['case', ['==', ['get', 'done'], 1], '#9fb7ef', '#2357d6'],
        'fill-extrusion-base': ['get', 'base'], 'fill-extrusion-height': ['get', 'top'], 'fill-extrusion-opacity': 0.95 } })
      map.addLayer({ id: 'goal', type: 'fill-extrusion', source: 'goal', paint: {
        'fill-extrusion-color': '#c93c3c', 'fill-extrusion-base': ['get', 'base'], 'fill-extrusion-height': ['get', 'top'] } })
      map.addLayer({ id: 'me', type: 'fill-extrusion', source: 'me', paint: {
        'fill-extrusion-color': '#0e8a5f', 'fill-extrusion-base': ['get', 'base'], 'fill-extrusion-height': ['get', 'top'] } })
      setStorey(perStorey)
    }
    const tryFind = () => {
      if (done || mapRef.current !== map) return
      let best: { ring: Ring; height: number } | null = null
      for (const f of map.querySourceFeatures('openmaptiles', { sourceLayer: 'building' })) {
        const g = f.geometry
        const rings = g.type === 'Polygon' ? [g.coordinates[0]] : g.type === 'MultiPolygon' ? g.coordinates.map((p: number[][][]) => p[0]) : []
        const h = Number(f.properties?.render_height ?? 0)
        for (const r of rings as Ring[]) if (inside(center, r) && (!best || h > best.height)) best = { ring: r, height: h }
      }
      if (best && best.height > 30) {
        draw(best.ring, best.height)
        map.off('sourcedata', tryFind)
      }
    }
    map.on('sourcedata', tryFind)
    map.once('idle', () => {
      tryFind()
      if (!done && mapRef.current === map) {
        map.off('sourcedata', tryFind)
        draw(square(center, 36), stories * FLOOR_M)
      }
    })
  }

  // Draw the route, the goal and the crew's position once the height is known.
  useEffect(() => {
    const map = mapRef.current
    if (!map || storey === null || !map.getSource('route-3d')) return
    ;(map.getSource('route-3d') as GeoJSONSource).setData(routeFeatures(placer, nodes, steps, storey, currentStep))
    const goal = nodes.get(steps.at(-1)?.to_node ?? '')
    ;(map.getSource('goal') as GeoJSONSource).setData(goal
      ? { type: 'FeatureCollection', features: [{ ...poly(square(placer.at(goal.x, goal.y, goal.floor), 2.2)), properties: { base: alt(goal.floor), top: alt(goal.floor) + 3.2 } }] }
      : EMPTY)
    ;(map.getSource('me') as GeoJSONSource).setData(position
      ? { type: 'FeatureCollection', features: [{ ...poly(square(placer.at(position.x, position.y, position.floor), 2)), properties: { base: alt(position.floor) + 0.3, top: alt(position.floor) + 2.6 } }] }
      : EMPTY)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storey, steps, currentStep, position, placer, nodes])

  const move = (map: MlMap, fn: () => void) => new Promise<void>((res) => { map.once('moveend', () => res()); fn() })
  const pause = (ms: number) => new Promise((r) => setTimeout(r, ms))

  /** Dispatch intro: drop in from the city, circle, show the floor, land on the entrance, then follow the route. */
  async function playIntro() {
    const map = mapRef.current
    if (!map) return
    const id = ++run.current
    const alive = () => run.current === id
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const end = { center: entrance?.at ?? center, zoom: 18.4, pitch: 66, bearing: -38, elevation: 0 }
    if (reduce) { map.jumpTo(end); setPhase('done'); return }

    setPhase('city'); setCaption(building.record.city)
    map.jumpTo({ center: [center[0] + 0.012, center[1] - 0.01], zoom: 13.4, pitch: 20, bearing: 10, elevation: 0 })
    await pause(900)
    if (!alive()) return
    setPhase('approach'); setCaption('Approaching the building')
    await move(map, () => map.flyTo({ center, zoom: 16.4, pitch: 60, bearing: -20, duration: 5200, curve: 1.6, essential: true }))
    if (!alive()) return
    setPhase('orbit'); setCaption('Circling the site')
    for (let k = 0; k < 4 && alive(); k++) {
      await move(map, () => map.easeTo({ bearing: map.getBearing() - 90, duration: 3000, easing: (t) => t, essential: true }))
    }
    if (!alive()) return
    if (patientFloor) {
      setPhase('floor'); setCaption(`Patient: floor ${patientFloor} of ${stories}`)
      await move(map, () => map.flyTo({ center, zoom: 16.8, pitch: 62, bearing: map.getBearing() - 30, duration: 3000, essential: true }))
      await pause(2000)
      if (!alive()) return
    }
    setPhase('entrance'); setCaption(`Ambulance stop: ${entrance?.label}`)
    await move(map, () => map.flyTo({ ...end, duration: 3600, essential: true }))
    await pause(1200)
    if (alive() && steps.length) await flyRoute(id)
    else if (alive()) { setPhase('done'); setCaption('') }
  }

  /**
   * Fly the route: through the entrance, up the shaft to the patient's
   * floor, then along the corridor to the patient. The camera centre rises
   * to each floor's height.
   */
  async function flyRoute(id = ++run.current) {
    const map = mapRef.current
    if (!map || !steps.length) return
    const alive = () => run.current === id
    setPhase('route')
    const first = nodes.get(steps[0].from_node)
    if (!first) return
    let here = placer.at(first.x, first.y, first.floor)
    let heading = map.getBearing()
    setCaption(`Start at ${entrance?.label ?? 'the entrance'}`)
    await move(map, () => map.flyTo({ center: here, elevation: alt(first.floor), zoom: 19.2, pitch: 64, duration: 2200, essential: true }))
    for (const s of steps) {
      if (!alive()) return
      const a = nodes.get(s.from_node)
      const b = nodes.get(s.to_node)
      if (!a || !b) continue
      const there = placer.at(b.x, b.y, b.floor)
      setCaption(`${s.index + 1}/${steps.length} · ${s.text}`)
      if (a.floor !== b.floor) {
        // Pull back to watch the climb, rise with it, then close in on the floor.
        await move(map, () => map.easeTo({ center: here, elevation: alt(a.floor), zoom: 17.6, pitch: 55, duration: 1200, essential: true }))
        await move(map, () => map.easeTo({ center: there, elevation: alt(b.floor), zoom: 17.6, duration: 3200, essential: true }))
        await move(map, () => map.easeTo({ zoom: 19.6, pitch: 66, duration: 1400, essential: true }))
      } else {
        if (Math.hypot(there[0] - here[0], there[1] - here[1]) > 1e-7) heading = bearing(here, there)
        await move(map, () => map.easeTo({ center: there, elevation: alt(b.floor), bearing: heading, zoom: 19.6, pitch: 66,
          duration: Math.max(1100, Math.min(3500, s.meters * 140)), essential: true }))
      }
      here = there
    }
    if (alive()) {
      setCaption(`${cueLabel.ARRIVE}: ${nodes.get(steps.at(-1)!.to_node)?.label ?? 'patient'}`)
      setPhase('done')
    }
  }

  // Dispatch starts its intro once the map is ready; the medic view waits.
  useEffect(() => { if (ready && mode === 'dispatch') void playIntro() }, [ready]) // eslint-disable-line react-hooks/exhaustive-deps

  if (failed) {
    return (
      <div className="grid h-full w-full place-items-center bg-sunk p-6 text-center text-sm text-ink-2">
        3D map unavailable in this browser (WebGL is off). Try the other views.
      </div>
    )
  }

  const busy = phase !== 'idle' && phase !== 'done'
  return (
    <div className="relative h-full w-full bg-sunk">
      {/* maplibre-gl.css forces position: relative on the container, so size it from a wrapper. */}
      <div className="absolute inset-0">
        <div ref={box} className="h-full w-full" />
      </div>
      {!ready && <div className="absolute inset-0 grid place-items-center text-sm text-ink-3">Loading 3D map…</div>}
      {caption && (
        <div key={caption} className="trace-in pointer-events-none absolute top-3 right-14 left-3 flex">
          <span className="rounded-2xl bg-ink/80 px-3 py-1.5 text-sm font-medium text-white backdrop-blur">{caption}</span>
        </div>
      )}
      <div className="absolute bottom-8 left-3 flex flex-wrap gap-2">
        {steps.length > 0 && (
          <button type="button" onClick={() => void flyRoute()} disabled={!ready}
            className="flex items-center gap-2 rounded-full bg-azure py-1.5 pr-3.5 pl-1.5 text-sm font-semibold text-white shadow-card transition hover:bg-azure-deep disabled:opacity-50">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-white/20 text-xs">▶</span>
            {phase === 'route' ? 'Restart route' : 'Fly the route'}
          </button>
        )}
        {mode === 'dispatch' && (
          <button type="button" onClick={() => void playIntro()} disabled={!ready}
            className="flex items-center gap-2 rounded-full bg-card py-1.5 pr-3.5 pl-1.5 text-sm font-semibold text-ink shadow-card transition hover:text-azure disabled:opacity-50">
            <span className="grid h-7 w-7 place-items-center rounded-full bg-sunk text-xs">↺</span>
            {busy && phase !== 'route' ? 'Restart flyover' : 'Replay flyover'}
          </button>
        )}
      </div>
      <div className="pointer-events-none absolute right-3 bottom-8 flex flex-col items-end gap-1 rounded-xl bg-card/90 px-2.5 py-2 text-[11px] text-ink-2 shadow-card">
        <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-azure" />Route</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-fern" />{position ? 'Crew · patient floor' : 'Patient floor'}</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-alert" />Patient</span>
      </div>
    </div>
  )
}
