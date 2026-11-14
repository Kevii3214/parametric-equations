import { useSearchParams } from 'react-router-dom'
import { supabaseConfigured } from './supabase'

/**
 * Demo mode replays the fixtures instead of reading Supabase. It is on when
 * Supabase is not configured, or when the URL has ?demo=1.
 */
export function useDemo(): boolean {
  const [params] = useSearchParams()
  return !supabaseConfigured || params.get('demo') === '1'
}

/** The incident both pages follow, kept in ?incident=<uuid>. */
export function useIncidentParam(): [string | null, (id: string) => void] {
  const [params, setParams] = useSearchParams()
  const set = (id: string) =>
    setParams((p) => {
      p.set('incident', id)
      return p
    })
  return [params.get('incident'), set]
}
