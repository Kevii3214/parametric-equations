import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useDemo } from '../lib/demo'
import { supabaseConfigured } from '../lib/supabase'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
    isActive ? 'bg-card text-ink shadow-card' : 'text-ink-2 hover:text-ink'
  }`

export default function Layout() {
  // Keep ?incident= and ?demo= when switching pages, so Medic follows the
  // incident that Dispatch just created.
  const { search } = useLocation()
  const demo = useDemo()
  return (
    <div className="flex h-full flex-col bg-paper text-ink">
      <header className="sticky top-0 z-10 border-b border-line bg-paper/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
          <span className="flex items-center gap-2">
            <Mark />
            <span className="hidden text-[15px] font-semibold tracking-tight sm:inline">Pairatech</span>
          </span>
          <nav className="ml-2 flex gap-0.5 rounded-full bg-sunk p-0.5">
            <NavLink to={{ pathname: '/dispatch', search }} className={linkClass}>Dispatch</NavLink>
            <NavLink to={{ pathname: '/medic', search }} className={linkClass}>Medic</NavLink>
          </nav>
          <span className={`ml-auto flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
            demo ? 'bg-azure-soft text-azure-deep' : 'bg-fern-soft text-fern-deep'}`}
            title={demo && !supabaseConfigured ? 'Supabase is not configured, so the sample incident is shown' : undefined}>
            <span className={`h-1.5 w-1.5 rounded-full ${demo ? 'bg-azure' : 'animate-pulse bg-fern'}`} />
            {demo ? 'Demo' : 'Live'}
          </span>
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
