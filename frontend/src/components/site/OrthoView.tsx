import { orthoXY, type Building } from '../../lib/buildings'

/** Vexcel ortho with the CoStar parcel outline and the entrance pins on top. */
export default function OrthoView({ building, entranceNode }: { building: Building; entranceNode: string | null }) {
  const pt = (p: [number, number]) => orthoXY(building, p).map((v) => v * 1000) as [number, number]
  const ring = building.parcel.map(pt)
  return (
    <div className="relative h-full w-full overflow-hidden bg-ink">
      <img src={building.ortho} alt={`Vexcel overhead image of ${building.record.name}`}
        className="absolute inset-0 h-full w-full object-cover" />
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 h-full w-full">
        <polygon points={ring.map((p) => p.join(',')).join(' ')}
          fill="rgb(35 87 214 / 0.14)" stroke="white" strokeWidth={5} strokeLinejoin="round" />
        <polygon points={ring.map((p) => p.join(',')).join(' ')}
          fill="none" stroke="var(--color-azure)" strokeWidth={2.5} strokeDasharray="10 7" strokeLinejoin="round" />
        {building.markers.map((m) => {
          const [x, y] = pt(m.at)
          const chosen = m.node === entranceNode
          return (
            <g key={m.node} transform={`translate(${x} ${y})`}>
              {chosen && (
                <circle r={34} fill="rgb(14 138 95 / 0.25)" stroke="white" strokeWidth={2}>
                  <animate attributeName="r" values="22;40;22" dur="2s" repeatCount="indefinite" />
                </circle>
              )}
              <circle r={chosen ? 13 : 10} fill={chosen ? 'var(--color-fern)' : 'white'}
                stroke={chosen ? 'white' : 'var(--color-ink-2)'} strokeWidth={4} />
              <g transform={`translate(0 ${chosen ? -30 : -24})`}>
                <rect x={-m.label.length * 6.2 - 12} y={-20} width={m.label.length * 12.4 + 24} height={28} rx={14}
                  fill={chosen ? 'var(--color-fern)' : 'rgb(255 253 248 / 0.92)'} />
                <text textAnchor="middle" y={0} fontSize={17.5} fontWeight={600}
                  fill={chosen ? 'white' : 'var(--color-ink)'}>{m.label}</text>
              </g>
            </g>
          )
        })}
      </svg>
      <div className="pointer-events-none absolute top-3 right-3 grid h-9 w-9 place-items-center rounded-full bg-card/90 text-[10px] font-bold text-ink shadow-card">
        <svg viewBox="0 0 20 20" className="h-4 w-4"><path d="M10 2l4 12-4-3-4 3z" fill="var(--color-alert)" /></svg>
        <span className="-mt-1">N</span>
      </div>
    </div>
  )
}
