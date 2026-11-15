import { randomBytes } from 'node:crypto'
import { Webhook } from 'standardwebhooks'
import type { BackendApi } from '../src/backend.js'
import type { Config } from '../src/config.js'
import type { PhotonApi } from '../src/photon.js'

export const secret = `whsec_${randomBytes(24).toString('base64')}`

export const config: Config = {
  apiKey: 'pho_sk_test',
  projectId: 'pho_prj_00000000000000000000000001',
  webhookSecret: secret,
  backendUrl: 'http://backend.test',
  sharedSecret: 'shh',
  port: 0,
}

/** A message.received event as Photon delivers it, signed the way Photon signs it. */
export function signedDelivery(
  overrides: { text?: string; contentType?: string; platform?: string; type?: string; id?: string } = {},
  signWith = secret,
) {
  const id = overrides.id ?? 'msg_1'
  const payload = JSON.stringify({
    id,
    type: overrides.type ?? 'message.received',
    apiVersion: '2026-07-01',
    source: 'imessage.photon',
    timestamp: new Date().toISOString(),
    data: {
      projectId: config.projectId,
      object: {
        platform: overrides.platform ?? 'imessage',
        status: 'received',
        content: { type: overrides.contentType ?? 'text', format: 'plain', text: overrides.text ?? 'elevator B is out' },
        sentBy: { id: 'pho_usr_human', handle: '+15551230000', platform: 'imessage' },
        receivedBy: { id: 'pho_usr_line', handle: '+15559990000', platform: 'imessage' },
        space: { id: 'pho_spc_1', platform: 'imessage' },
      },
    },
  })
  const now = new Date()
  const headers = {
    'webhook-id': id,
    'webhook-timestamp': String(Math.floor(now.getTime() / 1000)),
    'webhook-signature': new Webhook(signWith).sign(id, now, payload),
  }
  return { payload, headers }
}

export function fakePhoton() {
  const calls: { kind: string; args: unknown[] }[] = []
  const api: PhotonApi = {
    async sendText(...args) {
      calls.push({ kind: 'send', args })
    },
    async sendImage(spaceId, senderId, png, filename) {
      calls.push({ kind: 'image', args: [spaceId, senderId, png.byteLength, filename] })
    },
    async assign(...args) {
      calls.push({ kind: 'assign', args })
      return { assignedPhoneNumber: '+15559990000', assignmentId: 'asg_1' }
    },
  }
  return { api, calls }
}

export function fakeBackend(known = true, replies: string[] = ['Re-routing around elevator B. Reply YES to confirm.']) {
  const calls: { kind: string; args: unknown[] }[] = []
  const api: BackendApi = {
    async resolve(...args) {
      calls.push({ kind: 'resolve', args })
      return known ? { incidentId: 'inc-1', firstContact: false } : null
    },
    async crewReport(...args) {
      calls.push({ kind: 'report', args })
      return replies
    },
  }
  return { api, calls }
}
