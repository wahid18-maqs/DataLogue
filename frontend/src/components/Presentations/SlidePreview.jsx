// Centre pane: large 16:9 presentation canvas with previous/next controls.
//
// The slide is scaled to whatever space the pane has, so the canvas grows
// with the viewport instead of stopping at a fixed width. Because the whole
// slide is scaled as one piece, its internal padding, KPI tiles and type keep
// the proportions of a real presentation slide at any size.
//
// The scale is measured here (rather than inside the canvas) so the
// Previous / Next controls can sit directly beneath the slide, whatever size
// it ends up being.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import ScaledSlide from "./ScaledSlide";
import { SLIDE_DESIGN_HEIGHT, SLIDE_DESIGN_WIDTH } from "./SlideCanvas";
import { resolvePalette, seriesColors } from "./slideTheme";

const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

export default function SlidePreview({
  slide,
  slideNumber,
  totalSlides,
  onPrev,
  onNext,
  editing = false,
  onEdit,
  deck = null,
  themeName = null,
}) {
  // The box the slide is laid out in; the slide is scaled to fit inside it.
  const stageRef = useRef(null);
  const [scale, setScale] = useState(1);

  useIsomorphicLayoutEffect(() => {
    const node = stageRef.current;
    if (!node) return undefined;

    const measure = (rect) => {
      if (!rect || rect.width <= 0 || rect.height <= 0) return;
      const next = Math.min(rect.width / SLIDE_DESIGN_WIDTH, rect.height / SLIDE_DESIGN_HEIGHT);
      if (next > 0) setScale(next);
    };

    measure(node.getBoundingClientRect());

    if (typeof ResizeObserver === "undefined") return undefined;

    const observer = new ResizeObserver((entries) => {
      measure(entries[0]?.contentRect);
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  if (!slide) {
    return (
      <div className="flex h-full min-w-0 flex-1 flex-col bg-slate-100 p-4">
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <div className="w-full max-w-3xl rounded-xl border border-dashed border-slate-300 bg-surface p-12 text-center">
            <p className="text-sm font-semibold text-slate-700">No slide selected</p>
            <p className="mt-1 text-xs text-slate-400">
              Upload a dataset and generate a presentation to preview the deck here.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col bg-slate-100 p-4">
      <div
        ref={stageRef}
        className="flex min-h-0 flex-1 items-center justify-center overflow-hidden"
      >
        <ScaledSlide
          slide={slide}
          scale={scale}
          boxClassName="rounded-lg border border-slate-200 shadow-lg"
          editing={editing}
          onEdit={onEdit}
          palette={resolvePalette(deck, themeName)}
          themeName={themeName || deck?.theme}
          seriesPalette={seriesColors(deck, themeName)}
        />
      </div>

      <div className="mt-4 flex shrink-0 items-center justify-center gap-4">
        <button
          type="button"
          onClick={onPrev}
          disabled={slideNumber <= 1}
          className="rounded-lg border border-slate-300 bg-surface px-4 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          ← Previous
        </button>

        <span className="text-sm font-medium text-slate-600">
          Slide {slideNumber} of {totalSlides}
        </span>

        <button
          type="button"
          onClick={onNext}
          disabled={slideNumber >= totalSlides}
          className="rounded-lg border border-slate-300 bg-surface px-4 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
