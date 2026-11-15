import { timingSafeEqual } from 'node:crypto'
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http'
import type { Config } from './config.js'
import type { PhotonApi } from './photon.js'
import type { InboundText } from './webhook.js'
import { verifyAndParse } from './webhook.js'

const MAX_BODY = 1_000_000

interface Deps {
  config: Config
  photon: PhotonApi
  /** Called for every verified inbound text, after the delivery has been acknowledged. */
  onInbound: (message: InboundText) => Promise<void>
  log?: (line: string) => void
  /** Downloads the route card picture to attach. Replaceable in tests. */
  fetchImage?: (url: string) => Promise<Uint8Array>
}

const MAX_IMAGE = 5_000_000

/** Fetch a PNG over http(s): small, and it must really be an image. */
export async function downloadImage(url: string): Promise<Uint8Array> {
  if (!/^https?:\/\//.test(url)) throw new Error('image_url must be http(s)')
  const res = await fetch(url, { signal: AbortSignal.timeout(15_000) })
  if (!res.ok) throw new Error(`image answered ${res.status}`)
  if (!(res.headers.get('content-type') ?? '').startsWith('image/png')) throw new Error('image is not a PNG')
  const bytes = new Uint8Array(await res.arrayBuffer())
  if (bytes.byteLength > MAX_IMAGE) throw new Error('image is too large')
  return bytes
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    let size = 0
    req.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size > MAX_BODY) {
        reject(new Error('body too large'))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

const sameSecret = (given: string | undefined, secret: string): boolean => {
  if (!given) return false
  const a = Buffer.from(given)
  const b = Buffer.from(secret)
  return a.length === b.length && timingSafeEqual(a, b)
}

function reply(res: ServerResponse, status: number, body?: unknown): void {
  res.writeHead(status, body === undefined ? {} : { 'content-type': 'application/json' })
  res.end(body === undefined ? undefined : JSON.stringify(body))
}

export function createApp({ config, photon, onInbound, log = console.log, fetchImage = downloadImage }: Deps): Server {
  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url ?? '/', 'http://sidecar')
      if (req.method === 'GET' && url.pathname === '/health') return reply(res, 200, { ok: true })

      if (req.method === 'POST' && url.pathname === '/photon/webhook') {
        const raw = await readBody(req)
        const headers = Object.fromEntries(
          Object.entries(req.headers).map(([k, v]) => [k, Array.isArray(v) ? (v[0] ?? '') : (v ?? '')]),
        )
        let message: InboundText | null
        try {
          message = verifyAndParse(raw, headers, config.webhookSecret)
        } catch {
          return reply(res, 401, { error: 'bad signature' })
        }
        reply(res, 204) // acknowledge first: Photon retries a slow answer, and the backend may take a few seconds
        if (message) {
          onInbound(message).catch((error: unknown) => log(`inbound text failed: ${String(error)}`))
        }
        return
      }

      if (req.method === 'POST' && (url.pathname === '/send' || url.pathname === '/assign')) {
        if (!sameSecret(req.headers['x-photon-secret'] as string | undefined, config.sharedSecret)) {
          return reply(res, 401, { error: 'bad secret' })
        }
        const body = JSON.parse((await readBody(req)) || '{}') as Record<string, unknown>
        if (url.pathname === '/assign') {
          const handle = typeof body.handle === 'string' ? body.handle : ''
          if (!handle) return reply(res, 422, { error: 'handle is required' })
          const name = typeof body.name === 'string' && body.name ? body.name : undefined
          const assigned = await photon.assign(handle, name)
          return reply(res, 200, { assigned_phone_number: assigned.assignedPhoneNumber, assignment_id: assigned.assignmentId })
        }
        const threadId = typeof body.thread_id === 'string' ? body.thread_id : ''
        const senderId = typeof body.sender_id === 'string' ? body.sender_id : ''
        if (!threadId || !senderId) return reply(res, 422, { error: 'thread_id and sender_id are required' })
        const text = typeof body.text === 'string' ? body.text.trim() : ''
        const link = typeof body.url === 'string' ? body.url.trim() : ''
        const imageUrl = typeof body.image_url === 'string' ? body.image_url.trim() : ''
        if (!text && !link && !imageUrl) return reply(res, 422, { error: 'text, url or image_url is required' })
        let sent = 0
        // The route card first, as a real picture: iMessage on Photon 2.0 sends plain text only, so a bare link
        // does not unfurl into a card. A picture that cannot be fetched or uploaded must not lose the briefing.
        if (imageUrl) {
          try {
            await photon.sendImage(threadId, senderId, await fetchImage(imageUrl), 'route.png')
            sent += 1
          } catch (error) {
            log(`route card not sent (${String(error)}); sending the text anyway`)
          }
        }
        // then the briefing with the link under it, in one message
        const message = [text, link].filter(Boolean).join('\n')
        if (message) {
          await photon.sendText(threadId, senderId, message)
          sent += 1
        }
        log(`sent to ${threadId} for incident ${String(body.incident_id ?? '?')}`)
        return reply(res, 200, { ok: true, sent })
      }

      reply(res, 404, { error: 'not found' })
    } catch (error) {
      log(`request failed: ${String(error)}`)
      reply(res, 502, { error: 'photon request failed' })
    }
  })
}
