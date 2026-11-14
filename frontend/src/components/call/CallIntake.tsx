import { useState, type FormEvent } from 'react'
import { createIncident } from '../../lib/api'
import { buildingForNote, SAMPLE_CALLS } from '../../lib/buildings'
import { useExitDemo, type DemoReason } from '../../lib/demo'

type IntakeMsg =
  | { kind: 'ok' | 'waking' | 'error'; text: string }
  | { kind: 'demo' | 'no-supabase' | 'unreachable'; text: string; note: string }

/** The new-call box: type a call or pick a sample call, then dispatch it to the server. */
export default function CallIntake({ reason, onCreated }: { reason: DemoReason; onCreated: (id: string, demoBuilding?: string | null) => void }) {
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

