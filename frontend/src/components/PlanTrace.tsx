import type { PlanStepKind, PlanStepRow } from '../lib/contracts'

const kindStyle: Record<PlanStepKind, { label: string; className: string }> = {
  plan: { label: 'Plan', className: 'bg-slate-700 text-slate-100' },
  subagent: { label: 'Subagent', className: 'bg-indigo-900 text-indigo-200' },
  tool_call: { label: 'Tool call', className: 'bg-slate-800 text-slate-300' },
  tool_result: { label: 'Result', className: 'bg-emerald-900 text-emerald-200' },
  replan: { label: 'Replan', className: 'bg-amber-900 text-amber-200' },
  final: { label: 'Final', className: 'bg-sky-900 text-sky-200' },
}

function time(iso: string) {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function Detail({ step }: { step: PlanStepRow }) {
  const list = step.detail?.steps
  if (step.kind === 'plan' && Array.isArray(list)) {
    return (
      <ol className="mt-1.5 list-decimal space-y-0.5 pl-5 text-xs text-slate-400">
        {list.map((s, i) => <li key={i}>{String(s)}</li>)}
      </ol>
    )
  }
  if (!step.detail) return null
  return (
    <details className="mt-1">
      <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300">detail</summary>
      <pre className="mt-1 overflow-x-auto rounded bg-slate-950 p-2 text-[11px] leading-snug text-slate-400">
        {JSON.stringify(step.detail, null, 2)}
      </pre>
    </details>
  )
}

/** The agent's steps (plan_steps), one row per step, in seq order. */
export default function PlanTrace({ steps, waiting }: { steps: PlanStepRow[]; waiting: boolean }) {
  return (
    <ol className="space-y-2">
      {steps.map((s) => {
        const k = kindStyle[s.kind] ?? kindStyle.tool_call
        return (
          <li key={s.id} className="trace-in rounded-lg border border-slate-800 bg-slate-900/60 p-2.5">
            <div className="flex items-center gap-2">
              <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${k.className}`}>
                {k.label}
              </span>
              <span className="ml-auto font-mono text-[11px] text-slate-500">{time(s.created_at)}</span>
            </div>
            <p className={`mt-1.5 text-sm ${s.kind === 'tool_call' ? 'font-mono text-slate-300' : 'text-slate-100'}`}>
              {s.title}
            </p>
            <Detail step={s} />
          </li>
        )
      })}
      {waiting && (
        <li className="flex items-center gap-2 px-1 text-sm text-slate-500">
          <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" /> Agent working…
        </li>
      )}
    </ol>
  )
}
