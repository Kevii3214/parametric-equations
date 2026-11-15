import type { RouteStep } from '../../lib/contracts'
import { isFloorChange, tidy } from '../../lib/route'
import CueIcon from '../CueIcon'

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`

/**
 * The route as a timeline: grouped by floor, a connecting line through
 * each step's turn icon, distance and time as small tags, a running clock,
 * and the lift or stairs as a band between floors.
 */
export default function RouteTimeline({ steps, startFloor }: { steps: RouteStep[]; startFloor: number }) {
  let elapsed = 0
  let floor = startFloor
  const rows: React.ReactNode[] = [<FloorLabel key="f-start" floor={startFloor} />]

  steps.forEach((s, i) => {
    elapsed += s.seconds
    const last = i === steps.length - 1
    if (isFloorChange(s.cue)) {
      const stairs = /stairs/i.test(s.text)
      rows.push(
        <li key={s.index} className="relative py-2 pl-12">
          <span className="absolute top-0 bottom-0 left-[17px] w-0.5 bg-azure-line" aria-hidden="true" />
          <div className="relative flex items-center gap-3 rounded-2xl bg-azure px-4 py-3 text-white shadow-card">
            <CueIcon cue={s.cue} className="h-5 w-5 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold">{stairs ? 'Stairs' : 'Elevator'} · floor {floor} → {s.floor}</p>
              <p className="text-xs text-white/80">{tidy(s.text)}</p>
            </div>
            <span className="font-mono text-xs text-white/80 tabular-nums">{s.seconds} s</span>
          </div>
        </li>,
        <FloorLabel key={`f-${s.index}`} floor={s.floor} />,
      )
      floor = s.floor
      return
    }
    rows.push(
      <li key={s.index} className="group relative flex gap-4 py-2.5 pl-1">
        {/* the line between steps */}
        {!last && <span className="absolute top-8 -bottom-2.5 left-[17px] w-0.5 bg-azure-line" aria-hidden="true" />}
        <span className={`relative z-[1] grid h-9 w-9 shrink-0 place-items-center rounded-full ring-4 ring-paper ${
          last ? 'bg-fern text-white' : 'bg-azure-soft text-azure'}`}>
          <CueIcon cue={s.cue} className="h-[18px] w-[18px]" />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          <p className={`text-[15px] leading-snug ${last ? 'font-semibold text-fern-deep' : 'text-ink'}`}>{tidy(s.text)}</p>
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            {s.meters > 0 && <span className="rounded-full bg-sunk px-2 py-0.5 tabular-nums">{Math.round(s.meters * 10) / 10} m</span>}
            <span className="rounded-full bg-sunk px-2 py-0.5 tabular-nums">{s.seconds} s</span>
          </p>
        </div>
        <span className="pt-1 font-mono text-xs text-ink-3 tabular-nums" title="Time from the entrance">{clock(elapsed)}</span>
      </li>,
    )
  })

  return <ol className="mt-4">{rows}</ol>
}

function FloorLabel({ floor }: { floor: number }) {
  return (
    <li className="flex items-center gap-3 py-1.5 pl-1" aria-hidden="true">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-line-strong bg-card text-xs font-semibold text-ink-2">{floor}</span>
      <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">Floor {floor}</span>
    </li>
  )
}
