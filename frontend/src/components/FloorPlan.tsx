import { useEffect, useMemo, useState } from 'react'
import type { Building } from '../lib/buildings'
import type { BuildingGraph, GraphNode, RouteStep } from '../lib/contracts'
import { bounds, planFor, type Plan, type XY } from '../lib/floorplan'
import { tidy, type Point } from '../lib/route'

/** Room types too common to label (they would crowd the plan). */
const GENERIC = new Set(['office', 'closet', 'other', 'hallway', 'supply room', 'storage', 'utility room', 'bathroom'])

/** A small direction chevron drawn on the route line. */
function Chevron({ x, y, angle, size }: { x: number; y: number; angle: number; size: number }) {
  return (
    <path transform={`translate(${x} ${y}) rotate(${(angle * 180) / Math.PI})`}
      d={`M${-size} ${-size} L${size * 0.4} 0 L${-size} ${size}`} fill="none" stroke="white"
      strokeWidth={size * 0.55} strokeLinecap="round" strokeLinejoin="round" />
  )
}

interface Props {
  building: Building | null
  graph: BuildingGraph
  floor: number
  steps: RouteStep[]
  currentStep: number
  position?: Point | null
  offRoute?: boolean
  className?: string
}

/**
 * The floor's real layout (walls, doorways, rooms) from the Matterport scan,
 * with the route traced over it. Floors or stretches with no scan (street,
 * lobby, lift corridors) show the route on a plain, dashed corridor instead.
 */
