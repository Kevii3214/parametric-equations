import { lazy, Suspense, useState } from 'react'
import { obliqueShowing, sideOf, type Building } from '../../lib/buildings'
import type { RouteStep } from '../../lib/contracts'
import MatterportTour from './MatterportTour'
import ObliqueTour from './ObliqueTour'
import OrthoView from './OrthoView'

// MapLibre is large, so the 3D view loads only when it is shown.
const SiteFlyover = lazy(() => import('./SiteFlyover'))

type Tab = 'flyover' | 'overhead' | 'approach' | 'interior'

const TABS: { id: Tab; label: string; source: string }[] = [
  { id: 'flyover', label: '3D flyover', source: 'OpenStreetMap 3D · route placed from the building graph (approximate)' },
  { id: 'overhead', label: 'Overhead', source: 'Vexcel ortho · CoStar parcel' },
  { id: 'approach', label: 'Approach', source: 'Vexcel obliques' },
  { id: 'interior', label: 'Inside', source: 'Matterport scans' },
]

/** Every view of the site in one panel: map flyover, aerials and interior scans. */
export default function SiteImagery({ building, entranceNode, patientFloor, steps }: {
  building: Building; entranceNode: string | null; patientFloor: number | null; steps?: RouteStep[]
}) {
  const [tab, setTab] = useState<Tab>('flyover')
  const entrance = building.markers.find((m) => m.node === entranceNode)

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-card shadow-card">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-3.5 pb-3">
        <div className="min-w-0">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3">Site</h2>
          <p className="truncate text-[15px] font-semibold text-ink">
            {building.record.name}
            <span className="font-normal text-ink-2"> · {building.record.city}, {building.record.state}</span>
          </p>
        </div>
        <nav className="ml-auto flex gap-0.5 rounded-full bg-sunk p-0.5" aria-label="Site views">
          {TABS.filter((t) => building.imageryMatches || (t.id !== 'overhead' && t.id !== 'approach')).map((t) => (
            <button key={t.id} type="button" onClick={() => setTab(t.id)} aria-pressed={tab === t.id}
              className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                tab === t.id ? 'bg-card text-azure shadow-card' : 'text-ink-2 hover:text-ink'}`}>
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <div className="relative aspect-[4/3] w-full sm:aspect-[16/9]">
        {tab === 'flyover' && (
          <Suspense fallback={<div className="grid h-full place-items-center bg-sunk text-sm text-ink-3">Loading 3D map…</div>}>
            <SiteFlyover building={building} entranceNode={entranceNode} patientFloor={patientFloor} steps={steps} />
          </Suspense>
        )}
        {tab === 'overhead' && <OrthoView building={building} entranceNode={entranceNode} />}
        {tab === 'approach' && <ObliqueTour building={building} start={entrance ? obliqueShowing(sideOf(building, entrance.at)) : undefined} />}
        {tab === 'interior' && <MatterportTour models={building.matterport} />}
      </div>
      <footer className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-xs text-ink-3">
        {entrance && (
          <span className="flex items-center gap-1.5 text-sm text-ink-2">
            <span className="h-2 w-2 rounded-full bg-fern" />
            Stop at <span className="font-semibold text-ink">{entrance.label}</span>
            {entrance.estimated && <span className="text-xs text-ink-3">(position estimated)</span>}
          </span>
        )}
        {!building.imageryMatches && <span className="w-full text-amber">{building.imageryNote}</span>}
        <span className="ml-auto">{TABS.find((t) => t.id === tab)?.source}</span>
      </footer>
    </section>
  )
}
