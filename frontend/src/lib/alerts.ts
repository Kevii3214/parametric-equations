import type { AlertRow } from './contracts'

/** Insert or replace one alert row, keeping the list in the order the alerts opened. */
export function upsertAlert(list: AlertRow[], row: AlertRow): AlertRow[] {
  return [...list.filter((a) => a.id !== row.id), row].sort((a, b) => a.id - b.id)
}

/** Alerts that still stand (a fall the medic did not cancel, air that is still bad). */
export function activeAlerts(list: AlertRow[]): AlertRow[] {
  return list.filter((a) => a.active)
}

/** One short line for the banner. */
export function alertText(alert: AlertRow): string {
  if (alert.kind === 'fall') return 'Possible fall: the medic may be down. The medic can cancel it with button 1.'
  const reading = typeof alert.detail?.v === 'number' ? ` (reading ${alert.detail.v})` : ''
  return `Bad air detected near the medic${reading}. Smoke or fumes: use protection.`
}
