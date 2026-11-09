// Dataset upload widget: drag & drop, browse button, and an upload progress bar.
// Accepts CSV and Excel files and posts them to /upload, reporting the result
// to the parent component.
//
// Once a dataset is loaded the large dropzone collapses into a slim summary
// bar with a "Select another file" action, so the charts below get the room.

import { useCallback, useRef, useState } from "react";
import { getErrorMessage, uploadDataset } from "../services/api";

const ACCEPTED_EXTENSIONS = [".csv", ".xlsx", ".xls"];

export default function FileUpload({ onUploadSuccess, onUploadError, onClearError, dataset, error }) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [fileName, setFileName] = useState("");

  const uploadedName = dataset?.original_filename || dataset?.stored_filename || "";
  const schema = dataset?.schema || {};
  const rowCount = schema.total_rows ?? schema.rows;
  const columnCount = schema.total_columns ?? schema.columns;

  const handleFile = useCallback(
    async (file) => {
      if (!file) return;

      const lowerName = file.name.toLowerCase();
      if (!ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext))) {
        onUploadError?.("Only .csv, .xlsx and .xls files are supported.");
        return;
      }

      setFileName(file.name);
      setIsUploading(true);
      setProgress(0);

      try {
        const data = await uploadDataset(file, setProgress);
        onUploadSuccess?.(data);
      } catch (error) {
        onUploadError?.(getErrorMessage(error));
      } finally {
        setIsUploading(false);
      }
    },
    [onUploadSuccess, onUploadError]
  );

  const handleDrop = useCallback(
    (event) => {
      event.preventDefault();
      setIsDragging(false);
      handleFile(event.dataTransfer.files?.[0]);
    },
    [handleFile]
  );

  const openPicker = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const input = (
    <input
      ref={inputRef}
      type="file"
      accept=".csv,.xlsx,.xls"
      className="hidden"
      onChange={(event) => {
        handleFile(event.target.files?.[0]);
        event.target.value = "";
      }}
    />
  );

  // Upload in flight: always show the full dropzone with the progress bar.
  if (isUploading) {
    return (
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`rounded-2xl border-2 border-dashed p-10 text-center transition-colors ${
          isDragging ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-surface"
        }`}
      >
        {input}

        <p className="text-lg font-semibold text-slate-700">
          Drag & drop your CSV or Excel file here
        </p>
        <p className="mt-1 text-sm text-slate-500">or</p>

        <button
          type="button"
          onClick={openPicker}
          disabled={isUploading}
          className="mt-3 inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-on-accent transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Browse Files
        </button>

        {fileName && <p className="mt-4 text-sm text-slate-600">Selected: {fileName}</p>}

        <div className="mx-auto mt-4 max-w-sm">
          <div className="h-2 w-full overflow-hidden rounded-full bg-fill">
            <div
              className="h-full rounded-full bg-indigo-700 transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-slate-500">Uploading… {progress}%</p>
        </div>
      </div>
    );
  }

  // A dataset is loaded: collapse to a slim confirmation strip.
  if (uploadedName && !error) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 overflow-hidden rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3 transition-all duration-300">
        {input}

        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          </span>
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold text-slate-700">{uploadedName}</p>
            <p className="text-[11px] text-slate-500">
              {rowCount != null && columnCount != null
                ? `${rowCount} rows · ${columnCount} columns`
                : "Dataset loaded"}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={openPicker}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50"
        >
          Choose a different file
        </button>
      </div>
    );
  }

  // Nothing uploaded yet: the full dropzone.
  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={`overflow-hidden rounded-2xl border-2 border-dashed p-10 text-center transition-all duration-300 ${
        isDragging ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-surface"
      }`}
    >
      {input}

      <p className="text-lg font-semibold text-slate-700">
        Drag & drop your CSV or Excel file here
      </p>
      <p className="mt-1 text-sm text-slate-500">or</p>

      <button
        type="button"
        onClick={openPicker}
        className="mt-3 inline-flex items-center rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-on-accent transition-colors hover:bg-indigo-700"
      >
        Browse Files
      </button>

      {error ? (
        <div className="mx-auto mt-4 flex max-w-md items-start justify-between gap-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-left text-xs text-rose-700">
          <span>{error}</span>
          <button
            type="button"
            onClick={onClearError}
            className="font-semibold text-rose-500 hover:text-rose-700"
            aria-label="Dismiss upload error"
          >
            ✕
          </button>
        </div>
      ) : (
        <p className="mt-4 text-xs text-slate-400">
          Upload a CSV above to generate KPIs, trends, and distributions.
        </p>
      )}
    </div>
  );
}
