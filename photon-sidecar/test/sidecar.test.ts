import type { AddressInfo } from 'node:net'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createBackend } from '../src/backend.js'
import { loadConfig } from '../src/config.js'
import { createInbound } from '../src/inbound.js'
import { createPhoton } from '../src/photon.js'
import { createApp, downloadImage } from '../src/server.js'
import { verifyAndParse } from '../src/webhook.js'
import { config, fakeBackend, fakePhoton, secret, signedDelivery } from './helpers.js'

describe('config', () => {
  it('names the variable that is missing', () => {
    expect(() => loadConfig({})).toThrow('PHOTON_API_KEY is not set')
    const env = {
      PHOTON_API_KEY: 'k',
      PHOTON_PROJECT_ID: 'p',
      PHOTON_WEBHOOK_SECRET: 's',
      BACKEND_URL: 'http://b/',
      PHOTON_SHARED_SECRET: 'x',
    }
    expect(loadConfig(env)).toMatchObject({ backendUrl: 'http://b', port: 8788 })
    expect(loadConfig({ ...env, PORT: '' }).port).toBe(8788)
    expect(loadConfig({ ...env, PORT: '9000' }).port).toBe(9000)
  })
})

describe('webhook verification', () => {
  it('accepts a signed iMessage text and extracts who sent it and which chat to reply into', () => {
    const { payload, headers } = signedDelivery()
    expect(verifyAndParse(payload, headers, secret)).toEqual({
      webhookId: 'msg_1',
      handle: '+15551230000',
      spaceId: 'pho_spc_1',
      userId: 'pho_usr_line',
      text: 'elevator B is out',
    })
  })

  it('rejects a wrong signature, a tampered body and a stale timestamp', () => {
    const good = signedDelivery()
    const other = signedDelivery({}, 'whsec_' + Buffer.from('another secret!!!!!!!!').toString('base64'))
    expect(() => verifyAndParse(good.payload, other.headers, secret)).toThrow()
    expect(() => verifyAndParse(good.payload.replace('elevator', 'escalator'), good.headers, secret)).toThrow()
    const old = { ...good.headers, 'webhook-timestamp': String(Math.floor(Date.now() / 1000) - 3600) }
    expect(() => verifyAndParse(good.payload, old, secret)).toThrow()
  })

  it('ignores events that are not a text from a person on iMessage', () => {
    for (const odd of [{ type: 'message.delivered' }, { platform: 'sms' }, { contentType: 'attachment' }, { text: '  ' }]) {
      const { payload, headers } = signedDelivery(odd)
      expect(verifyAndParse(payload, headers, secret)).toBeNull()
    }
  })
})

describe('what is sent to Photon (checked against the public API contract)', () => {
  async function captured(action: (photon: ReturnType<typeof createPhoton>) => Promise<unknown>) {
    const requests: { url: string; method: string; headers: Headers; body: unknown }[] = []
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init)
      requests.push({
        url: request.url,
        method: request.method,
        headers: request.headers,
        body: request.body ? JSON.parse(await request.text()) : undefined,
      })
      return new Response('{}', { status: 500, headers: { 'content-type': 'application/json' } })
    }) as typeof fetch
    await action(createPhoton(config, fetchImpl)).catch(() => undefined) // the stub answers 500; only the request matters
    return requests
  }

  it('posts a plain text message into the saved space, as the line, with an idempotency key', async () => {
    const [request] = await captured((photon) => photon.sendText('pho_spc_1', 'pho_usr_line', 'Go left'))
    expect(request?.method).toBe('POST')
    expect(request?.url).toBe(`https://api.photon.codes/v1/projects/${config.projectId}/messages`)
    expect(request?.headers.get('authorization')).toBe('Bearer pho_sk_test')
    expect(request?.headers.get('idempotency-key')).toMatch(/^[\x20-\x7e]{1,255}$/)
    expect(request?.body).toEqual({
      content: { type: 'text', format: 'plain', text: 'Go left' },
      senderId: 'pho_usr_line',
      spaceId: 'pho_spc_1',
    })
  })

  it('uses a new idempotency key for every message', async () => {
    const [a, b] = await captured(async (photon) => {
      await photon.sendText('pho_spc_1', 'pho_usr_line', 'one').catch(() => undefined)
      await photon.sendText('pho_spc_1', 'pho_usr_line', 'two')
    })
    expect(a?.headers.get('idempotency-key')).not.toBe(b?.headers.get('idempotency-key'))
  })

  it('asks for a shared-line assignment for a crew member', async () => {
    const [request] = await captured((photon) => photon.assign('+15551230000', 'Sam'))
    expect(request?.url).toBe(`https://api.photon.codes/v1/projects/${config.projectId}/platforms/imessage/assignments`)
    expect(request?.body).toEqual({ handle: '+15551230000', firstName: 'Sam' })
    expect(request?.headers.get('idempotency-key')).toBeTruthy()
  })
})

