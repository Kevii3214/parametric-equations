import { useState, type FormEvent } from 'react'
import AerialSite from '../components/AerialSite'
import CueIcon from '../components/CueIcon'
import Panel, { Chip } from '../components/Panel'
import PlanTrace from '../components/PlanTrace'
import SiteImagery from '../components/site/SiteImagery'
import { createIncident } from '../lib/api'
import { buildingById, buildingForRoute, type Building } from '../lib/buildings'
import type { IncidentRow, PlanStepRow, RouteRow } from '../lib/contracts'
import { useDemo, useIncidentParam } from '../lib/demo'
import { graphFor, parsedNote, recordsResult } from '../lib/incident'
import { formatSeconds, nodeMap } from '../lib/route'
import { useIncidentLive } from '../lib/useIncidentLive'

const SAMPLE_NOTE = '65M chest pain, Suite 1800, 1415 Louisiana St'

export default function Dispatch() {
  const demo = useDemo()
  const [incidentId, setIncidentId] = useIncidentParam()
  const live = useIncidentLive(incidentId, demo)
  const started = live.source === 'fixtures' || incidentId !== null
  const building = buildingById(live.incident?.building_id)
    ?? buildingForRoute(live.route?.steps.flatMap((s) => [s.from_node, s.to_node]) ?? [])
  const working = started && live.incident?.status !== 'en_route' && live.incident?.status !== 'arrived'
    && !live.planSteps.some((s) => s.kind === 'final')

  return (
    <div className="mx-auto grid max-w-7xl gap-5 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-5">
        <CallIntake demo={demo} onCreated={setIncidentId} />
        {live.incident && <IncidentBar incident={live.incident} source={live.source} />}
        {building ? (
          <>
            <SiteImagery building={building} entranceNode={live.route?.entrance_node ?? null} />
            <div className="grid gap-5 md:grid-cols-2">
              <CostarCard building={building} incident={live.incident} steps={live.planSteps} />
              <RouteSummary route={live.route} started={started} />
            </div>
          </>
        ) : (
          <div className="grid gap-5 md:grid-cols-2">
            <RecordCard incident={live.incident} steps={live.planSteps} started={started} />
            <AerialCard route={live.route} started={started} />
            <RouteSummary route={live.route} started={started} className="md:col-span-2" />
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

function CallIntake({ demo, onCreated }: { demo: boolean; onCreated: (id: string) => void }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'warn' | 'err'; text: string } | null>(null)

  async function submit(e?: FormEvent) {
    e?.preventDefault()
    const text = note.trim()
    if (!text || busy) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await createIncident(text, demo)
      onCreated(r.incident_id)
      setMsg(r.live
        ? { tone: 'ok', text: `Incident ${r.incident_id.slice(0, 8)} created. The agent is planning.` }
        : { tone: 'warn', text: 'Server not reachable, so this shows the sample incident instead.' })
    } catch (err) {
      setMsg({ tone: 'err', text: err instanceof Error ? err.message : String(err) })
    } finally {
      setBusy(false)
    }
  }

  const tone = { ok: 'text-fern-deep', warn: 'text-amber', err: 'text-alert' }

  return (
    <form onSubmit={submit} className="rounded-2xl border border-line bg-card p-4 shadow-card">
      <div className="flex items-baseline justify-between">
        <label htmlFor="call-note" className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">
          Call intake
        </label>
        <span className="hidden text-[11px] text-ink-3 sm:inline">⌘ / Ctrl + Enter to send</span>
      </div>
      <textarea id="call-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2}
        placeholder={`e.g. ${SAMPLE_NOTE}`}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit() }}
        className="mt-2 w-full resize-y rounded-xl border border-line bg-paper/60 px-3.5 py-2.5 text-[15px] text-ink placeholder:text-ink-3 transition focus:border-azure focus:bg-card focus:ring-4 focus:ring-azure-soft focus:outline-none" />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy || !note.trim()}
          className="rounded-full bg-azure px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-azure-deep disabled:cursor-not-allowed disabled:bg-line-strong disabled:shadow-none">
          {busy ? 'Sending…' : 'Dispatch'}
        </button>
        {!note && (
          <button type="button" onClick={() => setNote(SAMPLE_NOTE)}
            className="rounded-full px-3 py-2 text-sm text-ink-2 transition hover:bg-sunk hover:text-ink">
            Use sample call
          </button>
        )}
        {msg && <span className={`text-sm ${tone[msg.tone]}`}>{msg.text}</span>}
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

function IncidentBar({ incident, source }: { incident: IncidentRow; source: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-sm">
      <Chip tone={statusTone[incident.status ?? ''] ?? 'neutral'}>
        <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current" />
        {(incident.status ?? 'unknown').replace('_', ' ')}
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
      aside={rec ? <Chip tone="fern">✓ records subagent</Chip> : null}>
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

  return (
    <Panel title="CoStar building record" aside={fromAgent ? <Chip tone="fern">✓ records subagent</Chip> : <Chip>CoStar</Chip>}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-lg font-semibold leading-tight tracking-tight text-ink">{r.name}</p>
          <p className="text-sm text-ink-2">{r.address}, {r.city}, {r.state} {r.postcode}</p>
        </div>
        <span className="shrink-0 rounded-xl bg-azure-soft px-2.5 py-1.5 text-center leading-none text-azure-deep">
          <span className="block text-lg font-bold">{CLASS[r.building_class] ?? r.building_class}</span>
          <span className="block text-[10px] font-medium">Class</span>
        </span>
      </div>
      {suite && (
        <div className="mt-3 flex items-center gap-3 rounded-xl border border-fern-line bg-fern-soft px-3 py-2.5">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-fern text-sm font-bold text-white">{floor ?? '?'}</span>
          <div className="min-w-0 text-sm">
            <div className="font-semibold text-fern-deep">Suite {suite}{tenant?.company ? ` · ${tenant.company}` : ''}</div>
            <div className="text-fern-deep/80">Floor {floor ?? 'unknown'}{note.complaint ? ` · ${note.complaint}` : ''}</div>
          </div>
        </div>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3.5">
        <Field label="Stories" value={r.stories_above_grade} />
        <Field label="Rating" value={<span className="text-amber">{'★'.repeat(r.building_rating)}<span className="text-line-strong">{'★'.repeat(Math.max(0, 5 - r.building_rating))}</span></span>} />
        <Field label="Elevators" value={lifts} />
        <Field label="Parking" value={covered ? `${covered.spaces!.toLocaleString()} covered` : null} />
        <Field label="Gross area" value={`${Math.round(r.gross_area_sqft).toLocaleString()} sq ft`} />
        <Field label="Tenants" value={r.current_tenants.filter((t) => t.company).length} />
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
        <Stat label="Entrance" value={nodes?.get(route.entrance_node)?.label ?? route.entrance_node} />
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
            <span className="min-w-0 flex-1 text-sm text-ink">{s.text}</span>
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
