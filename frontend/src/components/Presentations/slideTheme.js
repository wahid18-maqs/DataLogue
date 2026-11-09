// The slide themes.
//
// These are the same colour sets the backend draws the .pptx with (see
// src/presentation_generator.py). The deck plan carries the palette it was
// built with, so the preview and the exported file are always the same
// colours — the preview reads the palette off the deck rather than keeping
// its own copy of the theme in step.

export const LIGHT_PALETTE = {
  bg_dark: "#0F172A",
  primary: "#2563EB",
  secondary: "#06B6D4",
  accent: "#8B5CF6",
  text_main: "#1E293B",
  text_muted: "#64748B",
  card_bg: "#F8FAFC",
  border: "#E2E8F0",
  on_dark: "#FFFFFF",
  success: "#10B981",
};

export const DARK_PALETTE = {
  bg_dark: "#020617",
  primary: "#60A5FA",
  secondary: "#22D3EE",
  accent: "#A78BFA",
  text_main: "#F1F5F9",
  text_muted: "#94A3B8",
  card_bg: "#0F172A",
  border: "#334155",
  on_dark: "#F8FAFC",
  success: "#34D399",
};

export const EXECUTIVE_NAVY_PALETTE = {
  bg_dark: "#0B1B33",
  primary: "#1E3A8A",
  secondary: "#38BDF8",
  accent: "#C9A227",
  text_main: "#0F172A",
  text_muted: "#475569",
  card_bg: "#F1F5F9",
  border: "#CBD5E1",
  on_dark: "#F8FAFC",
  success: "#059669",
};

export const PALETTES = {
  light: LIGHT_PALETTE,
  dark: DARK_PALETTE,
  executive_navy: EXECUTIVE_NAVY_PALETTE,
};

export const DEFAULT_PALETTE = LIGHT_PALETTE;

// The chart series colours, in the order the series are drawn.
const SERIES_COLORS = {
  light: ["#2563EB", "#06B6D4", "#8B5CF6", "#10B981", "#F59E0B", "#EF4444", "#3B82F6", "#14B8A6"],
  dark: ["#60A5FA", "#22D3EE", "#A78BFA", "#34D399", "#FBBF24", "#F87171", "#93C5FD", "#2DD4BF"],
  executive_navy: ["#1E3A8A", "#38BDF8", "#C9A227", "#0F766E", "#B45309", "#9F1239", "#4F46E5", "#0D9488"],
};

/**
 * A hex colour the browser can use.
 *
 * The backend sends its palette as bare hex digits ("60A5FA"), because
 * that is what PowerPoint wants, while the browser needs the "#" — a
 * colour without it is not a colour, and the style is quietly dropped.
 */
function toCssColor(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  return text.startsWith("#") ? text : `#${text}`;
}

/**
 * The palette a deck is drawn in.
 *
 * The deck's own palette wins, because it is the one the .pptx was built
 * with. A deck with no palette — an older one, or one still being built —
 * falls back to the theme named on the deck, and then to the default.
 */
export function resolvePalette(deck, themeName) {
  if (deck?.theme_palette && typeof deck.theme_palette === "object") {
    const merged = { ...DEFAULT_PALETTE };

    for (const [name, value] of Object.entries(deck.theme_palette)) {
      const color = toCssColor(value);
      if (color) merged[name] = color;
    }

    return merged;
  }

  const key = themeName || deck?.theme;
  if (key && PALETTES[key]) return PALETTES[key];

  return DEFAULT_PALETTE;
}

/**
 * The chart series colours for a deck.
 *
 * The deck's own colours win — they are the ones the .pptx was drawn with,
 * so a deck keeps its colours even after the setting changes. A deck with
 * none falls back to the theme named on it, and then to the default.
 */
export function seriesColors(deck, themeName) {
  const own = deck?.theme_series_colors;
  if (Array.isArray(own) && own.length) {
    return own.map(toCssColor).filter(Boolean);
  }

  const key = themeName || deck?.theme;
  return SERIES_COLORS[key] || SERIES_COLORS.light;
}
