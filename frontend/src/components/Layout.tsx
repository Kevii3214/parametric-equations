import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useDemoReason, useExitDemo } from '../lib/demo'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium transition-colors sm:px-3.5 ${
    isActive ? 'bg-card text-ink shadow-card' : 'text-ink-2 hover:text-ink'
  }`

export default function Layout() {
  // Keep ?incident= and ?demo= when switching pages, so Medic follows the
  // incident that Dispatch just created.
  const { search } = useLocation()
  const demo = useDemoReason()
  const exitDemo = useExitDemo()
  return (
    <div className="flex h-full flex-col bg-paper text-ink">
      <header className="sticky top-0 z-10 border-b border-line bg-paper/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
          <span className="flex items-center gap-2">
            <Mark />
            <span className="hidden text-[15px] font-semibold tracking-tight sm:inline">Pairatech</span>
          </span>
          <nav className="ml-2 flex gap-0.5 rounded-full bg-sunk p-0.5">
            <NavLink to={{ pathname: '/pre-arrival', search }} className={linkClass}>Pre-arrival</NavLink>
            <NavLink to={{ pathname: '/arrival', search }} className={linkClass}>Arrival</NavLink>
          </nav>
          {demo === 'param' ? (
            // ?demo=1 carries across pages, so make it loud and easy to leave.
            <span className="ml-auto flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-amber-soft py-0.5 pr-0.5 pl-2.5 text-xs font-semibold text-amber">
              DEMO<span className="hidden sm:inline"> · sample data</span>
              <button type="button" onClick={exitDemo}
                className="rounded-full bg-card px-2 py-0.5 font-medium text-ink shadow-card hover:text-azure">
                Exit demo
              </button>
            </span>
          ) : demo === 'no-supabase' ? (
            <span className="ml-auto flex items-center gap-1.5 rounded-full bg-amber-soft px-2.5 py-1 text-xs font-semibold text-amber"
              title="This build has no VITE_SUPABASE_* values, so live updates cannot be shown">
              DEMO · Supabase not configured
            </span>
          ) : (
            <span className="ml-auto flex items-center gap-1.5 rounded-full bg-fern-soft px-2.5 py-1 text-xs font-medium text-fern-deep">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-fern" />
              Live
            </span>
          )}
        </div>
      </header>
      <main className="flex-1 px-4 py-5">
        <Outlet />
      </main>
    </div>
  )
}

/** Logo: a route line ending in a destination dot, blue into green. */
function Mark() {
  return (
    <svg viewBox="0 0 28 28" className="h-7 w-7" aria-hidden="true">
      <defs>
        <linearGradient id="mark-g" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="var(--color-azure)" />
          <stop offset="1" stopColor="var(--color-fern)" />
        </linearGradient>
      </defs>
      <rect width="28" height="28" rx="8" fill="url(#mark-g)" />
      <path d="M8 20V13a3 3 0 0 1 3-3h7" fill="none" stroke="white" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="19.5" cy="10" r="2.6" fill="white" />
    </svg>
  )
}
