import { describe, expect, it } from 'vitest'
import { buildingById, buildingForNote, SAMPLE_CALLS } from './buildings'

describe('sample calls', () => {
  it.each(SAMPLE_CALLS)('$label is recognised as its own building', (c) => {
    expect(buildingForNote(c.note)).toBe(c.building)
    expect(buildingById(c.building)).not.toBeNull()
  })

  it('returns null for a building it does not know', () => {
    expect(buildingForNote('70M fall, 1 Main St, Springfield')).toBeNull()
  })
})
