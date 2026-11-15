import type { BackendApi } from './backend.js'
import type { PhotonApi } from './photon.js'
import type { InboundText } from './webhook.js'

const CHANNEL = 'imessage'
const SEEN_LIMIT = 2000

/**
 * Handles texts from the crew. Looks the sender up by phone number (the backend also remembers their chat so it
 * can message them later), hands the text to the backend's crew-report endpoint, and posts whatever replies come
 * back into the same chat. Texts from people who are not on an active incident are dropped silently.
 */
export function createInbound(backend: BackendApi, photon: PhotonApi, log: (line: string) => void = console.log) {
  const seen = new Set<string>()
  return async function handle(message: InboundText): Promise<void> {
    // Photon retries a delivery until it gets a 2xx, and the same webhook-id comes with every retry.
    if (message.webhookId) {
      if (seen.has(message.webhookId)) return
      seen.add(message.webhookId)
      if (seen.size > SEEN_LIMIT) seen.delete(seen.values().next().value as string)
    }
    const thread = await backend.resolve(message.handle, message.spaceId, message.userId)
    if (!thread) {
      log(`ignored a text from ${message.handle}: not on an active incident`)
      return
    }
    const replies = await backend.crewReport(thread.incidentId, message.text, message.handle, CHANNEL)
    for (const reply of replies) await photon.sendText(message.spaceId, message.userId, reply)
  }
}
