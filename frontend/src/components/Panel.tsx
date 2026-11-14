import type { ReactNode } from 'react'

export default function Panel({
  title, aside, children, className = '',
}: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-w-0 flex-col rounded-2xl border border-line bg-card shadow-card ${className}`}>
      <header className="flex items-center justify-between gap-2 px-4 pt-3.5 pb-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">{title}</h2>
        {aside}
      </header>
      <div className="flex-1 px-4 pt-2 pb-4">{children}</div>
    </section>
  )
}

/** Small rounded label used in panel headers and rows. */
export function Chip({ tone = 'neutral', children }: {
  tone?: 'neutral' | 'azure' | 'fern' | 'amber' | 'alert'; children: ReactNode
}) {
  const tones = {
    neutral: 'bg-sunk text-ink-2',
    azure: 'bg-azure-soft text-azure-deep',
    fern: 'bg-fern-soft text-fern-deep',
    amber: 'bg-amber-soft text-amber',
    alert: 'bg-alert-soft text-alert',
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${tones[tone]}`}>
      {children}
    </span>
  )
}
