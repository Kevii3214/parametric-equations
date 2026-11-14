import type { PlanStepKind, PlanStepRow } from '../lib/contracts'

const kindStyle: Record<PlanStepKind, { label: string; dot: string; text: string }> = {
  plan: { label: 'Plan', dot: 'bg-ink', text: 'text-ink' },
  subagent: { label: 'Subagent', dot: 'bg-azure', text: 'text-azure-deep' },
  tool_call: { label: 'Tool call', dot: 'bg-ink-3', text: 'text-ink-2' },
  tool_result: { label: 'Result', dot: 'bg-fern', text: 'text-fern-deep' },
  replan: { label: 'Replan', dot: 'bg-amber', text: 'text-amber' },
  final: { label: 'Final', dot: 'bg-fern', text: 'text-fern-deep' },
}

function time(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Detail({ step }: { step: PlanStepRow }) {
  const list = step.detail?.steps
  if (step.kind === 'plan' && Array.isArray(list)) {
    return (
      <ol className="mt-2 space-y-1 text-[13px] text-ink-2">
        {list.map((s, i) => (
          <li key={i} className="flex gap-2">
            <span className="w-4 shrink-0 text-right font-mono text-[11px] leading-5 text-ink-3">{i + 1}</span>
            {String(s)}
          </li>
        ))}
      </ol>
    )
  }
  if (!step.detail) return null
  return (
    <details className="group mt-1.5">
      <summary className="cursor-pointer list-none text-xs text-ink-3 hover:text-azure">
        <span className="group-open:hidden">Show detail</span>
        <span className="hidden group-open:inline">Hide detail</span>
      </summary>
      <pre className="mt-1.5 overflow-x-auto rounded-lg bg-sunk p-2.5 font-mono text-[11px] leading-snug text-ink-2">
        {JSON.stringify(step.detail, null, 2)}
      </pre>
    </details>
  )
}

/** The agent's steps (plan_steps) as a timeline, in seq order. */
export default function PlanTrace({ steps: rows, waiting }: { steps: PlanStepRow[]; waiting: boolean }) {
  // Realtime rows can arrive out of order; always show them by seq.
  const steps = [...rows].sort((a, b) => a.seq - b.seq)
  return (
    <ol className="relative">
      {steps.map((s, i) => {
        const k = kindStyle[s.kind] ?? kindStyle.tool_call
        const last = i === steps.length - 1 && !waiting
        return (
          <li key={s.id} className="trace-in relative pb-4 pl-6">
            {!last && <span className="absolute top-3 bottom-0 left-[5px] w-px bg-line" aria-hidden="true" />}
            <span className={`absolute top-1.5 left-0 h-[11px] w-[11px] rounded-full ring-4 ring-card ${k.dot}`} aria-hidden="true" />
            <div className="flex items-baseline gap-2">
              <span className={`text-[11px] font-semibold uppercase tracking-[0.06em] ${k.text}`}>{k.label}</span>
              <span className="ml-auto font-mono text-[11px] text-ink-3">{time(s.created_at)}</span>
            </div>
            <p className={`mt-0.5 text-sm leading-snug ${s.kind === 'tool_call' ? 'font-mono text-[13px] text-ink-2' : 'text-ink'}`}>
              {s.title}
            </p>
            <Detail step={s} />
          </li>
        )
      })}
      {waiting && (
        <li className="relative flex items-center gap-2 pl-6 text-sm text-ink-3">
          <span className="absolute top-1.5 left-0 h-[11px] w-[11px] animate-pulse rounded-full bg-azure" />
          Agent working…
        </li>
      )}
    </ol>
  )
}
