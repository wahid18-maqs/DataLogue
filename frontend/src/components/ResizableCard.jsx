// Resizable wrapper for the dashboard chart cards.
//
// The card keeps its natural CSS layout until the user drags the corner grip;
// after that the explicit width/height is applied and persisted, so a tuned
// layout survives a reload.

import { useRef } from "react";
import { ResizeHandle, usePanelSize } from "./Resizable";

export default function ResizableCard({
  storageKey,
  title,
  children,
  className = "",
  min = {},
  max = {},
  resizeWidth = true,
  resizeHeight = true,
  lockWidth = false,
  defaultHeight = null,
}) {
  const panelRef = useRef(null);
  const { size, resize, reset } = usePanelSize(storageKey, { height: defaultHeight });

  // Once the user sizes a card, its explicit dimensions must win over the
  // flex basis in className — flex-basis would otherwise take precedence.
  const style = {};
  if (size.width && !lockWidth) {
    style.width = `${size.width}px`;
    style.flex = "0 0 auto";
  }
  if (size.height) style.height = `${size.height}px`;

  return (
    <div
      ref={panelRef}
      style={style}
      className={`relative ${className}`}
    >
      {children}

      <ResizeHandle
        size={size}
        elementRef={panelRef}
        min={min}
        max={max}
        resizeWidth={lockWidth ? false : resizeWidth}
        resizeHeight={resizeHeight}
        onResize={resize}
        onReset={reset}
      />
    </div>
  );
}