describe('assigning someone who already has a line', () => {
  it('returns the line they already have instead of failing', async () => {
    const urls: string[] = []
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init)
      urls.push(`${request.method} ${new URL(request.url).pathname}`)
      if (request.method === 'POST') {
        return Response.json({ type: 'x', title: 'Assignment exists', status: 409, code: 'ASSIGNMENT_EXISTS' }, { status: 409 })
      }
      return Response.json({
        assignments: [
          { createdAt: '2026-11-15T00:00:00.000Z', updatedAt: '2026-11-15T00:00:00.000Z', platform: 'imessage', projectId: 'pho_prj_x', handle: '+15550000000', assignedPhoneNumber: '+16280000000', assignmentId: 'pho_asg_other', optIn: { state: 'received' } },
          { createdAt: '2026-11-15T00:00:00.000Z', updatedAt: '2026-11-15T00:00:00.000Z', platform: 'imessage', projectId: 'pho_prj_x', handle: '+15551230000', assignedPhoneNumber: '+16283166196', assignmentId: 'pho_asg_mine', optIn: { state: 'received' } },
        ],
      })
    }) as typeof fetch
    const assigned = await createPhoton(config, fetchImpl).assign('+15551230000', 'Sam')
    expect(assigned).toEqual({ assignedPhoneNumber: '+16283166196', assignmentId: 'pho_asg_mine' })
    expect(urls).toHaveLength(2)
  })

  it('still fails for a handle that is not in the list, and for other errors', async () => {
    const conflict = (async (input: RequestInfo | URL, init?: RequestInit) =>
      new Request(input, init).method === 'POST'
        ? Response.json({ title: 't', status: 409 }, { status: 409 })
        : Response.json({ assignments: [] })) as typeof fetch
    await expect(createPhoton(config, conflict).assign('+15551230000')).rejects.toThrow()
    const down = (async () => Response.json({ title: 'x', status: 500 }, { status: 500 })) as typeof fetch
    await expect(createPhoton(config, down).assign('+15551230000')).rejects.toThrow()
  })
})

describe('sending an image to Photon', () => {
  it('uploads multipart/related (JSON part, then the bytes) and then sends it as an attachment message', async () => {
    const png = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 250, 251, 252])
    const seen: { path: string; headers: Headers; raw: Buffer }[] = []
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init)
      seen.push({ path: new URL(request.url).pathname, headers: request.headers, raw: Buffer.from(await request.arrayBuffer()) })
      if (request.url.endsWith('/attachments')) {
        const now = '2026-11-15T00:00:00.000Z'
        return Response.json(
          { id: 'pho_att_00000000000000000000000001', contentType: 'image/png', createdAt: now, updatedAt: now, projectId: 'pho_prj_x', sizeBytes: png.byteLength },
          { status: 201 },
        )
      }
      return Response.json({}, { status: 500 }) // only the request matters for the message
    }) as typeof fetch
    await createPhoton(config, fetchImpl).sendImage('pho_spc_1', 'pho_usr_line', png, 'route.png').catch(() => undefined)

    const [upload, message] = seen
    expect(upload?.path).toBe(`/v1/projects/${config.projectId}/attachments`)
    const type = upload?.headers.get('content-type') ?? ''
    const boundary = /^multipart\/related; boundary=(.+)$/.exec(type)?.[1]
    expect(boundary).toBeTruthy()
    expect(upload?.headers.get('idempotency-key')).toBeTruthy()
    expect(upload?.headers.get('content-length')).toBe(String(upload?.raw.byteLength))

    // exactly two parts: JSON with the true size, then the file bytes unchanged
    const body = upload?.raw as Buffer
    const blank = '\r\n\r\n'
    const parts = body.toString('latin1').split(`--${boundary}`).filter((p) => p.trim() && p.trim() !== '--')
    expect(parts).toHaveLength(2)
    const json = JSON.parse(parts[0]!.split(blank)[1]!.trim()) as Record<string, unknown>
    expect(json).toEqual({ contentType: 'image/png', sizeBytes: png.byteLength, filename: 'route.png' })
    const marker = `content-type: image/png${blank}`
    const fileStart = body.indexOf(Buffer.from(marker)) + marker.length
    expect([...body.subarray(fileStart, fileStart + png.byteLength)]).toEqual([...png])

    expect(message?.path).toBe(`/v1/projects/${config.projectId}/messages`)
    expect(JSON.parse(message!.raw.toString())).toEqual({
      content: { type: 'attachment', attachmentId: 'pho_att_00000000000000000000000001' },
      senderId: 'pho_usr_line',
      spaceId: 'pho_spc_1',
    })
  })
})

