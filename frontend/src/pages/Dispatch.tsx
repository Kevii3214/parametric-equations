import { useState, type FormEvent } from 'react'
import Icon from '../components/Icon'
import AerialSite from '../components/AerialSite'
import CueIcon from '../components/CueIcon'
import Panel, { Chip } from '../components/Panel'
import PlanTrace from '../components/PlanTrace'
import SiteImagery from '../components/site/SiteImagery'
import { createIncident } from '../lib/api'
import { fixtureIncident } from '../lib/fixtures'
import { buildingById, buildingForNote, buildingForRoute, inCostar, patientFloor, SAMPLE_CALLS, type Building } from '../lib/buildings'
import type { IncidentRow, PlanStepRow, RouteRow } from '../lib/contracts'
import { useDemoBuilding, useDemoReason, useExitDemo, useIncidentParam, type DemoReason } from '../lib/demo'
import { graphFor, parsedNote, recordsResult } from '../lib/incident'
import { formatSeconds, nodeMap, tidy } from '../lib/route'
import { useIncidentLive } from '../lib/useIncidentLive'


export default function Dispatch() {
  const reason = useDemoReason()
  const demo = reason !== null
  const [incidentId, setIncidentId] = useIncidentParam()
  const live = useIncidentLive(incidentId, demo, useDemoBuilding())
  const started = live.source === 'fixtures' || incidentId !== null
  const building = buildingById(live.incident?.building_id)
    ?? buildingForRoute(live.route?.steps.flatMap((s) => [s.from_node, s.to_node]) ?? [])
  // The agent finished (a final step) but saved no route: it gave up.
  const finalStep = live.planSteps.findLast((s) => s.kind === 'final')
  const gaveUp = live.source === 'supabase' && !!finalStep && !live.route
  const demoFor = buildingForNote(live.incident?.note ?? '')
  const working = started && live.incident?.status !== 'en_route' && live.incident?.status !== 'arrived'
    && !live.planSteps.some((s) => s.kind === 'final')

  return (
    <div className="mx-auto grid max-w-7xl gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-5">
        <CallIntake reason={reason} onCreated={setIncidentId} />
        {live.incident && <IncidentBar incident={live.incident} source={live.source} gaveUp={gaveUp} />}
        {gaveUp && (
          <div role="alert" className="rounded-2xl border border-amber/30 bg-amber-soft px-4 py-3">
            <p className="text-sm font-semibold text-ink">The agent finished without a route</p>
            <p className="mt-1 text-sm text-ink-2">{finalStep!.title.replace(/^Final:\s*/, '')}</p>
            <p className="mt-1 text-xs text-ink-3">
              The server could not match this building, so nothing was routed. If the building is one of the demo
              buildings, the server may be running an older snapshot.
            </p>
            {demoFor && (
              <button type="button" onClick={() => setIncidentId(fixtureIncident.id, demoFor)}
                className="mt-2.5 rounded-full bg-azure px-4 py-1.5 text-sm font-semibold text-white hover:bg-azure-deep">
                Show the demo route for {buildingById(demoFor)?.record.name ?? 'this building'}
              </button>
            )}
          </div>
        )}
        {building ? (
          <>
            <SiteImagery building={building} entranceNode={live.route?.entrance_node ?? null}
              patientFloor={patientFloor(building, live.incident?.parsed ?? null)} steps={live.route?.steps} />
            <div className="grid gap-5 md:grid-cols-2">
              <CostarCard building={building} incident={live.incident} steps={live.planSteps} />
              <RouteSummary route={live.route} started={started && !gaveUp} />
            </div>
          </>
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            <RecordCard incident={live.incident} steps={live.planSteps} started={started && !gaveUp} />
            <AerialCard route={live.route} started={started && !gaveUp} />
            <RouteSummary route={live.route} started={started && !gaveUp} className="md:col-span-2" />
          </div>
        )}
      </div>
      <Panel title="Agent plan trace" className="xl:sticky xl:top-20 xl:max-h-[calc(100vh-7rem)]"
        aside={<Chip>{live.planSteps.length} steps</Chip>}>
        <div className="-mr-2 pr-2 xl:max-h-[calc(100vh-11.5rem)] xl:overflow-y-auto">
          {started || live.planSteps.length
            ? <PlanTrace steps={live.planSteps} waiting={working} />
            : <Empty>The agent's steps appear here as it works.</Empty>}
        </div>
      </Panel>
    </div>
  )
}

type IntakeMsg =
  | { kind: 'ok' | 'waking' | 'error'; text: string }
  | { kind: 'demo' | 'no-supabase' | 'unreachable'; text: string; note: string }

function CallIntake({ reason, onCreated }: { reason: DemoReason; onCreated: (id: string, demoBuilding?: string | null) => void }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<IntakeMsg | null>(null)
  const exitDemo = useExitDemo()

  async function submit(e?: FormEvent, again?: string) {
    e?.preventDefault()
    const text = (again ?? note).trim()
    if (!text || busy) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await createIncident(text, reason !== null, () =>
        setMsg({ kind: 'waking', text: 'Waking up the server, this can take up to a minute…' }))
      // Live incidents follow the server; a fallback replays the building the note names.
      onCreated(r.incident_id, r.live ? null : buildingForNote(text))
      if (r.live) setMsg({ kind: 'ok', text: `Incident ${r.incident_id.slice(0, 8)} created. The agent is planning.` })
      else if (reason === 'param') setMsg({ kind: 'demo', note: text, text: 'Demo mode: nothing was sent, this is the sample incident.' })
      else if (reason === 'no-supabase') setMsg({ kind: 'no-supabase', note: text, text: 'This build has no Supabase settings, so live updates can’t be shown. Showing the sample incident.' })
      else setMsg({ kind: 'unreachable', note: text, text: 'The server didn’t answer for a minute, so this shows the sample incident.' })
    } catch (err) {
      setMsg({ kind: 'error', text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  const tone: Record<IntakeMsg['kind'], string> = {
    ok: 'text-fern-deep', waking: 'text-azure-deep', demo: 'text-amber',
    'no-supabase': 'text-amber', unreachable: 'text-alert', error: 'text-alert',
  }
  const linkBtn = 'rounded-full bg-card px-3 py-1 text-xs font-semibold text-ink shadow-card ring-1 ring-line hover:text-azure'

  return (
    <form onSubmit={submit} className="rounded-2xl border border-line bg-card p-4 shadow-card">
      <div className="flex items-baseline justify-between">
        <label htmlFor="call-note" className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">
          Call intake
        </label>
        <span className="hidden text-[11px] text-ink-3 sm:inline">⌘ / Ctrl + Enter to send</span>
      </div>
      <textarea id="call-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2}
        placeholder={`e.g. ${SAMPLE_CALLS[0].note}`}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit() }}
        className="mt-2 w-full resize-y rounded-xl border border-line bg-paper/60 px-3.5 py-2.5 text-[15px] text-ink placeholder:text-ink-3 transition focus:border-azure focus:bg-card focus:ring-4 focus:ring-azure-soft focus:outline-none" />
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-ink-3">Sample calls</span>
        {SAMPLE_CALLS.map((c) => (
          <button key={c.building} type="button" onClick={() => setNote(c.note)} title={c.note}
            className={`rounded-full px-3 py-1 text-xs font-medium transition ${
              note === c.note ? 'bg-azure text-white' : 'bg-sunk text-ink-2 hover:bg-azure-soft hover:text-azure-deep'}`}>
            {c.label}
          </button>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy || !note.trim()}
          className="rounded-full bg-azure px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-azure-deep disabled:cursor-not-allowed disabled:bg-line-strong disabled:shadow-none">
          {busy ? (msg?.kind === 'waking' ? 'Waking server…' : 'Sending…') : 'Dispatch'}
        </button>

        {msg && (
          <span role="status" className={`flex flex-wrap items-center gap-2 text-sm ${tone[msg.kind]}`}>
            {msg.kind === 'waking' && <span className="h-2 w-2 animate-pulse rounded-full bg-azure" />}
            {msg.text}
            {msg.kind === 'unreachable' && (
              <button type="button" className={linkBtn} onClick={() => void submit(undefined, msg.note)}>Try live again</button>
            )}
            {msg.kind === 'demo' && <button type="button" className={linkBtn} onClick={exitDemo}>Exit demo</button>}
          </span>
        )}
      </div>
    </form>
  )
}

const statusTone: Record<string, 'neutral' | 'azure' | 'fern'> = {
  planning: 'neutral',
  routing: 'azure',
  en_route: 'azure',
  arrived: 'fern',
}

function IncidentBar({ incident, source, gaveUp }: { incident: IncidentRow; source: string; gaveUp?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-sm">
      <Chip tone={gaveUp ? 'amber' : statusTone[incident.status ?? ''] ?? 'neutral'}>
        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current" />
        {gaveUp ? 'no route' : (incident.status ?? 'unknown').replace('_', ' ')}
      </Chip>
      <span className="min-w-0 truncate font-medium text-ink">{incident.note}</span>
      <span className="ml-auto font-mono text-[11px] text-ink-3">
        {incident.id.slice(0, 8)}{source === 'fixtures' && ' · sample data'}
      </span>
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-8 text-center text-sm text-ink-3">{children}</p>
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="mt-0.5 truncate text-[15px] font-medium text-ink">{value ?? <span className="text-ink-3">—</span>}</dd>
    </div>
  )
}

const scalar = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? v : undefined)

function RecordCard({ incident, steps, started }: { incident: IncidentRow | null; steps: PlanStepRow[]; started: boolean }) {
  const note = parsedNote(incident?.parsed ?? null)
  const rec = recordsResult(steps)
  const elevators = Array.isArray(rec?.elevators) ? (rec.elevators as unknown[]).join(', ') : null
  const has = incident?.parsed || rec

  return (
    <Panel title="CoStar building record"
      aside={rec ? <Chip tone="fern"><Icon name="check" className="mr-1 h-3 w-3" />records subagent</Chip> : null}>
      {!has ? (
        <Empty>{started ? 'Waiting for the records subagent…' : 'Building facts appear after a call.'}</Empty>
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3.5">
          <div className="col-span-2"><Field label="Address" value={note.address} /></div>
          <Field label="Suite" value={scalar(rec?.suite) ?? note.suite} />
          <Field label="Floor" value={scalar(rec?.floor) ?? note.floor} />
          <Field label="Elevators" value={elevators} />
          <Field label="Parking" value={typeof rec?.parking === 'string' ? rec.parking : null} />
          <Field label="Complaint" value={note.complaint} />
          <Field label="Building id" value={incident?.building_id && <span className="font-mono text-xs">{incident.building_id}</span>} />
          {note.access_notes && <div className="col-span-2"><Field label="Access notes" value={note.access_notes} /></div>}
        </dl>
      )}
    </Panel>
  )
}

const CLASS = ['', 'A', 'B', 'C']

/** The real CoStar record for a known building, plus who is in the patient's suite. */
function CostarCard({ building, incident, steps }: { building: Building; incident: IncidentRow | null; steps: PlanStepRow[] }) {
  const r = building.record
  const note = parsedNote(incident?.parsed ?? null)
  const suite = String(note.suite ?? '')
  const tenant = r.current_tenants.find((t) => t.suite === suite)
  const floor = tenant?.floor_guess_from_suite ?? note.floor
  const lifts = r.elevators.filter((e) => e.count).map((e) => `${e.count} ${e.type.toLowerCase()}`).join(' · ')
  const covered = r.parking.find((p) => p.type === 'Covered' && p.spaces)
  const fromAgent = recordsResult(steps) !== null
  const costar = inCostar(building)
  const rating = r.building_rating ?? null

  return (
    <Panel title={costar ? 'CoStar building record' : 'Building record'}
      aside={!costar ? <Chip tone="amber">Not in CoStar · written by hand</Chip>
        : fromAgent ? <Chip tone="fern"><Icon name="check" className="mr-1 h-3 w-3" />records subagent</Chip> : <Chip>CoStar</Chip>}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-lg font-semibold leading-tight tracking-tight text-ink">{r.name}</p>
          <p className="text-sm text-ink-2">{r.address}, {r.city}, {r.state} {r.postcode}</p>
        </div>
        {r.building_class != null && (
          <span className="shrink-0 rounded-xl bg-azure-soft px-2.5 py-1.5 text-center leading-none text-azure-deep">
            <span className="block text-lg font-bold">{CLASS[r.building_class] ?? r.building_class}</span>
            <span className="block text-[10px] font-medium">Class</span>
          </span>
        )}
      </div>
      {(suite || floor) && (
        <div className="mt-3 flex items-center gap-3 rounded-xl border border-fern-line bg-fern-soft px-3 py-2.5">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-fern text-sm font-bold text-white">{floor ?? '?'}</span>
          <div className="min-w-0 text-sm">
            <div className="font-semibold text-fern-deep">
              {suite ? `Suite ${suite}${tenant?.company ? ` · ${tenant.company}` : ''}` : String(note.location ?? 'Patient location')}
            </div>
            <div className="text-fern-deep/80">Floor {floor ?? 'unknown'}{note.complaint ? ` · ${note.complaint}` : ''}</div>
          </div>
        </div>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3.5">
        <Field label="Stories" value={r.stories_above_grade} />
        <Field label="Rating" value={rating == null ? null : <span className="flex gap-0.5" aria-label={`${rating} of 5 stars`}>{[1, 2, 3, 4, 5].map((i) => <Icon key={i} name="star" className={`h-4 w-4 ${i <= rating ? 'text-amber' : 'text-line-strong'}`} />)}</span>} />
        <Field label="Elevators" value={lifts || (costar ? null : 'None in the scan')} />
        <Field label="Parking" value={covered ? `${covered.spaces!.toLocaleString()} covered` : null} />
        <Field label="Gross area" value={r.gross_area_sqft ? `${Math.round(r.gross_area_sqft).toLocaleString()} sq ft` : null} />
        <Field label={costar ? 'Tenants' : 'Use'} value={costar ? r.current_tenants.filter((t) => t.company).length : r.property_type} />
      </dl>
      {r.data_quality_notes.length > 0 && (
        <details className="group mt-4">
          <summary className="cursor-pointer list-none text-xs text-ink-3 hover:text-azure">
            {r.data_quality_notes.length} data-quality notes
          </summary>
          <ul className="mt-2 space-y-1.5 text-xs leading-snug text-ink-2">
            {r.data_quality_notes.map((n) => <li key={n} className="rounded-lg bg-sunk p-2">{n}</li>)}
          </ul>
        </details>
      )}
    </Panel>
  )
}

function AerialCard({ route, started }: { route: RouteRow | null; started: boolean }) {
  const graph = graphFor(route?.steps)
  const entrance = graph && route ? nodeMap(graph).get(route.entrance_node) : null
  return (
    <Panel title="Aerial · chosen entrance"
      aside={<span title="The Vexcel image is wired in with P2-2"><Chip>schematic</Chip></span>}>
      {graph && route ? (
        <figure>
          <AerialSite graph={graph} entranceNode={route.entrance_node} className="w-full rounded-xl" />
          <figcaption className="mt-3 flex items-center gap-2 text-sm text-ink-2">
            <span className="h-2 w-2 rounded-full bg-fern" />
            Stop at <span className="font-semibold text-ink">{entrance?.label ?? route.entrance_node}</span>
          </figcaption>
        </figure>
      ) : (
        <Empty>{started ? 'Waiting for the aerial subagent…' : 'Entrances appear after a call.'}</Empty>
      )}
    </Panel>
  )
}

function RouteSummary({ route, started, className }: { route: RouteRow | null; started: boolean; className?: string }) {
  if (!route) {
    return (
      <Panel title="Route" className={className}>
        <Empty>{started ? 'Waiting for a route…' : 'The route appears after a call.'}</Empty>
      </Panel>
    )
  }
  const graph = graphFor(route.steps)
  const nodes = graph ? nodeMap(graph) : null
  const meters = Math.round(route.steps.reduce((m, s) => m + s.meters, 0))
  const floors = [...new Set(route.steps.map((s) => s.floor))]

  return (
    <Panel title="Route" className={className}
      aside={<Chip tone="azure">version {route.version}</Chip>}>
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <Stat label="Door to patient" value={formatSeconds(route.total_seconds)} big />
        <Stat label="Walking" value={`${meters} m`} />
        <Stat label="Floors" value={floors.join(' → ')} />
        <Stat label="Entrance" value={tidy(nodes?.get(route.entrance_node)?.label ?? route.entrance_node)} />
      </div>
      {route.briefing && (
        <p className="mt-4 rounded-xl border border-azure-line bg-azure-soft p-3 text-sm text-azure-deep">{route.briefing}</p>
      )}
      <ol className="mt-4 divide-y divide-line">
        {route.steps.map((s) => (
          <li key={s.index} className="flex items-center gap-3 py-2">
            <span className={`grid h-7 w-7 shrink-0 place-items-center rounded-lg ${
              s.cue === 'ARRIVE' ? 'bg-fern-soft text-fern' : 'bg-azure-soft text-azure'}`}>
              <CueIcon cue={s.cue} className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1 text-sm text-ink">{tidy(s.text)}</span>
            <span className="shrink-0 font-mono text-[11px] text-ink-3 tabular-nums">
              {s.meters ? `${s.meters} m · ` : ''}{s.seconds} s
            </span>
          </li>
        ))}
      </ol>
    </Panel>
  )
}

function Stat({ label, value, big }: { label: string; value: React.ReactNode; big?: boolean }) {
  return (
    <div>
      <div className="text-[11px] text-ink-3">{label}</div>
      <div className={big ? 'mt-0.5 text-3xl font-semibold tracking-tight text-fern-deep tabular-nums' : 'mt-1 text-[15px] font-medium text-ink'}>{value}</div>
    </div>
  )
}
