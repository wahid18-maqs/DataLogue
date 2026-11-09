// The app's own theme.
//
// This is separate from the deck themes in settingsSchema: the deck themes
// decide how a PowerPoint is drawn, this one decides how the app is drawn.
//
// The theme is applied by setting `data-theme` on the root element. The
// palette itself lives in CSS custom properties (see index.css), so the
// change is one attribute rather than a re-render of every component.

/** The themes the app can be drawn in. */
export const APP_THEMES = [
  { id: "light", label: "Light", hint: "The usual pale interface" },
  { id: "dark", label: "Dark", hint: "A dark interface, for a dim room" },
];

const APP_THEME_IDS = APP_THEMES.map((theme) => theme.id);

export const DEFAULT_APP_THEME = "light";

/** Whether a value is a theme the app knows about. */
export function isAppTheme(value) {
  return APP_THEME_IDS.includes(value);
}

/**
 * Put the theme on the document.
 *
 * The attribute goes on `<html>` so the palette covers the whole page,
 * including the parts React does not own. A document without a document
 * element — in a server render, say — is left alone rather than throwing.
 */
export function applyAppTheme(theme, doc = typeof document === "undefined" ? null : document) {
  const root = doc?.documentElement;
  if (!root) return null;

  const value = isAppTheme(theme) ? theme : DEFAULT_APP_THEME;

  if (value === DEFAULT_APP_THEME) {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", value);
  }

  return value;
}
