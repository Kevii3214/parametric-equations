import { useState } from 'react'
import { matterportThumb, matterportUrl, type MatterportModel } from '../../lib/buildings'

/**
 * Matterport 3D walkthroughs. Shows a poster until started (the embed is
 * heavy), then plays the model's guided tour on a loop.
 */
export default function MatterportTour({ models, compact = false }: { models: MatterportModel[]; compact?: boolean }) {
  const [selected, setSelected] = useState(models[0]?.id)
  const [started, setStarted] = useState(false)
  const model = models.find((m) => m.id === selected) ?? models[0]
  if (!model) return null

  return (
    <div className="flex h-full w-full flex-col bg-ink">
      <div className="relative min-h-0 flex-1">
        {started ? (
          <iframe key={model.id} title={`Matterport 3D walkthrough: ${model.title}`}
            src={matterportUrl(model.id, { autoplay: true, tour: true })}
            allow="fullscreen; xr-spatial-tracking" allowFullScreen
            className="absolute inset-0 h-full w-full border-0" />
        ) : (
          <button type="button" onClick={() => setStarted(true)}
            className="group absolute inset-0 h-full w-full overflow-hidden text-left">
            <img src={matterportThumb(model.id)} alt="" className="absolute inset-0 h-full w-full object-cover transition duration-700 group-hover:scale-105" />
            <span className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/10 to-black/5" />
            <span className="absolute inset-0 grid place-items-center">
              <span className="flex items-center gap-2 rounded-full bg-card/95 py-2 pr-4 pl-2 text-sm font-semibold text-ink shadow-card transition group-hover:scale-105">
                <span className="grid h-8 w-8 place-items-center rounded-full bg-azure text-white">▶</span>
                Start 3D walkthrough
              </span>
            </span>
            <span className="absolute bottom-3 left-3 text-white">
              {model.destination && (
                <span className="mb-1 inline-block rounded-full bg-fern px-2 py-0.5 text-[11px] font-semibold">Patient location</span>
              )}
              <span className="block text-lg font-semibold tracking-tight drop-shadow">{model.title}</span>
              <span className="block text-xs text-white/80">{model.subtitle} · Matterport scan</span>
            </span>
          </button>
        )}
      </div>
      {!compact && models.length > 1 && (
        <div className="flex gap-2 overflow-x-auto bg-card p-2">
          {models.map((m) => (
            <button key={m.id} type="button" onClick={() => setSelected(m.id)}
              className={`flex shrink-0 items-center gap-2 rounded-xl p-1 pr-3 text-left transition ${
                m.id === model.id ? 'bg-azure-soft ring-1 ring-azure-line' : 'hover:bg-sunk'}`}>
              <img src={matterportThumb(m.id)} alt="" loading="lazy" className="h-9 w-12 rounded-lg object-cover" />
              <span>
                <span className={`block text-xs font-semibold ${m.id === model.id ? 'text-azure-deep' : 'text-ink'}`}>
                  {m.title}{m.destination && <span className="ml-1 text-fern">●</span>}
                </span>
                <span className="block text-[11px] text-ink-3">{m.subtitle}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