describe('downloading the route card', () => {
  const answer = (init: ResponseInit, body: BodyInit = new Uint8Array([1, 2, 3])) =>
    vi.stubGlobal('fetch', async () => new Response(body, init))
  afterEach(() => vi.unstubAllGlobals())

  it('accepts a small PNG and refuses everything else', async () => {
    answer({ headers: { 'content-type': 'image/png' } })
    expect([...(await downloadImage('https://x.test/c.png'))]).toEqual([1, 2, 3])
    answer({ headers: { 'content-type': 'text/html' } })
    await expect(downloadImage('https://x.test/c.png')).rejects.toThrow('not a PNG')
    answer({ status: 404 })
    await expect(downloadImage('https://x.test/c.png')).rejects.toThrow('404')
    answer({ headers: { 'content-type': 'image/png' } }, new Uint8Array(5_000_001))
    await expect(downloadImage('https://x.test/c.png')).rejects.toThrow('too large')
    await expect(downloadImage('file:///etc/passwd')).rejects.toThrow('http(s)')
  })
})

describe('the backend client', () => {
  it('sends the shared secret and treats a 404 as "not on an incident"', async () => {
    const seen: { url: string; secret: string | null }[] = []
    const fetchImpl = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(input, init)
      seen.push({ url: request.url, secret: request.headers.get('x-photon-secret') })
      return request.url.endsWith('/resolve')
        ? new Response('{}', { status: 404 })
        : Response.json({ replies: ['hi'] })
    }) as typeof fetch
    const backend = createBackend(config, fetchImpl)
    expect(await backend.resolve('+1555', 's', 'u')).toBeNull()
    expect(await backend.crewReport('inc 1', 'text', '+1555', 'imessage')).toEqual(['hi'])
    expect(seen.map((s) => s.secret)).toEqual(['shh', 'shh'])
    expect(seen[1]?.url).toBe('http://backend.test/incidents/inc%201/crew-report')
  })
})

describe('inbound texts', () => {
  const message = { webhookId: 'w1', handle: '+15551230000', spaceId: 'pho_spc_1', userId: 'pho_usr_line', text: 'elevator out' }

  it('hands the text to the backend and posts its replies back into the same chat', async () => {
    const backend = fakeBackend()
    const photon = fakePhoton()
    await createInbound(backend.api, photon.api, () => undefined)(message)
    expect(backend.calls.map((c) => c.kind)).toEqual(['resolve', 'report'])
    expect(backend.calls[1]?.args).toEqual(['inc-1', 'elevator out', '+15551230000', 'imessage'])
    expect(photon.calls).toEqual([
      { kind: 'send', args: ['pho_spc_1', 'pho_usr_line', 'Re-routing around elevator B. Reply YES to confirm.'] },
    ])
  })

  it('drops a text from someone who is not on an active incident, without replying', async () => {
    const backend = fakeBackend(false)
    const photon = fakePhoton()
    await createInbound(backend.api, photon.api, () => undefined)(message)
    expect(backend.calls.map((c) => c.kind)).toEqual(['resolve'])
    expect(photon.calls).toEqual([])
  })

  it('handles a retried delivery (same webhook-id) only once', async () => {
    const backend = fakeBackend()
    const photon = fakePhoton()
    const inbound = createInbound(backend.api, photon.api, () => undefined)
    await inbound(message)
    await inbound(message)
    expect(photon.calls).toHaveLength(1)
  })
})

