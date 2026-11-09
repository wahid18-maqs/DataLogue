// The Settings page.
//
// Settings are device-scoped: there is no account, so they live in this
// browser. The page edits the shared settings state, which is written back
// to localStorage on a short delay (see SettingsContext).
//
// The page holds three groups — how decks are generated, how long workbooks
// are kept, and what the assistant shows — plus the destructive
// "Clear all workbooks" action, which asks for confirmation before it runs.

import { useCallback, useEffect, useState } from "react";
import {
  deleteAllWorkbooks,
  getErrorMessage,
  listWorkbooks,
  purgeWorkbooks,
} from "../services/api";
import { useSettings } from "../settings/SettingsContext";
import {
  DETAIL_LEVELS,
  RETENTION_OPTIONS,
  THEMES,
} from "../settings/settingsSchema";
import { APP_THEMES } from "../settings/appTheme";

function Section({ title, description, children }) {
  return (
    <section className="rounded-xl border border-slate-200/80 bg-surface p-5 shadow-sm">
      <h3 className="text-sm font-bold text-slate-800">{title}</h3>
      {description && <p className="mt-0.5 text-[11px] text-slate-400">{description}</p>}
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

function ChoiceRow({ label, hint, options, value, onChange, name }) {
  return (
    <div>
      <p className="text-xs font-semibold text-slate-700">{label}</p>
      {hint && <p className="mt-0.5 text-[11px] text-slate-400">{hint}</p>}
      <div className="mt-2 flex flex-wrap gap-2" role="radiogroup" aria-label={label}>
        {options.map((option) => {
          const isSelected = option.id === value;
          return (
            <button
              key={String(option.id)}
              type="button"
              name={name}
              role="radio"
              aria-checked={isSelected}
              title={option.hint}
              onClick={() => onChange(option.id)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold transition-colors ${
                isSelected
                  ? "border-blue-500 bg-blue-50 text-blue-700"
                  : "border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ToggleRow({ label, hint, checked, onChange }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <p className="text-xs font-semibold text-slate-700">{label}</p>
        {hint && <p className="mt-0.5 text-[11px] leading-relaxed text-slate-400">{hint}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-blue-600" : "bg-fill"
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-surface transition-all ${
            checked ? "left-[1.15rem]" : "left-0.5"
          }`}
        />
      </button>
    </div>
  );
}

export default function SettingsPanel({ onWorkbooksChanged }) {
  const { settings, update, reset } = useSettings();

  const [workbookCount, setWorkbookCount] = useState(0);
  const [isClearing, setIsClearing] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [isPurging, setIsPurging] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const refreshCount = useCallback(async () => {
    try {
      const result = await listWorkbooks();
      setWorkbookCount((result.workbooks || []).length);
    } catch (err) {
      // The count is a nicety; a failure to get it must not break the page.
      setWorkbookCount(0);
    }
  }, []);

  useEffect(() => {
    refreshCount();
  }, [refreshCount]);

  const setAppearance = useCallback(
    (value) => {
      update((current) => ({
        ...current,
        appearance: { ...current.appearance, app_theme: value },
      }));
    },
    [update]
  );

  const setGeneration = useCallback(
    (key) => (value) => {
      update((current) => ({
        ...current,
        generation: { ...current.generation, [key]: value },
      }));
    },
    [update]
  );

  const setRetention = useCallback(
    (value) => {
      update((current) => ({
        ...current,
        data_retention: { ...current.data_retention, retention_days: value },
      }));
    },
    [update]
  );

  const setAssistant = useCallback(
    (value) => {
      update((current) => ({
        ...current,
        ai_assistant: { ...current.ai_assistant, show_supporting_data: value },
      }));
    },
    [update]
  );

  const handleClearAll = useCallback(async () => {
    setIsClearing(true);
    setError("");
    setNotice("");
    try {
      const result = await deleteAllWorkbooks();
      setNotice(`Removed ${result.deleted || 0} workbook(s).`);
      setIsConfirming(false);
      await refreshCount();
      onWorkbooksChanged?.();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsClearing(false);
    }
  }, [refreshCount, onWorkbooksChanged]);

  const handlePurge = useCallback(async () => {
    const days = settings.data_retention.retention_days;
    if (days === null || days === undefined) return;

    setIsPurging(true);
    setError("");
    setNotice("");
    try {
      const result = await purgeWorkbooks(days);
      setNotice(`Removed ${result.deleted || 0} workbook(s) older than ${days} days.`);
      await refreshCount();
      onWorkbooksChanged?.();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsPurging(false);
    }
  }, [settings.data_retention.retention_days, refreshCount, onWorkbooksChanged]);

  const retentionDays = settings.data_retention.retention_days;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
        Settings
      </h1>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-xs text-emerald-700">
          {notice}
        </div>
      )}

      <Section
        title="Appearance"
        description="How this app looks on this screen. This is separate from the deck theme below."
      >
        <ChoiceRow
          label="App theme"
          hint="The colours of the app itself, in this browser."
          options={APP_THEMES}
          value={settings.appearance.app_theme}
          onChange={setAppearance}
          name="app_theme"
        />
      </Section>

      <Section
        title="Generation"
        description="How the PowerPoint decks are built. These are read at generation time."
      >
        <ChoiceRow
          label="Default theme"
          hint="The colours the deck is drawn in."
          options={THEMES}
          value={settings.generation.default_theme}
          onChange={setGeneration("default_theme")}
          name="default_theme"
        />

        <ChoiceRow
          label="Slide detail"
          hint="How much each slide carries."
          options={DETAIL_LEVELS}
          value={settings.generation.slide_detail_level}
          onChange={setGeneration("slide_detail_level")}
          name="slide_detail_level"
        />

        <ToggleRow
          label="AI narrative"
          hint="When off, the deck's prose is written from the data by rules rather than by the model, so no model is called."
          checked={settings.generation.ai_narrative_enabled}
          onChange={setGeneration("ai_narrative_enabled")}
        />
      </Section>

      <Section
        title="Data retention"
        description="How long uploaded workbooks are kept before they are purged."
      >
        <ChoiceRow
          label="Keep workbooks for"
          hint="The cleanup runs when you ask for it, not on a schedule."
          options={RETENTION_OPTIONS}
          value={retentionDays}
          onChange={setRetention}
          name="retention_days"
        />

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handlePurge}
            disabled={isPurging || retentionDays === null}
            title={
              retentionDays === null
                ? "Workbooks are kept forever, so there is nothing to purge."
                : "Remove the workbooks older than the retention window"
            }
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isPurging ? "Purging…" : "Purge now"}
          </button>
          <span className="text-[11px] text-slate-400">
            {workbookCount} workbook{workbookCount === 1 ? "" : "s"} stored
          </span>
        </div>
      </Section>

      <Section
        title="AI Assistant"
        description="What the assistant shows alongside its answers."
      >
        <ToggleRow
          label="Show supporting data"
          hint="The rows and numbers an answer was drawn from, so you can check it. When off, the assistant shows only its answer."
          checked={settings.ai_assistant.show_supporting_data}
          onChange={setAssistant}
        />
      </Section>

      <Section title="Data" description="The destructive actions, which need confirming.">
        {!isConfirming ? (
          <div>
            <button
              type="button"
              onClick={() => setIsConfirming(true)}
              className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-semibold text-rose-600 transition-colors hover:bg-rose-50"
            >
              Clear all workbooks
            </button>
            <p className="mt-1.5 text-[11px] text-slate-400">
              Removes every workbook, its file and its cached data. This cannot
              be undone.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2.5">
            <p className="text-xs font-semibold text-rose-700">
              Remove all {workbookCount} workbook{workbookCount === 1 ? "" : "s"}?
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-rose-600">
              The uploaded files go too, and nothing can be recovered.
            </p>
            <div className="mt-2.5 flex items-center gap-2">
              <button
                type="button"
                onClick={handleClearAll}
                disabled={isClearing}
                className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-on-accent transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isClearing ? "Removing…" : "Yes, remove everything"}
              </button>
              <button
                type="button"
                onClick={() => setIsConfirming(false)}
                disabled={isClearing}
                className="rounded-lg border border-slate-200 bg-surface px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div>
          <button
            type="button"
            onClick={reset}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50"
          >
            Reset settings to defaults
          </button>
          <p className="mt-1.5 text-[11px] text-slate-400">
            Puts the theme, the detail level, the retention window and the
            assistant back the way they were on a fresh install.
          </p>
        </div>
      </Section>
    </div>
  );
}
