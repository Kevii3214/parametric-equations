import { randomUUID } from 'node:crypto'
import { Photon } from '@photon-ai/api'
import type { Config } from './config.js'

/** What the sidecar needs from Photon: post a text into a chat, and give a person a line to text. */
export interface PhotonApi {
  sendText(spaceId: string, senderId: string, text: string): Promise<void>
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
    async assign(handle, firstName) {
      const created = await photon.projects.platforms.imessage.assignments.create({
        path: projectPath,
        headers: { idempotencyKey: randomUUID() },
        body: { handle, ...(firstName ? { firstName } : {}) },
      })
      return { assignedPhoneNumber: created.assignedPhoneNumber, assignmentId: created.assignmentId }
    },
  }
}
