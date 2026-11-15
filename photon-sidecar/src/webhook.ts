import { Webhook } from 'standardwebhooks'

/** A text a person sent to our iMessage line, reduced to what the backend needs. */
export interface InboundText {
  /** webhook-id: the same across retries, so it is used to drop duplicates. */
  webhookId: string
  /** The sender's phone number (E.164) or email. */
  handle: string
  /** The Photon chat to reply into. */
  spaceId: string
  /** Our line's id in that chat: Photon's `senderId` when we send. */
  userId: string
  text: string
}

type Json = Record<string, unknown>
const obj = (value: unknown): Json => (value && typeof value === 'object' ? (value as Json) : {})
const str = (value: unknown): string => (typeof value === 'string' ? value : '')

/**
 * Check a Photon webhook delivery (Standard Webhooks: webhook-id, webhook-timestamp, webhook-signature over the
 * raw body) and pick out an inbound iMessage text. Throws if the signature is wrong or the timestamp is more than
 * five minutes off. Returns null for anything that is not a text from a person (other events, attachments, ...).
 */
export function verifyAndParse(rawBody: string, headers: Record<string, string>, secret: string): InboundText | null {
  const event = obj(new Webhook(secret).verify(rawBody, headers))
  if (event.type !== 'message.received') return null
  const message = obj(obj(event.data).object)
  if (message.platform !== 'imessage') return null
  const content = obj(message.content)
  if (content.type !== 'text') return null
  const text = str(content.text).trim()
  const handle = str(obj(message.sentBy).handle)
  const spaceId = str(obj(message.space).id)
  const userId = str(obj(message.receivedBy).id) || str(obj(message.addressedTo).id)
  if (!text || !handle || !spaceId || !userId) return null
  return { webhookId: headers['webhook-id'] ?? '', handle, spaceId, userId, text }
}
