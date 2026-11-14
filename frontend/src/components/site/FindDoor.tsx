import { entranceSide, obliqueShowing, viewedFrom, type Building, type SiteMarker } from '../../lib/buildings'
import Icon from '../Icon'

/**
 * "Find this door": before the first turn, show the Vexcel oblique that looks
 * at the side of the building the chosen entrance is on, so the crew knows
 * what to look for when they step out of the ambulance.
 */
export default function FindDoor({ building, entrance, onDismiss }: {
  building: Building; entrance: SiteMarker; onDismiss: () => void
}) {
  const side = entranceSide(building, entrance)
  const photo = obliqueShowing(side)
  const note = building.obliqueNotes[photo]
  return (
    <section aria-label="Find this door" className="overflow-hidden rounded-3xl border border-line bg-card shadow-card">
      <div className="relative aspect-[16/10] w-full overflow-hidden bg-ink">
        <img src={building.obliques[photo]} alt={`The ${side} side of ${building.record.name}, seen from the ${viewedFrom(photo)}`}
          className="absolute inset-0 h-full w-full object-cover"
          style={{ objectPosition: building.obliqueFocus[photo] ?? 'center', animation: 'kenburns-0 9s ease-out forwards',
            transformOrigin: building.obliqueFocus[photo] ?? 'center' }} />
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-transparent" />
        <span className="absolute top-3 left-3 rounded-full bg-fern px-2.5 py-1 text-[11px] font-semibold text-white shadow-card">
          Find this door
        </span>
        <button type="button" onClick={onDismiss} aria-label="Hide door photo"
          className="absolute top-3 right-3 grid h-8 w-8 place-items-center rounded-full bg-card/90 text-ink-2 shadow-card hover:text-ink"><Icon name="close" /></button>
        <div className="absolute inset-x-0 bottom-0 p-4 text-white">
          <div className="text-xl font-semibold leading-tight tracking-tight drop-shadow">{entrance.label}</div>
          <div className="mt-0.5 text-sm text-white/85">
            On the <span className="font-semibold text-white">{side} side</span> of {building.record.name}
          </div>
        </div>
      </div>
      {note && (
        <p className="flex gap-2 border-b border-line bg-amber-soft/60 px-4 py-2.5 text-sm text-ink">
          <Icon name="info" className="mt-0.5 h-4 w-4 shrink-0 text-amber" />{note}
        </p>
      )}
      <p className="px-4 py-2.5 text-xs text-ink-3">
        Vexcel oblique, seen from the {viewedFrom(photo)}{entrance.estimated ? ' · door position estimated' : ''}
      </p>
    </section>
  )
}
