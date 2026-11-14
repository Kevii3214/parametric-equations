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

let health: Promise<boolean> | null = null

/** GET /health once per page load. False means use fake responses. */
export function serverUp(): Promise<boolean> {
  health ??= fetch(`${API_URL}/health`, { signal: AbortSignal.timeout(2000) })
    .then((r) => r.ok)
    .catch(() => false)
  return health
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path}: ${r.status} ${await r.text()}`)
  return (await r.json()) as T
}

export interface Sent {
  /** False when the server was down and nothing left the browser. */
  live: boolean
}

export async function createIncident(note: string, demo: boolean): Promise<{ incident_id: string } & Sent> {
  if (demo || !(await serverUp())) return { incident_id: fixtureIncident.id, live: false }
  const r = await post<{ incident_id: string }>('/incidents', { note })
  return { ...r, live: true }
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
