import maplibregl, { type Map as MlMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import { parcelCentre, type Building, type LngLat } from '../../lib/buildings'

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

const FLOOR_M = 4 // fallback storey height when the map has no building height

// Free vector tiles with building heights (OpenStreetMap data), no API key.
const STYLE = 'https://tiles.openfreemap.org/styles/liberty'

type Phase = 'idle' | 'city' | 'approach' | 'orbit' | 'floor' | 'entrance' | 'done'

const CAPTION: Record<Phase, string> = {
  idle: '',
  city: 'Downtown Houston',
  approach: 'Approaching the building',
  orbit: 'Circling the site',
  floor: 'Patient floor',
  entrance: 'Ambulance stop',
  done: '',
}

/**
 * 3D flyover of the site: drops in from the city, circles the tower, then
 * settles on the entrance the agent chose. The parcel comes from CoStar/Vexcel.
 */
export default function SiteFlyover({ building, entranceNode, patientFloor }: {
  building: Building; entranceNode: string | null; patientFloor: number | null
}) {
  const box = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MlMap | null>(null)
  const run = useRef(0)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const [phase, setPhase] = useState<Phase>('idle')

  const center: LngLat = [building.record.longitude, building.record.latitude]
  const entrance = building.markers.find((m) => m.node === entranceNode) ?? building.markers[0]

  useEffect(() => {
    const runs = run
    if (!box.current) return
    let map: MlMap
    try {
      map = new maplibregl.Map({
        container: box.current,
        style: STYLE,
        center,
        zoom: 16.2,
        pitch: 58,
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
      const ring = [...building.parcel]
      map.addSource('parcel', {
        type: 'geojson',
        data: { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } },
      })
      map.addLayer({ id: 'parcel-fill', type: 'fill', source: 'parcel', paint: { 'fill-color': '#2357d6', 'fill-opacity': 0.22 } })
      map.addLayer({ id: 'parcel-line', type: 'line', source: 'parcel', paint: { 'line-color': '#2357d6', 'line-width': 3 } })

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
        <div class="text-[11px] text-white/80">${building.record.stories_above_grade} stories${
          patientFloor ? ` · Patient on floor ${patientFloor}` : ''}</div></div>`
      new maplibregl.Marker({ element: tag, anchor: 'bottom', offset: [0, -24] }).setLngLat(center).addTo(map)
        if (patientFloor) highlightFloor(map, patientFloor)
      } catch (err) {
        console.warn('map setup:', err)
      }
      setReady(true)
    })
    map.on('error', (e) => console.warn('map:', e.error?.message))
    // Any manual drag or zoom stops a running flyover.
    const stop = () => { run.current++; setPhase('idle') }
    map.on('dragstart', stop)
    map.on('wheel', stop)
    return () => { runs.current++; map.remove(); mapRef.current = null }
    // The building is fixed for the life of this view.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * Find the tower in the map's OpenStreetMap buildings (the footprint that
   * contains the CoStar point, tallest first) and draw the patient's floor as
   * a green band, at its share of the real height. Falls back to the parcel.
   */
  function highlightFloor(map: MlMap, floor: number) {
    const stories = building.record.stories_above_grade
    let done = false
    const draw = (ring: Ring, height: number) => {
      done = true
      const storey = height / stories
      map.addSource('tower', { type: 'geojson', data: { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } } })
      map.addSource('patient-floor', { type: 'geojson', data: { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [grow(ring, 1.08)] } } })
      // A light blue wash over the whole tower, then the floor itself in green.
      map.addLayer({ id: 'tower-wash', type: 'fill-extrusion', source: 'tower', paint: {
        'fill-extrusion-color': '#c4d4f6', 'fill-extrusion-height': height + 0.5, 'fill-extrusion-base': 0, 'fill-extrusion-opacity': 0.5 } })
      map.addLayer({ id: 'patient-floor', type: 'fill-extrusion', source: 'patient-floor', paint: {
        'fill-extrusion-color': '#0e8a5f', 'fill-extrusion-base': (floor - 1) * storey, 'fill-extrusion-height': floor * storey,
        'fill-extrusion-opacity': 0.95 } })
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
    // If the tiles never give us the tower, use a shrunken parcel at the CoStar height.
    map.once('idle', () => {
      tryFind()
      if (!done && mapRef.current === map) {
        map.off('sourcedata', tryFind)
        const c = parcelCentre(building)
        draw(building.parcel.map(([x, y]) => [c[0] + (x - c[0]) * 0.55, c[1] + (y - c[1]) * 0.55]), stories * FLOOR_M)
      }
    })
  }

  async function play() {
    const map = mapRef.current
    if (!map) return
    const id = ++run.current
    const alive = () => run.current === id
    const move = (fn: () => void) => new Promise<void>((res) => { map.once('moveend', () => res()); fn() })
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const end = { center: entrance?.at ?? center, zoom: 18.4, pitch: 66, bearing: -38 }

    if (reduce) { map.jumpTo(end); setPhase('done'); return }

    setPhase('city')
    map.jumpTo({ center: [center[0] + 0.012, center[1] - 0.01], zoom: 13.4, pitch: 20, bearing: 10 })
    await new Promise((r) => setTimeout(r, 900))
    if (!alive()) return
    setPhase('approach')
    await move(() => map.flyTo({ center, zoom: 16.6, pitch: 60, bearing: -20, duration: 5200, curve: 1.6, essential: true }))
    if (!alive()) return
    setPhase('orbit')
    for (let k = 0; k < 4 && alive(); k++) {
      await move(() => map.easeTo({ bearing: map.getBearing() - 90, duration: 3200, easing: (t) => t, essential: true }))
    }
    if (!alive()) return
    if (patientFloor) {
      setPhase('floor')
      await move(() => map.flyTo({ center, zoom: 17, pitch: 62, bearing: map.getBearing() - 30, duration: 3000, essential: true }))
      await new Promise((r) => setTimeout(r, 2200))
      if (!alive()) return
    }
    setPhase('entrance')
    await move(() => map.flyTo({ ...end, duration: 3600, essential: true }))
    if (alive()) setTimeout(() => alive() && setPhase('done'), 2500)
  }

  // Start the flyover once the map is ready.
  useEffect(() => { if (ready) void play() }, [ready]) // eslint-disable-line react-hooks/exhaustive-deps

  if (failed) {
    return (
      <div className="grid h-full w-full place-items-center bg-sunk p-6 text-center text-sm text-ink-2">
        3D map unavailable in this browser (WebGL is off). Try the Overhead or Approach views.
      </div>
    )
  }

  const caption = phase === 'entrance' ? `${CAPTION.entrance}: ${entrance?.label}`
    : phase === 'floor' ? `Patient: floor ${patientFloor} of ${building.record.stories_above_grade}`
    : CAPTION[phase]
  return (
    <div className="relative h-full w-full bg-sunk">
      {/* maplibre-gl.css forces position: relative on the container, so size it from a wrapper. */}
      <div className="absolute inset-0">
        <div ref={box} className="h-full w-full" />
      </div>
      {!ready && <div className="absolute inset-0 grid place-items-center text-sm text-ink-3">Loading 3D map…</div>}
      {caption && (
        <div key={phase} className="trace-in pointer-events-none absolute top-3 left-3 rounded-full bg-ink/80 px-3 py-1.5 text-sm font-medium text-white backdrop-blur">
          {caption}
        </div>
      )}
      <button type="button" onClick={() => void play()} disabled={!ready}
        className="absolute bottom-8 left-3 flex items-center gap-2 rounded-full bg-card py-1.5 pr-3.5 pl-1.5 text-sm font-semibold text-ink shadow-card transition hover:text-azure disabled:opacity-50">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-azure text-xs text-white">▶</span>
        {phase === 'idle' || phase === 'done' ? 'Replay flyover' : 'Restart'}
      </button>
    </div>
  )
}