export default function FloorPlan({ building, graph, floor, steps, currentStep, position, offRoute, className }: Props) {
  const source = building?.floorPlans?.[floor]
  const key = source && building ? `${building.id}:${floor}` : null
  const [loaded, setLoaded] = useState<{ key: string; plan: Plan | null } | null>(null)
  const plan = loaded && loaded.key === key ? loaded.plan : null

  useEffect(() => {
    if (!key || !source || !building?.loadInterior) return
    let alive = true
    building.loadInterior()
      .then((interior) => { if (alive) setLoaded({ key, plan: planFor(interior, source.modelId, source.scanFloor) }) })
      .catch(() => { if (alive) setLoaded({ key, plan: null }) })
    return () => { alive = false }
  }, [key, source, building])

  const nodes = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph])
  const onFloor = (n?: GraphNode) => !!n && n.floor === floor
  const segs = steps
    .map((s) => ({ s, a: nodes.get(s.from_node), b: nodes.get(s.to_node) }))
    .filter((x): x is { s: RouteStep; a: GraphNode; b: GraphNode } => onFloor(x.a) && onFloor(x.b))
  const routePts: XY[] = segs.flatMap(({ a, b }) => [[a.x, a.y], [b.x, b.y]] as XY[])
  // Without a scan, frame the whole floor of the graph; with one, the walls and the route.
  const floorPts: XY[] = graph.nodes.filter((n) => n.floor === floor).map((n) => [n.x, n.y])
  const box = bounds(plan, plan ? routePts : [...floorPts, ...routePts], plan ? 1.5 : 4)
  const W = box.x1 - box.x0
  const H = box.y1 - box.y0
  const sy = (y: number) => box.y1 + box.y0 - y
  const unit = Math.max(W, H) / 60 // ~1/60 of the view: keeps strokes and text readable at any size
  const goal = nodes.get(steps.at(-1)?.to_node ?? '')
  const showGoal = onFloor(goal)
  const shaft = steps.find((s, i) => i >= currentStep && nodes.get(s.from_node)?.floor === floor && nodes.get(s.to_node)?.floor !== floor)
  const shaftNode = shaft ? nodes.get(shaft.from_node) : null
  const landmarks = graph.nodes.filter((n) => n.floor === floor && n.label
    && (n.kind === 'entrance' || n.kind === 'elevator' || n.kind === 'stairs' || n.id === goal?.id))

  // Graph corridors drawn only where there is no scan to show the real space.
  const corridors = graph.edges.filter((e) => {
    const a = nodes.get(e.from), b = nodes.get(e.to)
    if (!onFloor(a) || !onFloor(b) || e.from > e.to) return false
    if (!plan) return true
    const inScan = (n: GraphNode) => n.x >= box.x0 && n.x <= box.x1 && n.y >= box.y0 && n.y <= box.y1
    return !(inScan(a!) && inScan(b!)) || a!.kind === 'elevator' || b!.kind === 'elevator' || a!.kind === 'stairs' || b!.kind === 'stairs'
  })

  return (
    <div className={`relative ${className ?? ''}`}>
      <svg viewBox={`${box.x0} ${box.y0} ${W} ${H}`} className="h-full w-full" role="img" aria-label={`Floor ${floor} plan with the route`}>
        <defs>
          <pattern id="fp-void" width={unit * 1.2} height={unit * 1.2} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2={unit * 1.2} stroke="var(--color-line-strong)" strokeWidth={unit * 0.25} />
          </pattern>
        </defs>

        {/* Rooms and walls from the scan */}
        {plan?.rooms.filter((r) => r.ring.length > 2).map((r) => (
          <polygon key={r.id} points={r.ring.map(([x, y]) => `${x},${sy(y)}`).join(' ')}
            fill={r.isVoid ? 'url(#fp-void)' : 'var(--color-card)'} stroke="none" />
        ))}
        {plan?.doorways.map((d, k) => (
          <line key={`d${k}`} x1={d.a[0]} y1={sy(d.a[1])} x2={d.b[0]} y2={sy(d.b[1])}
            stroke="var(--color-line-strong)" strokeWidth={unit * 0.15} strokeDasharray={`${unit * 0.4} ${unit * 0.3}`} />
        ))}
        {plan?.walls.map((w, k) => (
          <line key={`w${k}`} x1={w.a[0]} y1={sy(w.a[1])} x2={w.b[0]} y2={sy(w.b[1])}
            stroke="var(--color-ink-2)" strokeWidth={Math.max(w.thickness, unit * 0.35)} strokeLinecap="square" />
        ))}
        {plan?.rooms.filter((r) => r.name && !GENERIC.has(r.name.toLowerCase())).map((r) => (
          <text key={`t${r.id}`} x={r.centre[0]} y={sy(r.centre[1])} textAnchor="middle" fontSize={unit * 1.05}
            className="fill-ink-3" style={{ textTransform: 'uppercase', letterSpacing: '0.05em' }}>{r.name}</text>
        ))}

        {/* Unscanned corridors (approximate) */}
        {corridors.map((e) => {
          const a = nodes.get(e.from)!, b = nodes.get(e.to)!
          return <line key={`${e.from}-${e.to}`} x1={a.x} y1={sy(a.y)} x2={b.x} y2={sy(b.y)}
            stroke="var(--color-card)" strokeWidth={unit * 2.6} strokeLinecap="round" />
        })}

        {/* The route: done (pale), ahead (blue), current (thick, with arrows) */}
        {segs.map(({ s, a, b }) => {
          const done = s.index < currentStep
          const now = s.index === currentStep
          return (
            <g key={s.index}>
              <line x1={a.x} y1={sy(a.y)} x2={b.x} y2={sy(b.y)} strokeLinecap="round"
                stroke={offRoute && now ? 'var(--color-alert)' : done ? 'var(--color-azure-line)' : 'var(--color-azure)'}
                strokeWidth={unit * (now ? 1.5 : 1)} />
              {!done && Math.hypot(b.x - a.x, b.y - a.y) > unit * 3 && (
                <Chevron x={(a.x + b.x) / 2} y={sy((a.y + b.y) / 2)} angle={Math.atan2(sy(b.y) - sy(a.y), b.x - a.x)} size={unit * (now ? 0.75 : 0.55)} />
              )}
            </g>
          )
        })}

        {/* Lift or stairs to take from this floor */}
        {shaftNode && (
          <g transform={`translate(${shaftNode.x} ${sy(shaftNode.y)})`}>
            <rect x={-unit * 1.6} y={-unit * 1.6} width={unit * 3.2} height={unit * 3.2} rx={unit * 0.6} fill="var(--color-azure-deep)" />
            <text y={unit * 0.55} textAnchor="middle" fontSize={unit * 1.5} fontWeight={700} fill="white">
              {/stairs/i.test(shaft!.text) ? 'S' : 'E'}
            </text>
          </g>
        )}

        {/* Landmark labels */}
        {landmarks.map((n) => (
          <text key={`l${n.id}`} x={n.x} y={sy(n.y) - unit * 2.3} textAnchor="middle" fontSize={unit * 1.3} fontWeight={600}
            className="fill-ink" stroke="var(--color-paper)" strokeWidth={unit * 0.35} paintOrder="stroke">{tidy(n.label!)}</text>
        ))}

        {/* The patient */}
        {showGoal && goal && (
          <g transform={`translate(${goal.x} ${sy(goal.y)})`}>
            <circle r={unit * 2.2} fill="var(--color-alert)" opacity={0.18} />
            <circle r={unit * 1.1} fill="var(--color-alert)" stroke="white" strokeWidth={unit * 0.35} />
          </g>
        )}

        {/* You are here */}
        {position && position.floor === floor && (
          <g transform={`translate(${position.x} ${sy(position.y)})`}>
            <circle r={unit * 2.4} fill="var(--color-azure)" opacity={0.2}>
              <animate attributeName="r" values={`${unit * 1.6};${unit * 3};${unit * 1.6}`} dur="1.6s" repeatCount="indefinite" />
            </circle>
            <circle r={unit * 1.1} fill={offRoute ? 'var(--color-alert)' : 'var(--color-azure)'} stroke="white" strokeWidth={unit * 0.4} />
          </g>
        )}
      </svg>
      <div className="pointer-events-none absolute top-2 left-2 rounded-full bg-card/90 px-2.5 py-1 text-[11px] font-medium text-ink-2 shadow-card">
        Floor {floor}{plan ? ' · from the scan' : source ? ' · loading plan…' : ' · not scanned, approximate'}
      </div>
    </div>
  )
}
