import { useState, type FormEvent } from 'react'
import AerialSite from '../components/AerialSite'
import CueIcon from '../components/CueIcon'
import Panel from '../components/Panel'
import PlanTrace from '../components/PlanTrace'
import { createIncident } from '../lib/api'
import type { IncidentRow, PlanStepRow, RouteRow } from '../lib/contracts'
import { useDemo, useIncidentParam } from '../lib/demo'
import { graphFor, parsedNote, recordsResult } from '../lib/incident'
import { formatSeconds, nodeMap } from '../lib/route'
import { useIncidentLive } from '../lib/useIncidentLive'

const SAMPLE_NOTE = '65M chest pain, Suite 1420, 1000 Main St'

export default function Dispatch() {
  const demo = useDemo()
  const [incidentId, setIncidentId] = useIncidentParam()
  const live = useIncidentLive(incidentId, demo)
  const started = live.source === 'fixtures' || incidentId !== null
  const working = started && live.incident?.status !== 'en_route' && live.incident?.status !== 'arrived'
    && !live.planSteps.some((s) => s.kind === 'final')

  return (
    <div className="mx-auto grid max-w-7xl gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-4">
        <CallIntake demo={demo} onCreated={setIncidentId} />
        {live.incident && <IncidentBar incident={live.incident} source={live.source} />}
        <div className="grid gap-4 md:grid-cols-2">
          <RecordCard incident={live.incident} steps={live.planSteps} started={started} />
          <AerialCard route={live.route} started={started} />
          <RouteSummary route={live.route} started={started} className="md:col-span-2" />
        </div>
      </div>
      <Panel title="Agent plan trace" className="xl:sticky xl:top-0 xl:max-h-[calc(100vh-6rem)]"
        aside={<span className="text-xs text-slate-500">{live.planSteps.length} steps</span>}>
        <div className="xl:max-h-[calc(100vh-10rem)] xl:overflow-y-auto">
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

  const tone = { ok: 'text-emerald-400', warn: 'text-amber-400', err: 'text-red-400' }

  return (
    <form onSubmit={submit} className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
      <label htmlFor="call-note" className="text-xs font-semibold uppercase tracking-wider text-slate-400">
        Call intake
      </label>
      <textarea id="call-note" value={note} onChange={(e) => setNote(e.target.value)} rows={2}
        placeholder={`e.g. ${SAMPLE_NOTE}`}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void submit() }}
        className="mt-2 w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none" />
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy || !note.trim()}
          className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-40">
          {busy ? 'Sending…' : 'Dispatch'}
        </button>
        {!note && (
          <button type="button" onClick={() => setNote(SAMPLE_NOTE)}
            className="text-xs text-slate-500 underline-offset-2 hover:text-slate-300 hover:underline">
            Use sample call
          </button>
        )}
        {msg && <span className={`text-sm ${tone[msg.tone]}`}>{msg.text}</span>}
        <span className="ml-auto hidden text-xs text-slate-600 sm:inline">⌘/Ctrl + Enter</span>
      </div>
    </form>
  )
}

const statusStyle: Record<string, string> = {
  planning: 'bg-slate-700 text-slate-100',
  routing: 'bg-indigo-900 text-indigo-200',
  en_route: 'bg-sky-900 text-sky-200',
  arrived: 'bg-emerald-900 text-emerald-200',
}

function IncidentBar({ incident, source }: { incident: IncidentRow; source: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
      <span className={`rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${statusStyle[incident.status ?? ''] ?? 'bg-slate-800 text-slate-300'}`}>
        {(incident.status ?? 'unknown').replace('_', ' ')}
      </span>
      <span className="min-w-0 truncate text-slate-200">{incident.note}</span>
      <span className="ml-auto font-mono text-xs text-slate-500">
        {incident.id.slice(0, 8)}{source === 'fixtures' && ' · sample data'}
      </span>
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="truncate text-sm text-slate-100">{value ?? <span className="text-slate-600">—</span>}</dd>
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
      aside={rec ? <span className="text-xs text-emerald-400">records subagent</span> : null}>
      {!has ? (
        <Empty>{started ? 'Waiting for the records subagent…' : 'Building facts appear after a call.'}</Empty>
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
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

function AerialCard({ route, started }: { route: RouteRow | null; started: boolean }) {
  const graph = graphFor(route?.steps)
  const entrance = graph && route ? nodeMap(graph).get(route.entrance_node) : null
  return (
    <Panel title="Aerial · chosen entrance"
      aside={<span className="text-xs text-slate-500" title="The Vexcel image is wired in with P2-2">schematic</span>}>
      {graph && route ? (
        <figure>
          <AerialSite graph={graph} entranceNode={route.entrance_node} className="w-full rounded-lg" />
          <figcaption className="mt-2 text-sm text-slate-300">
            Stop at <span className="font-semibold text-sky-300">{entrance?.label ?? route.entrance_node}</span>
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
  const meters = route.steps.reduce((m, s) => m + s.meters, 0)
  const floors = [...new Set(route.steps.map((s) => s.floor))]

  return (
    <Panel title="Route" className={className}
      aside={<span className="text-xs text-slate-500">version {route.version}</span>}>
      <div className="flex flex-wrap gap-x-8 gap-y-2">
        <Stat label="Door to patient" value={formatSeconds(route.total_seconds)} big />
        <Stat label="Walking" value={`${meters} m`} />
        <Stat label="Floors" value={floors.join(' → ')} />
        <Stat label="Entrance" value={nodes?.get(route.entrance_node)?.label ?? route.entrance_node} />
      </div>
      {route.briefing && (
        <p className="mt-3 rounded-lg border border-sky-900 bg-sky-950/40 p-2.5 text-sm text-sky-100">{route.briefing}</p>
      )}
      <ol className="mt-3 divide-y divide-slate-800/70">
        {route.steps.map((s) => (
          <li key={s.index} className="flex items-center gap-3 py-1.5">
            <CueIcon cue={s.cue} className="h-5 w-5 shrink-0 text-sky-400" />
            <span className="min-w-0 flex-1 text-sm text-slate-200">{s.text}</span>
            <span className="shrink-0 font-mono text-xs text-slate-500">
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
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className={big ? 'text-2xl font-bold text-slate-50' : 'text-sm font-medium text-slate-100'}>{value}</div>
    </div>
  )
}
