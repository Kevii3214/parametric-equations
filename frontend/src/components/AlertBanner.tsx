import { activeAlerts, alertText } from '../lib/alerts'
import type { AlertRow } from '../lib/contracts'

/** Red banner while the wearable reports a fall or bad air. Disappears when the alert clears. */
export default function AlertBanner({ alerts }: { alerts: AlertRow[] }) {
  const active = activeAlerts(alerts)
  if (!active.length) return null
  return (
    <div role="alert" aria-live="assertive" className="flex flex-col gap-2">
      {active.map((a) => (
        <p key={a.id} className="rounded-2xl border border-alert/40 bg-alert-soft px-4 py-3 text-sm font-semibold text-alert">
          {a.kind === 'fall' ? 'FALL ALERT' : 'AIR ALERT'} <span className="font-medium text-ink">{alertText(a)}</span>
        </p>
      ))}
    </div>
  )
}
