// The panel that appears after "Regenerate Presentation" is clicked: the
// requester types what they would like changed about the narrative, and the
// agent rewrites the prose to follow it.
//
// The suggestions steer the narrative and can request grounded structural
// changes. The backend validates any added chart against the dataset before
// rendering it, so the model never supplies chart figures directly.

import { useEffect, useRef } from "react";

// The backend bounds the suggestion length; the counter mirrors it.
const MAX_SUGGESTION_CHARS = 2000;

export default function SuggestionsPanel({
  value = "",
  onChange,
  onSubmit,
  onCancel,
  isGenerating = false,
}) {
  const textareaRef = useRef(null);

  // Focus the field as soon as the panel appears, so the user can type
  // straight away.
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const remaining = MAX_SUGGESTION_CHARS - value.length;
  const canSubmit = value.trim().length > 0 && !isGenerating;

  const handleKeyDown = (event) => {
    // Enter submits, Shift+Enter adds a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSubmit) onSubmit();
    }
  };

  return (
    <div className="rounded-xl border border-blue-100 bg-slate-50/70 p-4">
      <label
        htmlFor="presentation-suggestions"
        className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wider text-slate-400"
      >
        What should we change?
      </label>

      <textarea
        id="presentation-suggestions"
        ref={textareaRef}
        value={value}
        onChange={(event) => onChange(event.target.value.slice(0, MAX_SUGGESTION_CHARS))}
        onKeyDown={handleKeyDown}
        disabled={isGenerating}
        rows={4}
        placeholder="e.g. Lead with the Furniture segment, make the tone more cautious, and focus the recommendations on the North region."
        className="w-full resize-y rounded-lg border border-slate-300 bg-surface px-3 py-2 text-sm text-slate-700 shadow-sm outline-none transition-colors placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:opacity-60"
      />

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-slate-500">
          Ask to rewrite content, add/remove/reorder slides, or add a chart
          using an existing dataset column. Figures are always recomputed from
          the active data.
          {remaining < 200 && (
            <span className="ml-1 font-medium text-slate-400">{remaining} left</span>
          )}
        </p>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={isGenerating}
            className="rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-on-accent shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isGenerating ? "Regenerating…" : "Regenerate"}
          </button>
        </div>
      </div>
    </div>
  );
}
