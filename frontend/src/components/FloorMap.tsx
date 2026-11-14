import type { BuildingGraph, GraphNode, RouteStep } from '../lib/contracts'
import { nodeMap, type Point } from '../lib/route'

interface Props {
  graph: BuildingGraph
  floor: number
  steps: RouteStep[]
  /** Index of the step being walked; earlier route segments are dimmed. */
  currentStep?: number
  position?: Point | null
  offRoute?: boolean
  /** Edges closed by a replan, as "from->to". */
  closures?: string[]
  className?: string
}

const PAD = 4

const nodeStyle: Record<GraphNode['kind'], string> = {
  entrance: 'fill-sky-400',
  corridor: 'fill-slate-500',
  door: 'fill-rose-400',
  elevator: 'fill-amber-400',
  stairs: 'fill-violet-400',
  aed: 'fill-emerald-400',
}

const nodeLetter: Partial<Record<GraphNode['kind'], string>> = {
  elevator: 'E',
  stairs: 'S',
  aed: '+',
}

/**
 * SVG plan of one floor: corridors from the graph, the route on top, and the
 * paramedic's dot. Metres map 1:1 to SVG units; y is flipped so north is up.
 * Every floor shares one frame, so the elevator sits in the same spot on each.
 */
export default function FloorMap({
  graph, floor, steps, currentStep = 0, position, offRoute, closures = [], className,
}: Props) {
  const nodes = nodeMap(graph)
  const xs = graph.nodes.map((n) => n.x)
  const ys = graph.nodes.map((n) => n.y)
  const minX = Math.min(...xs) - PAD
  const maxX = Math.max(...xs) + PAD
  const minY = Math.min(...ys) - PAD
  const maxY = Math.max(...ys) + PAD
  const sy = (y: number) => maxY + minY - y

  const onFloor = graph.nodes.filter((n) => n.floor === floor)
  const seen = new Set<string>()
  const corridors = graph.edges.filter((e) => {
    const a = nodes.get(e.from)
    const b = nodes.get(e.to)
    const key = [e.from, e.to].sort().join('|')
    if (!a || !b || a.floor !== floor || b.floor !== floor || seen.has(key)) return false
    seen.add(key)
    return true
  })
  const routeSegs = steps
    .map((s) => ({ s, a: nodes.get(s.from_node), b: nodes.get(s.to_node) }))
    .filter(({ a, b }) => a && b && a.floor === floor && b.floor === floor)
  const routeNodes = new Set(steps.flatMap((s) => [s.from_node, s.to_node]))
  const goal = steps.at(-1)?.to_node
  const closed = new Set(closures)

  // Pick which labels to draw: entrances and elevators above the node, the
  // rest below; landmarks first, and a corridor label is skipped when another
  // label on the same side is too close.
  const labelled = new Map<string, boolean>()
  const order = [...onFloor].sort((a, b) => Number(a.kind === 'corridor') - Number(b.kind === 'corridor'))
  for (const n of order) {
    if (!n.label || (n.kind === 'corridor' && !routeNodes.has(n.id))) continue
    const above = n.kind === 'entrance' || n.kind === 'elevator'
    const crowded = n.kind === 'corridor' && order.some((m) => labelled.get(m.id) === above
      && Math.abs(m.y - n.y) < 3 && Math.abs(m.x - n.x) < 8)
    if (!crowded) labelled.set(n.id, above)
  }

  return (
    <svg viewBox={`${minX} ${minY} ${maxX - minX} ${maxY - minY}`}
      className={className} role="img" aria-label={`Floor ${floor} plan`}>
      {corridors.map((e) => {
        const a = nodes.get(e.from)!
        const b = nodes.get(e.to)!
        const isClosed = closed.has(`${e.from}->${e.to}`) || closed.has(`${e.to}->${e.from}`)
        return (
          <line key={`${e.from}-${e.to}`} x1={a.x} y1={sy(a.y)} x2={b.x} y2={sy(b.y)}
            strokeWidth={2.6} strokeLinecap="round"
            className={isClosed ? 'stroke-red-900' : 'stroke-slate-800'} />
        )
      })}
      {routeSegs.map(({ s, a, b }) => (
        <line key={`r${s.index}`} x1={a!.x} y1={sy(a!.y)} x2={b!.x} y2={sy(b!.y)}
          strokeWidth={1.2} strokeLinecap="round"
          className={s.index < currentStep ? 'stroke-sky-900' : 'stroke-sky-400'} />
      ))}
      {onFloor.map((n) => (
        <g key={n.id}>
          {n.id === goal && (
            <circle cx={n.x} cy={sy(n.y)} r={2.6} className="fill-none stroke-rose-400" strokeWidth={0.4} />
          )}
          <circle cx={n.x} cy={sy(n.y)} r={nodeLetter[n.kind] ? 1.5 : routeNodes.has(n.id) ? 0.9 : 0.6}
            className={nodeStyle[n.kind]} />
          {nodeLetter[n.kind] && (
            <text x={n.x} y={sy(n.y) + 0.65} textAnchor="middle" fontSize={1.8} fontWeight={700}
              className="fill-slate-950">{nodeLetter[n.kind]}</text>
          )}
          {n.label && labelled.has(n.id) && (() => {
            // The outermost nodes anchor inward so labels stay in frame.
            const above = labelled.get(n.id)
            const anchor = n.x <= minX + PAD ? 'start' : n.x >= maxX - PAD ? 'end' : 'middle'
            const dx = anchor === 'start' ? -1.2 : anchor === 'end' ? 1.2 : 0
            return (
              <text x={n.x + dx} y={sy(n.y) + (above ? -2.3 : 3.4)} textAnchor={anchor} fontSize={1.4}
                className="fill-slate-400">{n.label.replace(/ \(floor \d+\)$/, '')}</text>
            )
          })()}
        </g>
      ))}
      {position && position.floor === floor && (
        <g>
          <circle cx={position.x} cy={sy(position.y)} r={2.4}
            className={offRoute ? 'fill-red-500/30' : 'fill-white/20'}>
            <animate attributeName="r" values="1.6;3;1.6" dur="1.6s" repeatCount="indefinite" />
          </circle>
          <circle cx={position.x} cy={sy(position.y)} r={1.2}
            className={offRoute ? 'fill-red-500 stroke-white' : 'fill-white stroke-sky-500'} strokeWidth={0.4} />
        </g>
      )}
    </svg>
  )
}
