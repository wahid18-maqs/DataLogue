// Scales a slide canvas to fit the space it is given.
//
// A slide is authored at a fixed 1280x720 (16:9) design size. This wrapper
// applies a uniform transform so the whole slide — padding, KPI tiles, type
// and all — scales together and keeps its proportions, instead of reflowing
// into a different-looking widget.
//
// Two ways to use it:
// - pass `scale` to size the slide yourself (see SlidePreview)
// - otherwise the component measures its own box and fits the slide inside it
//   (`fit="contain"` fits both ways, `fit="width"` fits the width alone)

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import SlideCanvas, { SLIDE_DESIGN_HEIGHT, SLIDE_DESIGN_WIDTH } from "./SlideCanvas";

// Measuring before the browser paints avoids a flash of an unscaled slide.
const useIsomorphicLayoutEffect =
  typeof window !== "undefined" ? useLayoutEffect : useEffect;

export default function ScaledSlide({
  slide,
  fit = "contain",
  scale: fixedScale,
  className = "",
  boxClassName = "",
  editing = false,
  onEdit,
  palette,
  themeName = null,
  seriesPalette = null,
}) {
  const ref = useRef(null);
  const [size, setSize] = useState(null);

  useIsomorphicLayoutEffect(() => {
    const node = ref.current;
    if (!node || fixedScale !== undefined) return undefined;

    const measure = (rect) => {
      if (rect && rect.width > 0) {
        setSize({ width: rect.width, height: rect.height });
      }
    };

    measure(node.getBoundingClientRect());

    if (typeof ResizeObserver === "undefined") return undefined;

    const observer = new ResizeObserver((entries) => {
      measure(entries[0]?.contentRect);
    });

    observer.observe(node);
    return () => observer.disconnect();
  }, [fixedScale]);

  let scale = fixedScale;
  if (scale === undefined) {
    scale = 1;
    if (size) {
      const byWidth = size.width / SLIDE_DESIGN_WIDTH;
      const byHeight = size.height > 0 ? size.height / SLIDE_DESIGN_HEIGHT : Infinity;
      scale = fit === "width" ? byWidth : Math.min(byWidth, byHeight);
    }
  }

  return (
    <div ref={ref} className={className}>
      <div
        className={`relative overflow-hidden ${boxClassName}`}
        style={{ width: SLIDE_DESIGN_WIDTH * scale, height: SLIDE_DESIGN_HEIGHT * scale }}
      >
        <div
          className="absolute left-0 top-0 origin-top-left"
          style={{
            width: SLIDE_DESIGN_WIDTH,
            height: SLIDE_DESIGN_HEIGHT,
            transform: `scale(${scale})`,
          }}
        >
          <SlideCanvas
            slide={slide}
            editing={editing}
            onEdit={onEdit}
            palette={palette}
            themeName={themeName}
            seriesPalette={seriesPalette}
          />
        </div>
      </div>
    </div>
  );
}
