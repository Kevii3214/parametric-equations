// TypeScript mirror of contracts/ (frozen after ticket 0). Do not invent fields
// here: if something is missing, change it in contracts/ with Person 2 first.

// ---- contracts/api.md ----

export type Cue =
  | 'LEFT'
  | 'RIGHT'
  | 'STRAIGHT'
  | 'UTURN'
  | 'FLOOR_UP'
  | 'FLOOR_DOWN'
  | 'ARRIVE'
  | 'OFF_ROUTE'

export type IncidentStatus = 'planning' | 'routing' | 'en_route' | 'arrived'

export type PlanStepKind =
  | 'plan'
  | 'subagent'
  | 'tool_call'
  | 'tool_result'
  | 'replan'
  | 'crew'
  | 'final'

export type EventType = 'elevator_out' | 'obstacle' | 'note' | 'arrived' | 'skip_floor' | 'rejoin'

// ---- contracts/route.schema.json ----

export interface RouteStep {
  index: number
  from_node: string
  to_node: string
  cue: Cue
  meters: number
  seconds: number
  /** Floor the paramedic is on when this step ends. */
  floor: number
  text: string
}

// ---- contracts/building_graph.schema.json ----

export type NodeKind = 'entrance' | 'corridor' | 'door' | 'elevator' | 'stairs' | 'aed'
export type EdgeKind = 'corridor' | 'door' | 'elevator' | 'stairs'

export interface GraphNode {
  id: string
  floor: number
  /** Metres east on that floor's plan. */
  x: number
  /** Metres north on that floor's plan. */
  y: number
  kind: NodeKind
  label: string | null
  tag_id: string | null
}

export interface GraphEdge {
  from: string
  to: string
  meters: number
  kind: EdgeKind
  stretcher_ok: boolean
  seconds: number
}

export interface BuildingGraph {
  building_id: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ---- supabase/migrations/0001_init.sql (the five shared tables) ----
// Every column is nullable in the SQL, but the server always fills these.

export interface IncidentRow {
  id: string
  created_at: string
  note: string | null
  parsed: Record<string, unknown> | null
  building_id: string | null
  status: IncidentStatus | null
}

export interface PlanStepRow {
  id: number
  incident_id: string
  seq: number
  kind: PlanStepKind
  title: string
  detail: Record<string, unknown> | null
  created_at: string
}

export interface RouteRow {
  id: number
  incident_id: string
  version: number
  entrance_node: string
  steps: RouteStep[]
  total_seconds: number
  briefing: string | null
  created_at: string
  /**
   * Fly-through tour (contracts/tour.schema.json). Null for a building with
   * no scan data, and missing until the server adds the column; read it with
   * readTour() from lib/tour.ts.
   */
  tour?: unknown
}

export interface PositionRow {
  id: number
  incident_id: string
  route_version: number
  step_index: number
  progress_m: number
  floor: number
  off_route: boolean
  created_at: string
}

/** A safety alert from the wearable (supabase/migrations/0006_alerts.sql): shown while `active`. */
export interface AlertRow {
  id: number
  incident_id: string
  device_id: string | null
  kind: 'fall' | 'air'
  active: boolean
  detail: { v?: number } | null
  created_at: string
  cleared_at: string | null
}

export interface CueRow {
  id: number
  incident_id: string
  route_version: number
  cue: Cue
  dist_m: number | null
  text: string | null
  created_at: string
}
