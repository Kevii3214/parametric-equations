import { useEffect, useState } from 'react'
import type {
  CueRow,
  IncidentRow,
  PlanStepRow,
  PositionRow,
  RouteRow,
} from './contracts'
import { fixtureIncident } from './fixtures'
import { scenarioIncident, scenarioPlanSteps, scenarioRoute } from './scenario'
import { supabase } from './supabase'

export interface IncidentLive {
  incident: IncidentRow | null
  planSteps: PlanStepRow[]
  /** Highest route version seen so far (replans insert a new version). */
  route: RouteRow | null
  position: PositionRow | null
  cue: CueRow | null
  source: 'supabase' | 'fixtures'
}

const empty: Omit<IncidentLive, 'source'> = {
  incident: null,
  planSteps: [],
  route: null,
  position: null,
  cue: null,
}

const fixtureState: IncidentLive = {
  ...empty,
  // Demo mode shows the real demo building (1415 Louisiana), not the toy fixture.
  incident: scenarioIncident,
  planSteps: scenarioPlanSteps,
  route: scenarioRoute,
  source: 'fixtures',
}

function upsertStep(list: PlanStepRow[], row: PlanStepRow): PlanStepRow[] {
  return [...list.filter((s) => s.id !== row.id), row].sort((a, b) => a.seq - b.seq)
}

function newerRoute(cur: RouteRow | null, row: RouteRow): RouteRow {
  return cur && cur.version > row.version ? cur : row
}

function newer<T extends { id: number }>(cur: T | null, row: T): T {
  return cur && cur.id > row.id ? cur : row
}

/**
 * Live view of one incident: an initial read of the five shared tables, then
 * Realtime inserts and updates. Uses the anon key only (read-only). With no
 * Supabase env vars, or with demo set, it returns the fixtures instead.
 */
export function useIncidentLive(incidentId: string | null, demo = false): IncidentLive {
  // The sample incident id comes back when the server was down at intake, so
  // replay the fixtures for it rather than looking it up in Supabase.
  const useFixtures = demo || !supabase || incidentId === fixtureIncident.id
  const [live, setState] = useState<IncidentLive & { key: string | null }>({
    ...empty,
    source: 'supabase',
    key: null,
  })

  useEffect(() => {
    if (useFixtures || !supabase || !incidentId) return
    const db = supabase
    let cancelled = false
    const byIncident = `incident_id=eq.${incidentId}`
    const setLive = (f: (s: IncidentLive) => IncidentLive) =>
      setState((prev) => {
        const base = prev.key === incidentId ? prev : { ...empty, source: 'supabase' as const, key: incidentId }
        return { ...f(base), key: incidentId }
      })

    const channel = db
      .channel(`incident:${incidentId}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'incidents', filter: `id=eq.${incidentId}` },
        (p) => setLive((s) => ({ ...s, incident: p.new as IncidentRow })))
      .on('postgres_changes', { event: '*', schema: 'public', table: 'plan_steps', filter: byIncident },
        (p) => setLive((s) => ({ ...s, planSteps: upsertStep(s.planSteps, p.new as PlanStepRow) })))
      .on('postgres_changes', { event: '*', schema: 'public', table: 'routes', filter: byIncident },
        (p) => setLive((s) => ({ ...s, route: newerRoute(s.route, p.new as RouteRow) })))
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'positions', filter: byIncident },
        (p) => setLive((s) => ({ ...s, position: newer(s.position, p.new as PositionRow) })))
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'cues', filter: byIncident },
        (p) => setLive((s) => ({ ...s, cue: newer(s.cue, p.new as CueRow) })))
      .subscribe()

    // Initial read after subscribing, so nothing inserted in between is lost.
    void (async () => {
      const [inc, steps, route, pos, cue] = await Promise.all([
        db.from('incidents').select('*').eq('id', incidentId).maybeSingle(),
        db.from('plan_steps').select('*').eq('incident_id', incidentId).order('seq'),
        db.from('routes').select('*').eq('incident_id', incidentId).order('version', { ascending: false }).limit(1).maybeSingle(),
        db.from('positions').select('*').eq('incident_id', incidentId).order('id', { ascending: false }).limit(1).maybeSingle(),
        db.from('cues').select('*').eq('incident_id', incidentId).order('id', { ascending: false }).limit(1).maybeSingle(),
      ])
      if (cancelled) return
      setLive((s) => ({
        ...s,
        incident: s.incident ?? (inc.data as IncidentRow | null),
        planSteps: ((steps.data ?? []) as PlanStepRow[]).reduce(upsertStep, s.planSteps),
        route: route.data ? newerRoute(s.route, route.data as RouteRow) : s.route,
        position: pos.data ? newer(s.position, pos.data as PositionRow) : s.position,
        cue: cue.data ? newer(s.cue, cue.data as CueRow) : s.cue,
      }))
    })()

    return () => {
      cancelled = true
      void db.removeChannel(channel)
    }
  }, [incidentId, useFixtures])

  if (useFixtures) return fixtureState
  // Drop rows left over from a previous incident id until the new ones arrive.
  if (live.key !== incidentId) return { ...empty, source: 'supabase' }
  const { key: _key, ...state } = live
  return state
}
