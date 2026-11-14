// Client for Person 2's HTTP API (contracts/api.md). Until the server exists,
// or in demo mode, calls fall back to fake responses built from the fixtures.
import { API_URL } from './config'
import type { EventType } from './contracts'
import { fixtureIncident } from './fixtures'

export interface Telemetry {
  t: number
  steps: number
  heading: number
  pressure: number
  btn: 0 | 1 | 2
  tag: string | null
}

/** Render's free tier sleeps when idle and takes 30-60 s to wake. */
export const WAKE_BUDGET_MS = 60_000
const UP_FOR_MS = 60_000 // trust a good health check for this long
let lastUp = 0

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function healthOnce(timeoutMs: number): Promise<boolean> {
  try {
    const r = await fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(timeoutMs) })
    if (r.ok) lastUp = Date.now()
    return r.ok
  } catch {
    return false
  }
}

/**
 * Is the server up? Only success is cached (briefly); a failure is checked
 * again next time, so a sleeping server is not treated as down all session.
 */
export async function serverUp(timeoutMs = 4000): Promise<boolean> {
  if (Date.now() - lastUp < UP_FOR_MS) return true
  return healthOnce(timeoutMs)
}

/**
 * Wait for the server to answer /health, retrying with backoff for up to
 * `budgetMs`. `onWaking` fires once if the first quick check fails.
 */
export async function waitForServer(
  onWaking?: () => void,
  { budgetMs = WAKE_BUDGET_MS, quickMs = 4000 } = {},
): Promise<boolean> {
  if (await serverUp(quickMs)) return true
  onWaking?.()
  const deadline = Date.now() + budgetMs
  let backoff = 1000
  while (Date.now() < deadline) {
    // A waking Render instance holds the request open, so allow a long timeout.
    if (await healthOnce(Math.max(1000, Math.min(25_000, deadline - Date.now())))) return true
    await sleep(Math.min(backoff, Math.max(0, deadline - Date.now())))
    backoff = Math.min(backoff * 2, 8000)
  }
  return false
}

/** Reset the cached health state (tests). */
export function resetHealth() {
  lastUp = 0
}

async function post<T>(path: string, body: unknown, timeoutMs = 30_000): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`)
  return (await r.json()) as T
}

export interface Sent {
  /** False when the server was down and nothing left the browser. */
  live: boolean
}

export type CreateResult =
  | { live: true; incident_id: string }
  | { live: false; incident_id: string; reason: 'demo' | 'unreachable' }

/**
 * POST /incidents. In demo mode nothing is sent. Otherwise waits for a
 * sleeping server to wake (calling `onWaking`), and only falls back to the
 * sample incident if it stays unreachable.
 */
export async function createIncident(
  note: string,
  demo: boolean,
  onWaking?: () => void,
  wait?: { budgetMs?: number; quickMs?: number },
): Promise<CreateResult> {
  if (demo) return { live: false, incident_id: fixtureIncident.id, reason: 'demo' }
  if (!(await waitForServer(onWaking, wait))) return { live: false, incident_id: fixtureIncident.id, reason: 'unreachable' }
  const r = await post<{ incident_id: string }>('/incidents', { note })
  return { live: true, incident_id: r.incident_id }
}

export async function sendEvent(
  incidentId: string,
  type: EventType,
  text: string | null,
  demo: boolean,
): Promise<Sent> {
  if (demo || !(await serverUp())) return { live: false }
  await post(`/incidents/${incidentId}/events`, { type, text })
  return { live: true }
}

export async function sendTelemetry(incidentId: string, sample: Telemetry, demo: boolean): Promise<Sent> {
  if (demo || !(await serverUp())) return { live: false }
  await post(`/incidents/${incidentId}/telemetry`, sample)
  return { live: true }
}
