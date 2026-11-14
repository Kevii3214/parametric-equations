import { useEffect, useState } from 'react'
import Icon from '../Icon'
import type { Building, Direction } from '../../lib/buildings'

const ORDER: Direction[] = ['south', 'east', 'north', 'west']
// Vexcel names obliques by the way the camera looks, so "north" is seen from the south.
const LABEL: Record<Direction, string> = {
  north: 'From the south', east: 'From the west', south: 'From the north', west: 'From the east',
}
const SLIDE_MS = 6000

/**
 * Vexcel oblique images as an approach tour: each direction drifts in slowly
 * (a Ken Burns move) and the tour cycles round the building on its own.
 */
export default function ObliqueTour({ building, start }: { building: Building; start?: Direction }) {
  // Open on the photo that shows the chosen entrance, then tour the rest.
  const [i, setI] = useState(() => Math.max(0, ORDER.indexOf(start ?? ORDER[0])))
  const [playing, setPlaying] = useState(true)

  useEffect(() => {
    if (!playing) return
    const t = setTimeout(() => setI((n) => (n + 1) % ORDER.length), SLIDE_MS)
    return () => clearTimeout(t)
  }, [i, playing])

  const dir = ORDER[i]
  const captured = building.obliqueCaptured
    ? new Date(building.obliqueCaptured).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })
    : null

  return (
    <div className="relative h-full w-full overflow-hidden bg-ink">
      {ORDER.map((d, n) => (
        <img key={d} src={building.obliques[d]} alt={`Vexcel oblique image of ${building.record.name}, ${LABEL[d].toLowerCase()}`}
          className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-1000 ${n === i ? 'opacity-100' : 'opacity-0'}`}
          style={n === i && playing ? { animation: `kenburns-${n % 2} ${SLIDE_MS + 1000}ms ease-out forwards` } : undefined} />
      ))}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black/55 to-transparent" />
      <div className="absolute bottom-3 left-3 text-white">
        <div className="text-lg font-semibold tracking-tight drop-shadow">{LABEL[dir]}</div>
        <div className="text-xs text-white/80">Vexcel oblique{captured ? ` · ${captured}` : ''}</div>
        {building.obliqueNotes[dir] && <div className="mt-1 max-w-md text-xs text-white/90">{building.obliqueNotes[dir]}</div>}
      </div>
      <div className="absolute right-3 bottom-3 flex items-center gap-1 rounded-full bg-card/90 p-1 shadow-card">
        {ORDER.map((d, n) => (
          <button key={d} type="button" onClick={() => { setI(n); setPlaying(false) }}
            aria-label={LABEL[d]} title={LABEL[d]}
            className={`h-7 min-w-7 rounded-full px-2 text-[11px] font-semibold uppercase transition ${
              n === i ? 'bg-azure text-white' : 'text-ink-2 hover:text-ink'}`}>
            {LABEL[d].split(' ').at(-1)![0]}
          </button>
        ))}
        <button type="button" onClick={() => setPlaying((p) => !p)} aria-label={playing ? 'Pause tour' : 'Play tour'}
          className="grid h-7 w-7 place-items-center rounded-full text-ink-2 hover:text-azure">
          <Icon name={playing ? 'pause' : 'play'} className="h-3.5 w-3.5" />
        </button>
      </div>
      {playing && (
        <div className="absolute inset-x-0 top-0 h-0.5 bg-white/20">
          <div key={i} className="h-full bg-white/80" style={{ animation: `progress ${SLIDE_MS}ms linear forwards` }} />
        </div>
      )}
    </div>
  )
}
