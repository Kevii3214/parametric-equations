import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useDemo } from '../lib/demo'
import { supabaseConfigured } from '../lib/supabase'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm font-medium ${
    isActive ? 'bg-red-600 text-white' : 'text-slate-300 hover:bg-slate-800'
  }`

export default function Layout() {
  // Keep ?incident= and ?demo= when switching pages, so Medic follows the
  // incident that Dispatch just created.
  const { search } = useLocation()
  const demo = useDemo()
  return (
    <div className="flex h-full flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-4">
          <span className="font-semibold tracking-tight">Last 100 Meters</span>
          <nav className="flex gap-1">
            <NavLink to={{ pathname: '/dispatch', search }} className={linkClass}>
              Dispatch
            </NavLink>
            <NavLink to={{ pathname: '/medic', search }} className={linkClass}>
              Medic
            </NavLink>
          </nav>
        </div>
        <span className={`text-xs ${demo ? 'text-amber-400' : 'text-emerald-400'}`}>
          {demo
            ? supabaseConfigured ? '● Demo mode' : '● Demo mode (Supabase not configured)'
            : '● Live'}
        </span>
      </header>
      <main className="flex-1 overflow-auto p-4">
        <Outlet />
      </main>
    </div>
  )
}
