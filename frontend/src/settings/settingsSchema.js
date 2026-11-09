// The settings model.
//
// Settings are device-scoped: there is no login, so there is no account to
// hang them on. They live in the browser's localStorage under one key, as a
// single JSON blob, and are read once per session into shared app state
// (see SettingsContext.jsx) rather than re-read on every render.
//
// The shape is versioned. `meta.schema_version` is what makes an old blob
// recognisable, so a shape change can be migrated rather than discarded.

import { APP_THEMES } from "./appTheme";

export const STORAGE_KEY = "settings";

export const SCHEMA_VERSION = 2;

// The themes the deck generator can draw in. They match the themes the
// backend knows about (src/presentation_generator.py).
export const THEMES = [
  { id: "light", label: "Light", hint: "Clean white slides with a blue accent" },
  { id: "dark", label: "Dark", hint: "Slate slides for a dim room" },
  { id: "executive_navy", label: "Executive navy", hint: "Navy and gold, for a board pack" },
];

export const DETAIL_LEVELS = [
  { id: "concise", label: "Concise", hint: "The executive skim — three points a slide" },
  { id: "standard", label: "Standard", hint: "The normal briefing" },
  { id: "detailed", label: "Detailed", hint: "More points per slide, for a working document" },
];

// The retention windows. `null` means the workbooks are kept forever.
export const RETENTION_OPTIONS = [
  { id: 7, label: "7 days" },
  { id: 30, label: "30 days" },
  { id: 90, label: "90 days" },
  { id: null, label: "Forever" },
];

/**
 * The settings a fresh install has.
 *
 * The defaults live in code, not in storage, so a cleared browser and a
 * first-time visitor both get sane values without a backend call.
 */
export const DEFAULTS = {
  appearance: {
    app_theme: "light",
  },
  generation: {
    default_theme: "light",
    ai_narrative_enabled: true,
    slide_detail_level: "standard",
  },
  data_retention: {
    retention_days: 30,
  },
  ai_assistant: {
    show_supporting_data: true,
  },
  meta: {
    schema_version: SCHEMA_VERSION,
  },
};

const THEME_IDS = THEMES.map((theme) => theme.id);
const APP_THEME_IDS = APP_THEMES.map((theme) => theme.id);
const DETAIL_IDS = DETAIL_LEVELS.map((level) => level.id);
const RETENTION_IDS = RETENTION_OPTIONS.map((option) => option.id);

/** A fresh, deep copy of the defaults. */
export function defaultSettings() {
  return JSON.parse(JSON.stringify(DEFAULTS));
}

function pickChoice(value, allowed, fallback) {
  return allowed.includes(value) ? value : fallback;
}

/**
 * Bring a stored blob up to the current shape.
 *
 * A blob from an older version of the app is upgraded field by field, and
 * a field that is missing or out of range falls back to its default. The
 * migration is deliberately forgiving: a settings blob is not worth losing
 * a user's choices over, but a broken one must not break the app.
 */
export function migrateSettings(stored) {
  const settings = defaultSettings();

  if (!stored || typeof stored !== "object" || Array.isArray(stored)) {
    return settings;
  }

  const appearance = stored.appearance;
  if (appearance && typeof appearance === "object") {
    settings.appearance.app_theme = pickChoice(
      appearance.app_theme,
      APP_THEME_IDS,
      DEFAULTS.appearance.app_theme
    );
  }

  const generation = stored.generation;
  if (generation && typeof generation === "object") {
    settings.generation.default_theme = pickChoice(
      generation.default_theme,
      THEME_IDS,
      DEFAULTS.generation.default_theme
    );
    if (typeof generation.ai_narrative_enabled === "boolean") {
      settings.generation.ai_narrative_enabled = generation.ai_narrative_enabled;
    }
    settings.generation.slide_detail_level = pickChoice(
      generation.slide_detail_level,
      DETAIL_IDS,
      DEFAULTS.generation.slide_detail_level
    );
  }

  const retention = stored.data_retention;
  if (retention && typeof retention === "object") {
    const days = retention.retention_days;
    if (days === null) {
      // `null` is a valid choice: it means the workbooks are kept forever.
      settings.data_retention.retention_days = null;
    } else if (RETENTION_IDS.includes(days)) {
      settings.data_retention.retention_days = days;
    }
  }

  const assistant = stored.ai_assistant;
  if (assistant && typeof assistant === "object") {
    if (typeof assistant.show_supporting_data === "boolean") {
      settings.ai_assistant.show_supporting_data = assistant.show_supporting_data;
    }
  }

  settings.meta.schema_version = SCHEMA_VERSION;
  return settings;
}

/**
 * Read the settings from storage, falling back to the defaults.
 *
 * A missing or corrupt blob is not an error: the defaults are written back
 * so the next read has something to read.
 */
export function readSettings(storage) {
  const target = storage ?? safeLocalStorage();

  if (!target) return defaultSettings();

  let raw = null;
  try {
    raw = target.getItem(STORAGE_KEY);
  } catch {
    // Storage can be unavailable — a private window, a blocked cookie
    // setting. The app still works; the settings just do not persist.
    return defaultSettings();
  }

  if (!raw) {
    const settings = defaultSettings();
    writeSettings(settings, target);
    return settings;
  }

  let parsed = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // A corrupt blob is replaced by the defaults rather than left in
    // place, so it cannot fail again on the next load.
    const settings = defaultSettings();
    writeSettings(settings, target);
    return settings;
  }

  // The migration is version-driven: it reads whatever shape the blob has
  // and produces the current one. An unknown future version is treated the
  // same as an old one — the fields it can still recognise are kept.
  const settings = migrateSettings(parsed);

  // The blob is rewritten only when the migration actually changed it, so
  // an up-to-date blob is left alone and the app does not write on every
  // load.
  if (!sameShape(parsed, settings)) {
    writeSettings(settings, target);
  }

  return settings;
}

/**
 * Whether a stored blob is already the shape the migration produced.
 *
 * The comparison is on the fields the app knows about, so a blob carrying
 * extra keys is not rewritten for the sake of it.
 */
function sameShape(stored, settings) {
  if (!stored || typeof stored !== "object") return false;

  const generation = stored.generation || {};
  const retention = stored.data_retention || {};
  const assistant = stored.ai_assistant || {};
  const appearance = stored.appearance || {};
  const meta = stored.meta || {};

  return (
    appearance.app_theme === settings.appearance.app_theme &&
    generation.default_theme === settings.generation.default_theme &&
    generation.ai_narrative_enabled === settings.generation.ai_narrative_enabled &&
    generation.slide_detail_level === settings.generation.slide_detail_level &&
    retention.retention_days === settings.data_retention.retention_days &&
    assistant.show_supporting_data === settings.ai_assistant.show_supporting_data &&
    meta.schema_version === settings.meta.schema_version
  );
}

/** Write the settings to storage. A failure is not fatal. */
export function writeSettings(settings, storage) {
  const target = storage ?? safeLocalStorage();
  if (!target) return false;

  try {
    target.setItem(STORAGE_KEY, JSON.stringify(settings));
    return true;
  } catch {
    return false;
  }
}

function safeLocalStorage() {
  try {
    if (typeof window === "undefined" || !window.localStorage) return null;
    return window.localStorage;
  } catch {
    return null;
  }
}
