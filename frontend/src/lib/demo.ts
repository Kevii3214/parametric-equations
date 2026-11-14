import { useSearchParams } from 'react-router-dom'
import { supabaseConfigured } from './supabase'

export type DemoReason = 'param' | 'no-supabase' | null

/**
 * Why the app is showing sample data instead of live data, if it is:
 * ?demo=1 in the URL, or a build without Supabase env vars.
 */
export function useDemoReason(): DemoReason {
  const [params] = useSearchParams()
  if (params.get('demo') === '1') return 'param'
  return supabaseConfigured ? null : 'no-supabase'
}

/** Demo mode replays the fixtures instead of reading Supabase. */
export function useDemo(): boolean {
  return useDemoReason() !== null
}

/** Which demo building to replay: ?building=<CoStar id>. */
export function useDemoBuilding(): string | null {
  const [params] = useSearchParams()
  return params.get('building')
}

/** Leave ?demo=1 (and the sample incident) and go back to live data. */
export function useExitDemo(): () => void {
  const [, setParams] = useSearchParams()
  return () => setParams((p) => {
    p.delete('demo')
    p.delete('incident')
    return p
  })
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
