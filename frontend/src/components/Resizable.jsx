// Drag-to-resize helper shared by the dashboard chart cards.
//
// A panel's size is held in state and persisted to localStorage, so a layout
// the user tuned survives a page reload. Panels start unsized (null) and keep
// their natural CSS-driven dimensions until the user drags the handle.

import { useCallback, useEffect, useRef, useState } from "react";

const STORAGE_PREFIX = "dashboard-panel-size:";

function clamp(value, min, max) {
  if (typeof min === "number" && value < min) return min;
  if (typeof max === "number" && value > max) return max;
  return value;
}

/**
 * Work out a panel's new size from a drag.
 *
 * The panel's starting size is captured when the drag begins, so every move
 * is measured against that origin rather than accumulating rounding drift.
 *
 * @param {object} origin  { x, y, width, height } captured on pointer down.
 * @param {object} pointer { clientX, clientY } of the current event.
 * @param {object} options { min, max, resizeWidth, resizeHeight }.
 * @returns {{width?: number, height?: number}}
 */
export function computeResizedSize(origin, pointer, options = {}) {
  const { min = {}, max = {}, resizeWidth = true, resizeHeight = true } = options;

  const next = {};

  if (resizeWidth) {
    next.width = Math.round(
      clamp(origin.width + (pointer.clientX - origin.x), min.width, max.width)
    );
  }

  if (resizeHeight) {
    next.height = Math.round(
      clamp(origin.height + (pointer.clientY - origin.y), min.height, max.height)
    );
  }

  return next;
}

/**
 * Size state for one resizable panel.
 *
 * @param {string} key       Storage key (null disables persistence).
 * @param {object} defaults  { width, height } used before the user resizes.
 * @returns {{size, resize, reset}}
 */
export function usePanelSize(key, defaults = {}) {
  const { width = null, height = null } = defaults;

  const [size, setSize] = useState(() => {
    if (!key) return { width, height };
    try {
      const raw = window.localStorage.getItem(STORAGE_PREFIX + key);
      const stored = raw ? JSON.parse(raw) : null;
      return {
        width: stored?.width ?? width,
        height: stored?.height ?? height,
      };
    } catch {
      return { width, height };
    }
  });

  const resize = useCallback((next) => {
    setSize((current) => ({ ...current, ...next }));
  }, []);

  const reset = useCallback(() => {
    setSize({ width, height });
  }, [width, height]);

  useEffect(() => {
    if (!key) return;
    try {
      window.localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(size));
    } catch {
      // localStorage can be unavailable (private mode); resizing still works.
    }
  }, [key, size]);

  return { size, resize, reset };
}

/**
 * Corner grip that resizes its parent panel.
 *
 * The drag origin and the panel's starting size are captured on pointer down,
 * so every move is measured against the size the panel had when the drag
 * began rather than accumulating rounding drift.
 */
export function ResizeHandle({
  size = {},
  elementRef,
  min = {},
  max = {},
  resizeWidth = true,
  resizeHeight = true,
  onResize,
  onReset,
}) {
  const originRef = useRef(null);

  const handlePointerDown = (event) => {
    event.preventDefault();
    event.stopPropagation();

    // An unsized panel falls back to its measured on-screen size.
    const rect = elementRef?.current?.getBoundingClientRect();

    originRef.current = {
      x: event.clientX,
      y: event.clientY,
      width: size.width ?? rect?.width ?? 0,
      height: size.height ?? rect?.height ?? 0,
    };

    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event) => {
    const origin = originRef.current;
    if (!origin) return;

    onResize(
      computeResizedSize(origin, event, { min, max, resizeWidth, resizeHeight })
    );
  };

  const stopDragging = (event) => {
    originRef.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const cursor =
    resizeWidth && resizeHeight
      ? "cursor-nwse-resize"
      : resizeHeight
        ? "cursor-ns-resize"
        : "cursor-ew-resize";

  return (
    <div
      role="separator"
      aria-label="Resize chart"
      title="Drag to resize · double-click to reset"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={stopDragging}
      onPointerCancel={stopDragging}
      onDoubleClick={(event) => {
        event.preventDefault();
        onReset?.();
      }}
      className={`absolute bottom-0 right-0 z-10 flex h-4 w-4 touch-none items-end justify-end rounded-br-xl text-slate-300 transition-colors hover:text-blue-500 ${cursor}`}
    >
      <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 10 10" aria-hidden="true">
        <path d="M9 1v8H1l8-8z" />
      </svg>
    </div>
  );
}
