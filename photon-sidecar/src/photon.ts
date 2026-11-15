import { randomUUID } from 'node:crypto'
import { ApiError, Photon } from '@photon-ai/api'
import type { Config } from './config.js'

/** What the sidecar needs from Photon: post a text into a chat, and give a person a line to text. */
export interface PhotonApi {
  sendText(spaceId: string, senderId: string, text: string): Promise<void>
  /** Upload a PNG and send it into the chat as an image message. */
  sendImage(spaceId: string, senderId: string, png: Uint8Array, filename: string): Promise<void>
  assign(handle: string, firstName?: string): Promise<{ assignedPhoneNumber: string; assignmentId: string }>
}

export function createPhoton(config: Config, fetchImpl?: typeof fetch): PhotonApi {
  const photon = new Photon({
    headers: { Authorization: `Bearer ${config.apiKey}` },
    ...(config.photonBaseUrl ? { baseUrl: config.photonBaseUrl } : {}),
    ...(fetchImpl ? { fetch: fetchImpl } : {}),
  })
  const projectPath = { id: config.projectId }
  return {
    async sendText(spaceId, senderId, text) {
      // A shared iMessage line can only message someone who has texted it first: spaceId and senderId are the
      // ones saved from that first inbound message. 202 means Photon accepted it, not that it was delivered.
      await photon.projects.sendMessage({
        path: projectPath,
        headers: { 'idempotency-key': randomUUID() },
        body: { content: { type: 'text', format: 'plain', text }, senderId, spaceId },
      })
    },
    async sendImage(spaceId, senderId, png, filename) {
      // An upload is multipart/related with exactly two parts: JSON (contentType, sizeBytes, filename), then the bytes.
      const boundary = `photon-${randomUUID()}`
      const meta = JSON.stringify({ contentType: 'image/png', sizeBytes: png.byteLength, filename })
      const CRLF = '\r\n' // multipart uses CRLF, not LF
      const head = [`--${boundary}`, 'content-type: application/json', '', meta, `--${boundary}`, 'content-type: image/png', '', ''].join(CRLF)
      const tail = ['', `--${boundary}--`, ''].join(CRLF)
      const body = Buffer.concat([Buffer.from(head), Buffer.from(png), Buffer.from(tail)])
      const attachment = await photon.projects.uploadAttachment({
        path: projectPath,
        headers: {
          'content-type': `multipart/related; boundary=${boundary}`,
          'content-length': String(body.byteLength),
          'idempotency-key': randomUUID(),
        },
        body: new Blob([body]),
      })
      await photon.projects.sendMessage({
        path: projectPath,
        headers: { 'idempotency-key': randomUUID() },
        body: { content: { type: 'attachment', attachmentId: attachment.id }, senderId, spaceId },
      })
    },
    async assign(handle, firstName) {
      try {
        const created = await photon.projects.platforms.imessage.assignments.create({
          path: projectPath,
          headers: { idempotencyKey: randomUUID() },
          body: { handle, ...(firstName ? { firstName } : {}) },
        })
        return { assignedPhoneNumber: created.assignedPhoneNumber, assignmentId: created.assignmentId }
      } catch (error) {
        // Already assigned (a person keeps their line): hand back the one they have.
        if (!(error instanceof ApiError) || error.status !== 409) throw error
        const listed = await photon.projects.platforms.imessage.assignments.list({ path: projectPath })
        const existing = listed.assignments.find((a) => a.handle === handle && !a.releasedAt)
        if (!existing) throw error
        return { assignedPhoneNumber: existing.assignedPhoneNumber, assignmentId: existing.assignmentId }
      }
    },
  }
}
