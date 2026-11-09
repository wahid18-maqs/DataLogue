// The colours the dashboard charts are drawn in.
//
// The charts are drawn with plain SVG, so they do not pick up the app's CSS
// classes the way the rest of the interface does. They take their colours
// from here instead, and follow the app's theme.

import { useSettings } from "../settings/SettingsContext";

/** Data colors stay consistent across themes; only chart scaffolding changes. */
const SERIES = ["#2563eb", "#06b6d4", "#8b5cf6", "#f59e0b", "#10b981"];
const PIE = ["#2563eb", "#38bdf8", "#818cf8", "#f59e0b", "#ec4899", "#10b981", "#64748b"];

/** The lines, the axes and the grid, per theme. */
const AXES = {
  light: { tick: "#64748b", axis: "#e2e8f0", grid: "#f1f5f9" },
  dark: { tick: "#9b9b9b", axis: "#444444", grid: "#373737" },
};

/**
 * The chart colours for a theme.
 *
 * The lookup is kept separate from the hook so the colours can be checked
 * without rendering anything.
 */
export function chartColorsFor(theme) {
  const key = theme === "dark" ? "dark" : "light";

  return {
    isDark: key === "dark",
    series: SERIES,
    pie: PIE,
    tick: AXES[key].tick,
    axis: AXES[key].axis,
    grid: AXES[key].grid,
  };
}

/**
 * The chart colours for the app's current theme.
 *
 * The theme comes from the shared settings, so the charts change with the
 * rest of the app rather than needing their own toggle.
 */
export function useChartTheme() {
  const { settings } = useSettings();
  return chartColorsFor(settings.appearance.app_theme);
}
