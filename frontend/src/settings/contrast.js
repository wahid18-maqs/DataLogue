// The contrast audit.
//
// Every text colour in the app is a token, and every token has a value in
// both themes. A token that is legible on white can still be illegible on
// a dark background, so the two are checked separately: the light theme
// against white, the dark theme against the dark surfaces.
//
// The ratios are computed here rather than checked by eye, because a
// colour that looks fine in one place stops being fine when the same
// token is used on a darker surface.
//
// The palette itself is not written down here. It is read out of index.css
// by `readPalettesFromCss`, so the audit always measures the colours the
// app actually ships, rather than a copy of them that can drift.

/** The light theme, copied from index.css. */
export const LIGHT = {
  page: "#f4f6f9",
  surface: "#ffffff",
  panel: "#ffffff",
  drawer: "#f8fafc",
  fill: "#cbd5e1",
  slate50: "#f8fafc",
  slate100: "#cbd3de",
  slate200: "#c3ccd8",
  slate300: "#bcc6d4",
  slate400: "#5f6f85",
  slate500: "#64748b",
  slate600: "#475569",
  slate700: "#334155",
  slate800: "#1e293b",
  slate900: "#0f172a",
  blue50: "#eff6ff",
  blue100: "#dbeafe",
  blue200: "#bfdbfe",
  blue300: "#93c5fd",
  blue400: "#60a5fa",
  blue500: "#3b82f6",
  blue600: "#2563eb",
  blue700: "#1d4ed8",
  rose50: "#fff1f2",
  rose100: "#ffe4e6",
  rose200: "#fecdd3",
  rose500: "#f43f5e",
  rose600: "#e11d48",
  rose700: "#be123c",
  emerald50: "#ecfdf5",
  emerald100: "#d1fae5",
  emerald200: "#a7f3d0",
  emerald500: "#10b981",
  emerald600: "#059669",
  emerald700: "#047857",
  amber50: "#fffbeb",
  amber100: "#fef3c7",
  amber200: "#fde68a",
  amber600: "#d97706",
  amber700: "#b45309",
  amber800: "#92400e",
  indigo50: "#eef2ff",
  indigo500: "#6366f1",
  indigo600: "#4f46e5",
  indigo700: "#4338ca",
  onAccent: "#ffffff",
  code: "#0f172a",
  codeText: "#e2e8f0",
};

/** The dark theme, copied from index.css. */
export const DARK = {
  page: "#212121",
  surface: "#2f2f2f",
  panel: "#171717",
  drawer: "#171717",
  fill: "#525252",
  slate50: "#383838",
  slate100: "#373737",
  slate200: "#4c4c4c",
  slate300: "#404040",
  slate400: "#b0b8c4",
  slate500: "#c0c6d0",
  slate600: "#d0d6e0",
  slate700: "#dce2ea",
  slate800: "#e2e8f0",
  slate900: "#f1f5f9",
  blue50: "#252d38",
  blue100: "#2c3644",
  blue200: "#3a475a",
  blue300: "#6084b2",
  blue400: "#7ea2cc",
  blue500: "#94b4da",
  blue600: "#7ea2cc",
  blue700: "#a0c0e4",
  rose50: "#3a2326",
  rose100: "#462a2d",
  rose200: "#60383c",
  rose500: "#d6767e",
  rose600: "#e2949a",
  rose700: "#eebabe",
  emerald50: "#203028",
  emerald100: "#283a30",
  emerald200: "#385042",
  emerald500: "#58b284",
  emerald600: "#7ac29c",
  emerald700: "#a2d6b6",
  amber50: "#382e18",
  amber100: "#44381e",
  amber200: "#5c4a26",
  amber600: "#d0a854",
  amber700: "#e0c07a",
  amber800: "#ecd6a8",
  indigo50: "#262a44",
  indigo500: "#828cbe",
  indigo600: "#949ecc",
  indigo700: "#b0b8de",
  onAccent: "#0c0c0c",
  code: "#141414",
  codeText: "#d1d1d1",
};

/**
 * The palettes as they are actually written in index.css.
 *
 * The stylesheet is the source of truth for the colours, so the audit
 * reads them back out of it rather than trusting the copies above. A
 * token that is renamed or retuned in the CSS is then measured as it
 * ships, and a copy that has drifted shows up as a mismatch.
 *
 * @param {string} css  The contents of index.css.
 * @returns {{light: object, dark: object}} The palettes, keyed by token.
 */
export function palettesFromCss(css) {
  return {
    light: readBlock(css, ":root"),
    dark: readBlock(css, '[data-theme="dark"]'),
  };
}

/** The camelCase name a CSS custom property is known by. */
function tokenName(property) {
  const bare = property.replace(/^--/, "");
  return bare.replace(/-([a-z0-9])/g, (_, letter) => letter.toUpperCase());
}

