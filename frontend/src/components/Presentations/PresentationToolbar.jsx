// Top toolbar for the presentation workspace: the Generate Presentation,
// Regenerate Presentation, Edit and Export PPTX actions, aligned to the left.
//
// Regenerate and Edit only appear once a deck exists — there is nothing to
// improve or edit before the first presentation has been generated.

export default function PresentationToolbar({
  isGenerating = false,
  hasDeck = false,
  onGenerate,
  onRegenerate,
  onEdit,
  onExport,
}) {
  return (
    <header className="flex flex-wrap items-center justify-start gap-2 border-b border-slate-200 bg-surface px-5 py-3">
      <button
        type="button"
        onClick={onGenerate}
        disabled={isGenerating}
        className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-semibold text-on-accent shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M12 4v16m8-8H4"
          />
        </svg>
        {isGenerating ? "Generating…" : "Generate Presentation"}
      </button>

      {hasDeck && (
        <button
          type="button"
          onClick={onRegenerate}
          disabled={isGenerating}
          title="Rewrite the presentation's narrative to follow your suggestions"
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-surface px-3.5 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
          Regenerate Presentation
        </button>
      )}

      {hasDeck && (
        <button
          type="button"
          onClick={onEdit}
          disabled={isGenerating}
          title="Edit the slide text directly and re-render the deck"
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-surface px-3.5 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
            />
          </svg>
          Edit
        </button>
      )}

      <button
        type="button"
        onClick={onExport}
        disabled={!hasDeck}
        title={hasDeck ? "Download the generated PPTX file" : "Generate a presentation first"}
        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-surface px-3.5 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"
          />
        </svg>
        Export PPTX
      </button>
    </header>
  );
}
