// The shared settings state.
//
// Settings are read from localStorage once, when the app starts, and held
// here. Components read them from this context rather than reaching into
// storage themselves, so a component render never touches the disk.
//
// Writes are debounced: a control that fires on every change (a select, a
// slider drag) would otherwise write on every step. The write lands after
// the user stops changing things, and on unmount so nothing is lost.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { defaultSettings, readSettings, writeSettings } from "./settingsSchema";
import { createDebouncedWriter } from "./debouncedWriter";
import { applyAppTheme } from "./appTheme";

// How long the app waits after the last change before it writes.
export const WRITE_DEBOUNCE_MS = 400;

const SettingsContext = createContext(null);

/**
 * The settings, and a setter for them.
 *
 * The setter takes the whole settings object. `update` is the convenience
 * form: it takes a function of the current settings and returns the next
 * one, so a caller never has to build the new object by hand.
 */
export function SettingsProvider({ children, initialSettings = null }) {
  // The initial value is read once, when the provider mounts.
  const [settings, setSettings] = useState(() => initialSettings || readSettings());

  // The current settings, mirrored in a ref. A change is computed against
  // this rather than inside a state updater, because the updater also
  // schedules the write — and a state updater must stay pure.
  const settingsRef = useRef(settings);

  // The writer that saves a change once it has settled.
  const writerRef = useRef(null);
  if (writerRef.current === null) {
    writerRef.current = createDebouncedWriter((value) => writeSettings(value), WRITE_DEBOUNCE_MS);
  }

  const flush = useCallback(() => {
    writerRef.current.flush();
  }, []);

  // Anything still pending is written when the app goes away.
  useEffect(() => flush, [flush]);

  // The app's own theme is applied to the document, so the palette covers
  // the whole page rather than only the parts React re-renders.
  useEffect(() => {
    applyAppTheme(settings.appearance.app_theme);
  }, [settings.appearance.app_theme]);

  const update = useCallback((change) => {
    const current = settingsRef.current;
    const next = typeof change === "function" ? change(current) : change;
    if (!next) return;

    settingsRef.current = next;
    setSettings(next);
    writerRef.current.schedule(next);
  }, []);

  // Writing straight through, for the moments when a change must be on
  // disk before something else happens.
  const updateNow = useCallback((change) => {
    const current = settingsRef.current;
    const next = typeof change === "function" ? change(current) : change;
    if (!next) return;

    settingsRef.current = next;
    setSettings(next);
    writerRef.current.flush();
    writeSettings(next);
  }, []);

  const reset = useCallback(() => {
    const defaults = defaultSettings();
    settingsRef.current = defaults;
    setSettings(defaults);
    writerRef.current.flush();
    writeSettings(defaults);
  }, []);

  const value = useMemo(
    () => ({ settings, update, updateNow, reset }),
    [settings, update, updateNow, reset]
  );

  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

/**
 * The settings and a way to change them.
 *
 * Outside a provider this returns the defaults, so a component rendered on
 * its own — in a test, say — still works.
 */
export function useSettings() {
  const context = useContext(SettingsContext);
  if (context) return context;

  return {
    settings: defaultSettings(),
    update: () => {},
    updateNow: () => {},
    reset: () => {},
  };
}

export default SettingsContext;