/**
 * The declarations of one selector, with every `var()` resolved.
 *
 * A declaration may point at another variable (`--slate-900: var(--text-primary)`),
 * so the references are followed until only plain channel values are left.
 */
function readBlock(css, selector) {
  const start = css.indexOf(selector);
  if (start === -1) return {};

  const open = css.indexOf("{", start);
  if (open === -1) return {};

  // The block ends at the matching brace.
  let depth = 0;
  let close = -1;
  for (let at = open; at < css.length; at += 1) {
    if (css[at] === "{") depth += 1;
    else if (css[at] === "}") {
      depth -= 1;
      if (depth === 0) {
        close = at;
        break;
      }
    }
  }
  if (close === -1) return {};

  const body = css.slice(open + 1, close);
  const values = {};
  for (const match of body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    values[match[1]] = match[2].trim();
  }

  const resolved = {};
  for (const [property, raw] of Object.entries(values)) {
    const value = resolve(raw, values, 0);
    if (!value) continue;
    const channels = value.split(/\s+/).map(Number);
    if (channels.length !== 3 || channels.some((n) => Number.isNaN(n))) continue;
    resolved[tokenName(property)] = channels
      .map((n) => Math.round(n).toString(16).padStart(2, "0"))
      .join("");
  }
  return resolved;
}

/** Follow the `var()` references in a value until it is a plain one. */
function resolve(raw, values, depth) {
  if (depth > 8) return raw;
  const match = raw.match(/^var\(\s*(--[\w-]+)\s*\)$/);
  if (!match) return raw;
  const next = values[match[1]];
  if (next === undefined) return raw;
  return resolve(next, values, depth + 1);
}

/** The relative luminance of a colour. */
function luminance(hex) {
  // The leading '#' is not part of the digits, so it is dropped first.
  const digits = hex.replace("#", "");
  const channels = [0, 2, 4].map((at) => {
    const value = parseInt(digits.slice(at, at + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return (
    0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
  );
}

/** The contrast ratio between two colours, from 1 to 21. */
export function contrastRatio(foreground, background) {
  const one = luminance(foreground);
  const two = luminance(background);
  const lighter = Math.max(one, two);
  const darker = Math.min(one, two);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * The pairs that are actually used.
 *
 * Each one names a piece of the interface, the token its text is drawn in,
 * and the token it sits on. The `kind` says how strict the bar is: body
 * text has to clear 4.5, a border only has to be visible.
 */
export const CONTRAST_PAIRS = [
  { label: "the page title", text: "slate900", on: "page", kind: "text" },
  { label: "a section title", text: "slate800", on: "surface", kind: "text" },
  { label: "a section description", text: "slate400", on: "surface", kind: "text" },
  { label: "a control label", text: "slate700", on: "surface", kind: "text" },
  { label: "a control hint", text: "slate400", on: "surface", kind: "text" },
  { label: "a search placeholder", text: "slate400", on: "surface", kind: "text" },
  { label: "an empty state message", text: "slate400", on: "surface", kind: "text" },
  { label: "a sidebar nav item", text: "slate600", on: "panel", kind: "text" },
  { label: "a selected button", text: "blue700", on: "blue50", kind: "text" },
  { label: "an unselected button", text: "slate600", on: "surface", kind: "text" },
  { label: "an error message", text: "rose700", on: "rose50", kind: "text" },
  { label: "a success message", text: "emerald700", on: "emerald50", kind: "text" },
  { label: "the text on an accent", text: "onAccent", on: "blue600", kind: "text" },
  { label: "a code block", text: "codeText", on: "code", kind: "text" },
  { label: "a card border", text: "slate200", on: "surface", kind: "border" },
  { label: "an edge on the page", text: "slate300", on: "page", kind: "border" },
  { label: "a hairline in a panel", text: "slate100", on: "panel", kind: "border" },
  { label: "a progress bar on its track", text: "indigo700", on: "fill", kind: "shape" },
  { label: "an inactive step on its track", text: "slate500", on: "fill", kind: "shape" },
];

/** The bar a pair has to clear. */
const THRESHOLDS = { text: 4.5, border: 1.4, shape: 3 };

/**
 * Every pair that falls short, in either theme.
 *
 * A pair that is fine in one theme and not in the other is the interesting
 * case: it is a token that was tuned for the theme it was not used in.
 */
export function contrastFailures() {
  const failures = [];

  for (const [theme, palette] of [
    ["light", LIGHT],
    ["dark", DARK],
  ]) {
    for (const pair of CONTRAST_PAIRS) {
      const ratio = contrastRatio(palette[pair.text], palette[pair.on]);
      const bar = THRESHOLDS[pair.kind];
      if (ratio < bar) {
        failures.push({
          theme,
          label: pair.label,
          ratio: Math.round(ratio * 100) / 100,
          needed: bar,
        });
      }
    }
  }

  return failures;
}
