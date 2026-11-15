import type { Config } from './config.js'

/** The backend calls the sidecar makes. Every one carries the shared secret. */
export interface BackendApi {
  /** Which active incident this text belongs to; null if the sender is not on one. Remembers the chat. */
  resolve(handle: string, spaceId: string, userId: string): Promise<{ incidentId: string; firstContact: boolean } | null>
  /** Hand a crew text to the agent side; returns the replies to post back in the same chat. */
  crewReport(incidentId: string, text: string, sender: string, channel: string): Promise<string[]>
}

export function createBackend(config: Config, fetchImpl: typeof fetch = fetch): BackendApi {
  const call = (path: string, body: unknown) =>
    fetchImpl(`${config.backendUrl}${path}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-photon-secret': config.sharedSecret },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(20_000),
    })
  return {
    async resolve(handle, spaceId, userId) {
      const res = await call('/crew-threads/resolve', { handle, space_id: spaceId, user_id: userId })
      if (res.status === 404) return null
      if (!res.ok) throw new Error(`backend /crew-threads/resolve answered ${res.status}`)
      const body = (await res.json()) as { incident_id: string; first_contact: boolean }
      return { incidentId: body.incident_id, firstContact: body.first_contact }
    },
    async crewReport(incidentId, text, sender, channel) {
      const res = await call(`/incidents/${encodeURIComponent(incidentId)}/crew-report`, { text, sender, channel })
      if (!res.ok) throw new Error(`backend crew-report answered ${res.status}`)
      const body = (await res.json()) as { replies?: string[] }
      return body.replies ?? []
    },
  }
}
