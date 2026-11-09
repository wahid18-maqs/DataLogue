// Export dialog: confirms the generated deck and triggers the real download of
// the backend-produced .pptx file (fetched as a blob from the API service).

export default function ExportDialog({
  open,
  filename,
  downloadUrl,
  slideCount = 0,
  isDownloading = false,
  error = "",
  onDownload,
  onClose,
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-scrim/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Export presentation"
        className="relative w-full max-w-md rounded-2xl border border-slate-200 bg-surface p-6 shadow-xl"
      >
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
            <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.8}
                d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"
              />
            </svg>
          </div>

          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-bold text-slate-800">Export PowerPoint</h2>
            <p className="mt-1 text-xs text-slate-500">
              Download the editable presentation generated on the server.
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 transition-colors hover:text-slate-600"
            aria-label="Close export dialog"
          >
            ✕
          </button>
        </div>

        <dl className="mt-5 space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs">
          <div className="flex items-center justify-between gap-3">
            <dt className="text-slate-500">File name</dt>
            <dd className="truncate font-semibold text-slate-800">{filename || "—"}</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-slate-500">Format</dt>
            <dd className="font-semibold text-slate-800">PowerPoint (.pptx)</dd>
          </div>
          <div className="flex items-center justify-between gap-3">
            <dt className="text-slate-500">Slides</dt>
            <dd className="font-semibold text-slate-800">{slideCount}</dd>
          </div>
        </dl>

        {error && (
          <p className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </p>
        )}

        <div className="mt-6 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-300 bg-surface px-3.5 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onDownload}
            disabled={isDownloading || !downloadUrl}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-semibold text-on-accent transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isDownloading ? "Downloading…" : "Download PPTX"}
          </button>
        </div>
      </div>
    </div>
  );
}
