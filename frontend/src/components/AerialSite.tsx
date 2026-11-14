import type { BuildingGraph } from '../lib/contracts'

const PAD = 7

/**
 * Site view with the entrances and the one the agent chose. Until the Vexcel
 * image is wired in (P2-2), it draws a schematic footprint from the ground
 * floor of the building graph instead of the photo.
 */
export default function AerialSite({
  graph, entranceNode, className,
}: { graph: BuildingGraph; entranceNode: string | null; className?: string }) {
  const ground = Math.min(...graph.nodes.map((n) => n.floor))
  const nodes = graph.nodes.filter((n) => n.floor === ground)
  const xs = nodes.map((n) => n.x)
  const ys = nodes.map((n) => n.y)
  const fx0 = Math.min(...xs) - 2
  const fx1 = Math.max(...xs) + 2
  const fy0 = Math.min(...ys)
  const fy1 = Math.max(...ys) + 4
  const minX = fx0 - PAD
  const maxX = fx1 + PAD
  const minY = fy0 - PAD - 4
  const maxY = fy1 + PAD
  const sy = (y: number) => maxY + minY - y
  const entrances = nodes.filter((n) => n.kind === 'entrance')

  return (
    <svg viewBox={`${minX} ${minY} ${maxX - minX} ${maxY - minY}`} className={className}
      role="img" aria-label="Site plan with entrances">
      <rect x={minX} y={minY} width={maxX - minX} height={maxY - minY} className="fill-slate-950" />
      {/* street along the south side */}
      <rect x={minX} y={sy(fy0 - 3)} width={maxX - minX} height={6} className="fill-slate-800/70" />
      <line x1={minX} x2={maxX} y1={sy(fy0 - 6)} y2={sy(fy0 - 6)} strokeDasharray="2 2"
        strokeWidth={0.3} className="stroke-slate-600" />
      {/* footprint */}
      <rect x={fx0} y={sy(fy1)} width={fx1 - fx0} height={fy1 - fy0} rx={0.8}
        className="fill-slate-800 stroke-slate-600" strokeWidth={0.4} />
      <text x={(fx0 + fx1) / 2} y={sy(fy1) + 3.2} textAnchor="middle" fontSize={2.2}
        className="fill-slate-500">Building</text>
      {entrances.map((n) => {
        const chosen = n.id === entranceNode
        return (
          <g key={n.id}>
            {chosen && (
              <>
                <circle cx={n.x} cy={sy(n.y)} r={3.4} className="fill-none stroke-sky-400" strokeWidth={0.5}>
                  <animate attributeName="r" values="2.6;4.2;2.6" dur="2s" repeatCount="indefinite" />
                </circle>
                <rect x={n.x - 2.4} y={sy(fy0 - 4.6)} width={4.8} height={2.6} rx={0.5}
                  className="fill-red-600" />
                <text x={n.x} y={sy(fy0 - 4.6) + 1.85} textAnchor="middle" fontSize={1.7} fontWeight={700}
                  className="fill-white">EMS</text>
              </>
            )}
            <circle cx={n.x} cy={sy(n.y)} r={1.4} className={chosen ? 'fill-sky-400' : 'fill-slate-500'} />
            <text x={n.x <= fx0 + 3 ? n.x - 1.5 : n.x >= fx1 - 3 ? n.x + 1.5 : n.x} y={sy(n.y) - 4.4}
              textAnchor={n.x <= fx0 + 3 ? 'start' : n.x >= fx1 - 3 ? 'end' : 'middle'}
              fontSize={1.8} fontWeight={chosen ? 700 : 400}
              className={chosen ? 'fill-sky-300' : 'fill-slate-400'}>
              {n.label ?? n.id}
            </text>
          </g>
        )
      })}
      <g transform={`translate(${maxX - 4} ${minY + 4})`} className="fill-slate-500">
        <path d="M0 -2.4 L1.2 1.2 L0 0.4 L-1.2 1.2 Z" />
        <text y={3.6} textAnchor="middle" fontSize={1.8}>N</text>
      </g>
    </svg>
  )
}
