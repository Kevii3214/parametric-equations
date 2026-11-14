import Icon from '../Icon'
import Panel, { Chip } from '../Panel'
import { inCostar, type Building } from '../../lib/buildings'
import type { IncidentRow, PlanStepRow } from '../../lib/contracts'
import { parsedNote, recordsResult } from '../../lib/incident'

export function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="mt-0.5 truncate text-[15px] font-medium text-ink">{value ?? <span className="text-ink-3">—</span>}</dd>
    </div>
  )
}


const CLASS = ['', 'A', 'B', 'C']

/** The real CoStar record for a known building, plus who is in the patient's suite. */
export default function CostarCard({ building, incident, steps }: { building: Building; incident: IncidentRow | null; steps: PlanStepRow[] }) {
  const r = building.record
  const note = parsedNote(incident?.parsed ?? null)
  const suite = String(note.suite ?? '')
  const tenant = r.current_tenants.find((t) => t.suite === suite)
  const floor = tenant?.floor_guess_from_suite ?? note.floor
  const lifts = r.elevators.filter((e) => e.count).map((e) => `${e.count} ${e.type.toLowerCase()}`).join(' · ')
  const covered = r.parking.find((p) => p.type === 'Covered' && p.spaces)
  const fromAgent = recordsResult(steps) !== null
  const costar = inCostar(building)
  const rating = r.building_rating ?? null

  return (
    <Panel title={costar ? 'CoStar building record' : 'Building record'}
      aside={!costar ? <Chip tone="amber">Not in CoStar · written by hand</Chip>
        : fromAgent ? <Chip tone="fern"><Icon name="check" className="mr-1 h-3 w-3" />records subagent</Chip> : <Chip>CoStar</Chip>}>
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-lg font-semibold leading-tight tracking-tight text-ink">{r.name}</p>
          <p className="text-sm text-ink-2">{r.address}, {r.city}, {r.state} {r.postcode}</p>
        </div>
        {r.building_class != null && (
          <span className="shrink-0 rounded-xl bg-azure-soft px-2.5 py-1.5 text-center leading-none text-azure-deep">
            <span className="block text-lg font-bold">{CLASS[r.building_class] ?? r.building_class}</span>
            <span className="block text-[10px] font-medium">Class</span>
          </span>
        )}
      </div>
      {(suite || floor) && (
        <div className="mt-3 flex items-center gap-3 rounded-xl border border-fern-line bg-fern-soft px-3 py-2.5">
          <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-fern text-sm font-bold text-white">{floor ?? '?'}</span>
          <div className="min-w-0 text-sm">
            <div className="font-semibold text-fern-deep">
              {suite ? `Suite ${suite}${tenant?.company ? ` · ${tenant.company}` : ''}` : String(note.location ?? 'Patient location')}
            </div>
            <div className="text-fern-deep/80">Floor {floor ?? 'unknown'}{note.complaint ? ` · ${note.complaint}` : ''}</div>
          </div>
        </div>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3.5">
        <Field label="Stories" value={r.stories_above_grade} />
        <Field label="Rating" value={rating == null ? null : <span className="flex gap-0.5" aria-label={`${rating} of 5 stars`}>{[1, 2, 3, 4, 5].map((i) => <Icon key={i} name="star" className={`h-4 w-4 ${i <= rating ? 'text-amber' : 'text-line-strong'}`} />)}</span>} />
        <Field label="Elevators" value={lifts || (costar ? null : 'None in the scan')} />
        <Field label="Parking" value={covered ? `${covered.spaces!.toLocaleString()} covered` : null} />
        <Field label="Gross area" value={r.gross_area_sqft ? `${Math.round(r.gross_area_sqft).toLocaleString()} sq ft` : null} />
        <Field label={costar ? 'Tenants' : 'Use'} value={costar ? r.current_tenants.filter((t) => t.company).length : r.property_type} />
      </dl>
      {r.data_quality_notes.length > 0 && (
        <details className="group mt-4">
          <summary className="cursor-pointer list-none text-xs text-ink-3 hover:text-azure">
            {r.data_quality_notes.length} data-quality notes
          </summary>
          <ul className="mt-2 space-y-1.5 text-xs leading-snug text-ink-2">
            {r.data_quality_notes.map((n) => <li key={n} className="rounded-lg bg-sunk p-2">{n}</li>)}
          </ul>
        </details>
      )}
    </Panel>
  )
}

