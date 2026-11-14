import type { ReactNode } from 'react'

export default function Panel({
  title, aside, children, className = '',
}: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`flex min-w-0 flex-col rounded-xl border border-slate-800 bg-slate-900/40 ${className}`}>
      <header className="flex items-center justify-between gap-2 border-b border-slate-800 px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h2>
        {aside}
      </header>
      <div className="flex-1 p-3">{children}</div>
    </section>
  )
}
