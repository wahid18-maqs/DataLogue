// Pipeline stage list shared by the presentation generation UI.
//
// The backend advances the stage as real work happens, so this renders
// genuine progress rather than an artificial timer.

export const GENERATION_STAGES = [
  { id: "reading_spreadsheet", label: "Reading spreadsheet" },
  { id: "detecting_columns", label: "Detecting columns" },
  { id: "analyzing_data", label: "Analyzing data" },
  { id: "writing_narrative", label: "Writing the narrative" },
  { id: "generating_slides", label: "Generating slides" },
  { id: "preparing_powerpoint", label: "Preparing PowerPoint" },
];

export const FIRST_STAGE = GENERATION_STAGES[0].id;

export default function StageIndicator({ currentStage, failed = false }) {
  const activeIndex = GENERATION_STAGES.findIndex((stage) => stage.id === currentStage);

  return (
    <ol className="space-y-2">
      {GENERATION_STAGES.map((stage, index) => {
        const isCurrent = activeIndex === index;
        // A failed run marks the stage that broke; earlier stages stay done.
        const isDone = activeIndex > index || (activeIndex === -1 && !failed);
        const isFailed = failed && isCurrent;

        return (
          <li key={stage.id} className="flex items-center gap-2.5">
            <span
              className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold transition-colors ${
                isFailed
                  ? "bg-rose-500 text-on-accent"
                  : isDone
                    ? "bg-emerald-500 text-on-accent"
                    : isCurrent
                      ? "bg-blue-600 text-on-accent"
                      : "bg-fill text-slate-500"
              }`}
            >
              {isFailed ? "!" : isDone ? "✓" : index + 1}
            </span>
            <span
              className={`text-xs font-medium ${
                isFailed
                  ? "text-rose-700"
                  : isCurrent
                    ? "text-blue-700"
                    : isDone
                      ? "text-slate-600"
                      : "text-slate-400"
              }`}
            >
              {stage.label}
            </span>
            {isCurrent && !failed && (
              <span className="ml-1 h-3 w-3 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
            )}
          </li>
        );
      })}
    </ol>
  );
}
