// Left rail: vertical list of slide thumbnails with slide numbers and titles.
// Clicking a thumbnail selects that slide in the main preview.

import ScaledSlide from "./ScaledSlide";
import { resolvePalette, seriesColors } from "./slideTheme";

export default function SlideThumbnailRail({
  slides = [],
  activeIndex = 0,
  onSelect,
  deck = null,
  themeName = null,
}) {
  if (!slides.length) {
    return (
      <aside className="w-56 shrink-0 border-r border-slate-200 bg-surface">
        <div className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Slides
        </div>
        <p className="px-4 pb-4 text-[11px] text-slate-400">No slides yet.</p>
      </aside>
    );
  }

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-slate-200 bg-surface">
      <div className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        Slides ({slides.length})
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-3 pb-4">
        {slides.map((slide, index) => {
          const isActive = index === activeIndex;
          return (
            <button
              key={slide.index ?? index}
              type="button"
              onClick={() => onSelect?.(index)}
              className={`block w-full rounded-lg border p-1.5 text-left transition-all ${
                isActive
                  ? "border-blue-500 bg-blue-50/60 ring-2 ring-blue-100"
                  : "border-slate-200 bg-surface hover:border-blue-300 hover:bg-slate-50"
              }`}
              aria-current={isActive ? "true" : undefined}
            >
              <ScaledSlide
                slide={slide}
                fit="width"
                className="aspect-video w-full overflow-hidden rounded border border-slate-200"
                palette={resolvePalette(deck, themeName)}
                themeName={themeName || deck?.theme}
                seriesPalette={seriesColors(deck, themeName)}
              />

              <div className="mt-1.5 flex items-center gap-1.5">
                <span
                  className={`flex h-4 min-w-4 items-center justify-center rounded px-1 text-[9px] font-bold ${
                    isActive ? "bg-blue-600 text-on-accent" : "bg-fill text-slate-600"
                  }`}
                >
                  {slide.index ?? index + 1}
                </span>
                <span className="truncate text-[10px] font-medium text-slate-600">
                  {slide.title || `Slide ${index + 1}`}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