describe('the http server', () => {
  async function start(known = true, fetchImage?: (url: string) => Promise<Uint8Array>) {
    const backend = fakeBackend(known)
    const photon = fakePhoton()
    const handled: Promise<void>[] = []
    const inbound = createInbound(backend.api, photon.api, () => undefined)
    const server = createApp({
      config,
      photon: photon.api,
      onInbound: (m) => {
        const done = inbound(m)
        handled.push(done)
        return done
      },
      log: () => undefined,
      ...(fetchImage ? { fetchImage } : {}),
    })
    await new Promise<void>((resolve) => server.listen(0, resolve))
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
    return { base, photon, backend, handled, stop: () => server.close() }
  }
  const post = (url: string, body: unknown, headers: Record<string, string> = {}) =>
    fetch(url, { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) })

  it('answers /health', async () => {
    const s = await start()
    expect((await (await fetch(`${s.base}/health`)).json()) as unknown).toEqual({ ok: true })
    s.stop()
  })

  it('/send and /assign need the shared secret', async () => {
    const s = await start()
    const body = { thread_id: 'pho_spc_1', sender_id: 'pho_usr_line', text: 'hi' }
    expect((await post(`${s.base}/send`, body)).status).toBe(401)
    expect((await post(`${s.base}/send`, body, { 'x-photon-secret': 'nope' })).status).toBe(401)
    expect((await post(`${s.base}/assign`, { handle: '+1' })).status).toBe(401)
    expect(s.photon.calls).toEqual([])
    s.stop()
  })

  it('/send puts the briefing and the link in one text message', async () => {
    const s = await start()
    const body = { incident_id: 'inc-1', thread_id: 'pho_spc_1', sender_id: 'pho_usr_line', text: 'Go left', url: 'https://x.test/medic/inc-1?t=abc' }
    const res = await post(`${s.base}/send`, body, { 'x-photon-secret': 'shh' })
    expect(await res.json()).toEqual({ ok: true, sent: 1 })
    expect(s.photon.calls.map((c) => c.args[2])).toEqual(['Go left\nhttps://x.test/medic/inc-1?t=abc'])
    s.stop()
  })

  it('/send sends the route card as a picture first, then the text', async () => {
    const fetched: string[] = []
    const s = await start(true, async (url) => {
      fetched.push(url)
      return new Uint8Array([1, 2, 3, 4])
    })
    const body = { thread_id: 'pho_spc_1', sender_id: 'pho_usr_line', text: 'Go left', url: 'https://x.test/m', image_url: 'https://x.test/card.png' }
    const res = await post(`${s.base}/send`, body, { 'x-photon-secret': 'shh' })
    expect(await res.json()).toEqual({ ok: true, sent: 2 })
    expect(fetched).toEqual(['https://x.test/card.png'])
    expect(s.photon.calls.map((c) => c.kind)).toEqual(['image', 'send'])
    expect(s.photon.calls[0]?.args).toEqual(['pho_spc_1', 'pho_usr_line', 4, 'route.png'])
    s.stop()
  })

  it('a card that cannot be fetched or uploaded never loses the briefing', async () => {
    const s = await start(true, async () => {
      throw new Error('card is down')
    })
    const body = { thread_id: 'pho_spc_1', sender_id: 'pho_usr_line', text: 'Go left', image_url: 'https://x.test/card.png' }
    const res = await post(`${s.base}/send`, body, { 'x-photon-secret': 'shh' })
    expect(await res.json()).toEqual({ ok: true, sent: 1 })
    expect(s.photon.calls.map((c) => c.kind)).toEqual(['send'])
    s.stop()
  })

  it('/send refuses an empty request', async () => {
    const s = await start()
    const headers = { 'x-photon-secret': 'shh' }
    expect((await post(`${s.base}/send`, { thread_id: 't', sender_id: 's' }, headers)).status).toBe(422)
    expect((await post(`${s.base}/send`, { text: 'hi' }, headers)).status).toBe(422)
    s.stop()
  })

  it('/assign returns the number the crew member has to text', async () => {
    const s = await start()
    const res = await post(`${s.base}/assign`, { handle: '+15551230000', name: 'Sam' }, { 'x-photon-secret': 'shh' })
    expect(await res.json()).toEqual({ assigned_phone_number: '+15559990000', assignment_id: 'asg_1' })
    expect(s.photon.calls[0]).toEqual({ kind: 'assign', args: ['+15551230000', 'Sam'] })
    s.stop()
  })

  it('a photon failure is a 502, not a crash', async () => {
    const s = await start()
    s.photon.api.sendText = async () => {
      throw new Error('photon is down')
    }
    const res = await post(`${s.base}/send`, { thread_id: 't', sender_id: 's', text: 'hi' }, { 'x-photon-secret': 'shh' })
    expect(res.status).toBe(502)
    s.stop()
  })

  it('the webhook rejects a bad signature, and acknowledges a good one before the reply is sent', async () => {
    const s = await start()
    const bad = signedDelivery({}, 'whsec_' + Buffer.from('another secret!!!!!!!!').toString('base64'))
    const rejected = await fetch(`${s.base}/photon/webhook`, { method: 'POST', headers: bad.headers, body: bad.payload })
    expect(rejected.status).toBe(401)
    expect(s.photon.calls).toEqual([])

    const good = signedDelivery()
    const accepted = await fetch(`${s.base}/photon/webhook`, { method: 'POST', headers: good.headers, body: good.payload })
    expect(accepted.status).toBe(204)
    await Promise.all(s.handled)
    expect(s.photon.calls).toHaveLength(1)
    expect(s.backend.calls.map((c) => c.kind)).toEqual(['resolve', 'report'])
    s.stop()
  })

  it('a verified event that is not a crew text is acknowledged and ignored', async () => {
    const s = await start()
    const delivery = signedDelivery({ type: 'message.delivered' })
    const res = await fetch(`${s.base}/photon/webhook`, { method: 'POST', headers: delivery.headers, body: delivery.payload })
    expect(res.status).toBe(204)
    expect(s.handled).toHaveLength(0)
    s.stop()
  })

  it('answers 404 for anything else', async () => {
    const s = await start()
    expect((await fetch(`${s.base}/nope`)).status).toBe(404)
    s.stop()
  })
})
