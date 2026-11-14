import { NavLink, Outlet } from 'react-router-dom'
import { supabaseConfigured } from '../lib/supabase'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm font-medium ${
    isActive ? 'bg-red-600 text-white' : 'text-slate-300 hover:bg-slate-800'
  }`

export default function Layout() {
  return (
    <div className="flex h-full flex-col bg-slate-950 text-slate-100">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-4">
          <span className="font-semibold tracking-tight">Last 100 Meters</span>
          <nav className="flex gap-1">
            <NavLink to="/dispatch" className={linkClass}>
              Dispatch
            </NavLink>
            <NavLink to="/medic" className={linkClass}>
              Medic
            </NavLink>
          </nav>
        </div>
        <span
          className={`text-xs ${supabaseConfigured ? 'text-emerald-400' : 'text-amber-400'}`}
        >
          {supabaseConfigured ? '● Supabase connected' : '● Supabase not configured'}
        </span>
      </header>
      <main className="flex-1 overflow-auto p-4">
        <Outlet />
      </main>
    </div>
  )
}
