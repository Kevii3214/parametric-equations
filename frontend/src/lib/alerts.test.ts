import { describe, expect, it } from 'vitest'
import { activeAlerts, alertText, upsertAlert } from './alerts'
import type { AlertRow } from './contracts'

const row = (over: Partial<AlertRow>): AlertRow => ({
  id: 1,
  incident_id: 'i',
  device_id: 'wearable-1',
  kind: 'fall',
  active: true,
  detail: {},
  created_at: '2026-11-15T10:00:00Z',
  cleared_at: null,
  ...over,
})

describe('alerts', () => {
  it('replaces a row when it is cleared and keeps the order', () => {
    const list = upsertAlert(upsertAlert([], row({ id: 2, kind: 'air' })), row({ id: 1 }))
    expect(list.map((a) => a.id)).toEqual([1, 2])
    const cleared = upsertAlert(list, row({ id: 1, active: false }))
    expect(cleared).toHaveLength(2)
    expect(activeAlerts(cleared).map((a) => a.id)).toEqual([2])
  })

  it('words each kind of alert', () => {
    expect(alertText(row({}))).toMatch(/fall/i)
    expect(alertText(row({ kind: 'air', detail: { v: 2800 } }))).toMatch(/2800/)
    expect(alertText(row({ kind: 'air', detail: {} }))).toMatch(/air/i)
  })
})
