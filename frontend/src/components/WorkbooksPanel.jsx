// The Workbooks page.
//
// A workbook is one uploaded spreadsheet, with one sheet per tabular sheet
// inside it. The list shows the workbooks with their status and the
// one-line auto-summary; expanding one shows its sheets, and lets the
// user pick which sheet is active — the sheet the assistant and the PPT
// generator work with by default.
//
// A workbook that needs attention stays in the list, with the reason it
// needs attention and a Replace action, rather than disappearing.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  activateWorkbook,
  createWorkbook,
  deleteWorkbook,
  getErrorMessage,
  getWorkbook,
  listWorkbooks,
  replaceWorkbook,
  searchWorkbooks,
  setActiveSheet,
} from "../services/api";
import { FILTERS, SORTS, filterAndSort } from "./workbookList";

const ACCEPTED_EXTENSIONS = [".csv", ".xlsx", ".xls"];

// How long the search waits for the typing to pause before it runs.
const SEARCH_DEBOUNCE_MS = 300;

// How the status is shown. A workbook that needs attention is the only one
// that gets a colour, so the list stays quiet.
const STATUS_STYLES = {
  parsed: { label: "Ready", className: "bg-emerald-50 text-emerald-700" },
  needs_attention: { label: "Needs attention", className: "bg-amber-50 text-amber-700" },
  stale: { label: "Stale", className: "bg-slate-100 text-slate-500" },
  processing: { label: "Processing", className: "bg-blue-50 text-blue-600" },
  uploading: { label: "Uploading", className: "bg-slate-100 text-slate-500" },
};

function StatusBadge({ status }) {
  const style = STATUS_STYLES[status] || STATUS_STYLES.stale;
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${style.className}`}
    >
      {style.label}
    </span>
  );
}

function FileIcon({ fileType }) {
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
      <svg className="h-4.5 w-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.8}
          d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
        />
      </svg>
    </span>
  );
}

function SchemaTable({ schema }) {
  if (!schema?.length) return null;

  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200">
      <table className="w-full text-left text-[11px]">
        <thead>
          <tr className="bg-slate-50">
            <th className="px-2.5 py-1.5 font-semibold text-slate-500">Column</th>
            <th className="px-2.5 py-1.5 font-semibold text-slate-500">Type</th>
            <th className="px-2.5 py-1.5 font-semibold text-slate-500">Detail</th>
          </tr>
        </thead>
        <tbody>
          {schema.map((entry) => {
            let detail = "";
            if (entry.type === "number") {
              detail = `${entry.min} – ${entry.max}`;
            } else if (entry.type === "date") {
              detail = `${String(entry.from || "").slice(0, 10)} – ${String(entry.to || "").slice(0, 10)}`;
            } else if (entry.values) {
              detail = entry.values.slice(0, 4).join(", ");
            } else if (entry.distinct_count !== undefined) {
              detail = `${entry.distinct_count} distinct`;
            }
            return (
              <tr key={entry.name} className="border-t border-slate-100">
                <td className="px-2.5 py-1.5 font-medium text-slate-700">{entry.name}</td>
                <td className="px-2.5 py-1.5">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">
                    {entry.type}
                  </span>
                </td>
                <td className="max-w-[16rem] truncate px-2.5 py-1.5 font-mono text-[10px] text-slate-500">
                  {detail}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FindingsGrid({ findings }) {
  if (!findings || !Object.keys(findings).length) return null;

  const tiles = [];
  for (const [name, total] of Object.entries(findings.totals || {})) {
    tiles.push({ label: `Total ${name}`, value: Number(total).toLocaleString() });
  }
  for (const [name, count] of Object.entries(findings.unique_counts || {})) {
    // A column that already has a total tile does not need a second one.
    if (!findings.totals?.[name]) {
      tiles.push({ label: `Distinct ${name}`, value: Number(count).toLocaleString() });
    }
  }
  if (findings.concentration) {
    for (const [name, ratio] of Object.entries(findings.concentration)) {
      tiles.push({
        label: `Top ${name} share`,
        value: `${(Number(ratio) * 100).toFixed(1)}%`,
      });
    }
  }

  if (!tiles.length) return null;

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
      {tiles.slice(0, 8).map((tile) => (
        <div key={tile.label} className="rounded-lg border border-slate-200 bg-surface px-3 py-2">
          <p className="truncate text-[10px] font-medium text-slate-400">{tile.label}</p>
          <p className="mt-0.5 font-mono text-sm font-semibold text-slate-800">
            {tile.value}
          </p>
        </div>
      ))}
    </div>
  );
}

function SheetRow({ workbookId, sheet, isActive, onActivate, onError }) {
  const isUsable = sheet.status === "parsed";

  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-surface px-3 py-2">
      <span
        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${
          isUsable ? "bg-slate-100 text-slate-500" : "bg-amber-50 text-amber-600"
        }`}
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.8}
            d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
      </span>

      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-semibold text-slate-700">{sheet.name}</p>
        <p className="truncate text-[10px] text-slate-400">
          {isUsable
            ? `${sheet.row_count.toLocaleString()} rows · ${sheet.column_count} columns`
            : sheet.error_reason || "Not usable"}
        </p>
      </div>

      {isUsable && (
        <button
          type="button"
          onClick={() => onActivate(workbookId, sheet.id)}
          disabled={isActive}
          title={isActive ? "This is the active sheet" : "Make this the active sheet"}
          className={`shrink-0 rounded-lg px-2.5 py-1 text-[10px] font-semibold transition-colors ${
            isActive
              ? "bg-blue-50 text-blue-700"
              : "border border-slate-200 text-slate-600 hover:bg-slate-50"
          }`}
        >
          {isActive ? "Active" : "Make active"}
        </button>
      )}
    </div>
  );
}

export function WorkbookRow({ workbook, onChanged, onError, onUseWorkbook, onOverview, isActive }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [detail, setDetail] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isActivating, setIsActivating] = useState(false);
  const fileInputRef = useRef(null);

  const loadDetail = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await getWorkbook(workbook.id);
      setDetail(result.workbook);
    } catch (error) {
      onError?.(getErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, [workbook.id, onError]);

  const toggle = useCallback(() => {
    const next = !isExpanded;
    setIsExpanded(next);
    if (next && !detail) loadDetail();
  }, [isExpanded, detail, loadDetail]);

  const handleActivate = useCallback(
    async (workbookId, sheetId) => {
      try {
        await setActiveSheet(workbookId, sheetId);
        await loadDetail();
        onChanged?.();
      } catch (error) {
        onError?.(getErrorMessage(error));
      }
    },
    [loadDetail, onChanged, onError]
  );

  const handleReplace = useCallback(
    async (file) => {
      if (!file) return;
      try {
        await replaceWorkbook(workbook.id, file);
        setDetail(null);
        await loadDetail();
        onChanged?.();
      } catch (error) {
        onError?.(getErrorMessage(error));
      }
    },
    [workbook.id, loadDetail, onChanged, onError]
  );

  const handleDelete = useCallback(async () => {
    try {
      await deleteWorkbook(workbook.id);
      onChanged?.();
    } catch (error) {
      onError?.(getErrorMessage(error));
    }
  }, [workbook.id, onChanged, onError]);

  const activeSheetId = detail?.active_sheet_id || workbook.active_sheet_id;

  // The overview makes this workbook the active dataset and sends the
  // user to the dashboard, where it is drawn.
  const handleOverview = useCallback(async () => {
    setIsActivating(true);
    try {
      const result = await activateWorkbook(workbook.id, activeSheetId);
      onOverview?.(result);
    } catch (error) {
      onError?.(getErrorMessage(error));
    } finally {
      setIsActivating(false);
    }
  }, [workbook.id, activeSheetId, onOverview, onError]);

  return (
    <div className="rounded-xl border border-slate-200/80 bg-surface shadow-sm">
      <div className="flex items-center gap-3 p-4">
        <FileIcon fileType={workbook.file_type} />

        <button
          type="button"
          onClick={toggle}
          className="min-w-0 flex-1 text-left"
        >
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold text-slate-800">
              {workbook.file_name}
            </p>
            <StatusBadge status={workbook.status} />
          </div>
          <p className="mt-0.5 truncate text-[11px] text-slate-400">
            {workbook.sheets?.[0]?.auto_summary || "No summary yet"}
          </p>
        </button>

        <div className="flex shrink-0 items-center gap-1.5">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS.join(",")}
            className="hidden"
            onChange={(event) => {
              handleReplace(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
          {onOverview && (
            <button
              type="button"
              onClick={handleOverview}
              disabled={isActivating}
              title="Make this workbook the active dataset and show it on the dashboard"
              className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isActivating ? "Opening…" : "Overview"}
            </button>
          )}
          {onUseWorkbook && (
            <button
              type="button"
              onClick={() => onUseWorkbook(workbook)}
              title="Ask the assistant about this workbook"
              className={`rounded-lg px-2.5 py-1.5 text-[10px] font-semibold transition-colors ${
                isActive
                  ? "bg-blue-50 text-blue-700"
                  : "border border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {isActive ? "In use" : "Ask about this"}
            </button>
          )}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            title="Replace this file"
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-semibold text-slate-600 transition-colors hover:bg-slate-50"
          >
            Replace
          </button>
          <button
            type="button"
            onClick={handleDelete}
            title="Delete this workbook"
            className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-[10px] font-semibold text-rose-500 transition-colors hover:bg-rose-50"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={toggle}
            title={isExpanded ? "Collapse" : "Expand"}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            <svg
              className={`h-4 w-4 transition-transform ${isExpanded ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        </div>
      </div>

      {workbook.status === "needs_attention" && workbook.error_reason && (
        <div className="mx-4 mb-4 rounded-lg bg-amber-50 px-3 py-2">
          <p className="text-[10px] font-bold uppercase tracking-wider text-amber-600">
            Needs attention
          </p>
          <p className="mt-0.5 text-[11px] leading-relaxed text-amber-800">
            {workbook.error_reason}
          </p>
        </div>
      )}

      {isExpanded && (
        <div className="space-y-4 border-t border-slate-100 px-4 py-4">
          {isLoading && <p className="text-[11px] text-slate-400">Loading sheets…</p>}

          {detail && (
            <>
              <div>
                <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                  Sheets
                </p>
                <div className="space-y-2">
                  {detail.sheets.map((sheet) => (
                    <SheetRow
                      key={sheet.id}
                      workbookId={detail.id}
                      sheet={sheet}
                      isActive={sheet.id === activeSheetId}
                      onActivate={handleActivate}
                      onError={onError}
                    />
                  ))}
                </div>
              </div>

              {detail.sheets
                .filter((sheet) => sheet.id === activeSheetId && sheet.status === "parsed")
                .map((sheet) => (
                  <div key={sheet.id} className="space-y-3">
                    <div>
                      <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        Findings
                      </p>
                      <FindingsGrid findings={sheet.findings} />
                    </div>

                    <div>
                      <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        Schema
                      </p>
                      <SchemaTable schema={sheet.schema} />
                    </div>
                  </div>
                ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * A button that opens a list of choices.
 *
 * The menu closes when the pointer goes down outside it, when the choice
 * is made, and on Escape, so it never traps the user.
 */
function MenuButton({ label, icon, options, value, onChange, align = "left" }) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;

    const handlePointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) setIsOpen(false);
    };
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setIsOpen(false);
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  const selected = options.find((option) => option.id === value) || options[0];

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-surface px-3 py-2 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50"
      >
        {icon}
        {selected.label}
        <svg
          className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {isOpen && (
        <ul
          role="listbox"
          className={`absolute z-20 mt-1 w-44 overflow-hidden rounded-lg border border-slate-200 bg-surface py-1 shadow-lg ${
            align === "right" ? "right-0" : "left-0"
          }`}
        >
          {options.map((option) => {
            const isSelected = option.id === value;
            return (
              <li key={option.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => {
                    onChange(option.id);
                    setIsOpen(false);
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors ${
                    isSelected
                      ? "bg-blue-50 font-semibold text-blue-700"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {isSelected && (
                    <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                  <span className={isSelected ? "" : "pl-[1.375rem]"}>{option.label}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/**
 * The search field.
 *
 * The keyword is searched as it is typed, with a short delay so a long
 * word does not fire a request on every keystroke.
 */
function SearchBar({ value, onChange, isSearching, onClear }) {
  return (
    <div className="relative w-full max-w-[50rem]">
      <svg
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z"
        />
      </svg>

      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Search workbooks…"
        aria-label="Search inside your workbooks"
        className="w-full rounded-lg border border-slate-200 bg-surface py-2 pl-9 pr-9 text-xs text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      />

      {isSearching && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-slate-400">
          …
        </span>
      )}

      {!isSearching && value && (
        <button
          type="button"
          onClick={onClear}
          title="Clear the search"
          aria-label="Clear the search"
          className="absolute right-2.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </div>
  );
}

/**
 * One search result.
 *
 * The scope says where the keyword was found — the workbook's name, a
 * sheet's name, a column's name, or a row's value — and a row result
 * shows the row it was found in, so the hit can be understood.
 */
function SearchResult({ match }) {
  const scopeLabels = {
    workbook: "Workbook name",
    sheet: "Sheet name",
    column: "Column",
    row: "Row",
  };

  return (
    <li className="border-t border-slate-100 px-4 py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
          {scopeLabels[match.scope] || match.scope}
        </span>
        <span className="truncate text-xs font-semibold text-slate-800">
          {match.file_name}
        </span>
        {match.sheet_name && (
          <span className="truncate text-[11px] text-slate-400">
            {match.sheet_name}
          </span>
        )}
      </div>

      <p className="mt-1 text-[11px] text-slate-600">
        <span className="font-medium text-slate-500">{match.field}:</span>{" "}
        <span className="font-mono">{match.value}</span>
      </p>

      {match.row && (
        <p className="mt-1 truncate font-mono text-[10px] text-slate-400">
          {Object.entries(match.row)
            .map(([key, value]) => `${key}=${value}`)
            .join("  ·  ")}
        </p>
      )}
    </li>
  );
}

export default function WorkbooksPanel({ onUseWorkbook, onOverview, activeWorkbookId }) {
  const [workbooks, setWorkbooks] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef(null);

  // The search.
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");

  // The filter and the sort.
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("newest");

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const result = await listWorkbooks();
      setWorkbooks(result.workbooks || []);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  /**
   * The list as it is shown: filtered, then ordered.
   *
   * The filter narrows by status or by file type; the sort decides the
   * order. Both are applied to the list the client already has, so
   * changing one is instant.
   */
  const visibleWorkbooks = useMemo(
    () => filterAndSort(workbooks, filter, sort),
    [workbooks, filter, sort]
  );

  /**
   * Run the search as the keyword is typed.
   *
   * The request waits for a short pause, so typing a word does not fire
   * one request per letter, and a request that is still running when a
   * newer keyword arrives is ignored rather than allowed to overwrite the
   * newer results.
   */
  useEffect(() => {
    const trimmed = keyword.trim();
    if (!trimmed) {
      setResults(null);
      setSearchError("");
      setIsSearching(false);
      return undefined;
    }

    let isCurrent = true;
    setIsSearching(true);

    const timer = setTimeout(async () => {
      try {
        const result = await searchWorkbooks(trimmed);
        if (!isCurrent) return;
        setResults(result);
        setSearchError("");
      } catch (err) {
        if (!isCurrent) return;
        setSearchError(getErrorMessage(err));
      } finally {
        if (isCurrent) setIsSearching(false);
      }
    }, SEARCH_DEBOUNCE_MS);

    return () => {
      isCurrent = false;
      clearTimeout(timer);
    };
  }, [keyword]);

  const handleUpload = useCallback(
    async (file) => {
      if (!file) return;

      const lower = file.name.toLowerCase();
      if (!ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
        setError("Only .csv, .xlsx and .xls files are supported.");
        return;
      }

      setIsUploading(true);
      setError("");
      try {
        await createWorkbook(file);
        await refresh();
      } catch (err) {
        setError(getErrorMessage(err));
      } finally {
        setIsUploading(false);
      }
    },
    [refresh]
  );

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl">
        Workbooks
      </h1>

      <div className="flex flex-wrap items-center gap-3">
        <SearchBar
          value={keyword}
          onChange={setKeyword}
          isSearching={isSearching}
          onClear={() => setKeyword("")}
        />

        <MenuButton
          label="Filter"
          icon={
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 4h18l-7 8v7l-4 2v-9L3 4z"
              />
            </svg>
          }
          options={FILTERS}
          value={filter}
          onChange={setFilter}
        />

        <MenuButton
          label="Sort"
          align="right"
          icon={
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 6h13M3 12h9M3 18h5M17 12v8m0 0l-3-3m3 3l3-3"
              />
            </svg>
          }
          options={SORTS}
          value={sort}
          onChange={setSort}
        />

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={(event) => {
            handleUpload(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading}
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-semibold text-on-accent transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 4v16m8-8H4"
            />
          </svg>
          {isUploading ? "Processing…" : "Upload workbook"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
          {error}
        </div>
      )}

      {searchError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
          {searchError}
        </div>
      )}

      {results && (
        <section className="rounded-xl border border-slate-200/80 bg-surface shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
            <p className="text-xs font-bold text-slate-800">
              {results.total} match{results.total === 1 ? "" : "es"} for{" "}
              <span className="font-mono text-blue-700">“{results.keyword}”</span>
            </p>
            <p className="text-[10px] text-slate-400">
              {results.workbooks?.length || 0} workbook
              {(results.workbooks?.length || 0) === 1 ? "" : "s"} searched
            </p>
          </div>

          {results.matches?.length ? (
            <ul>
              {results.matches.map((match, index) => (
                <SearchResult key={`${match.workbook_id}-${match.scope}-${index}`} match={match} />
              ))}
            </ul>
          ) : (
            <p className="px-4 py-6 text-center text-xs text-slate-400">
              Nothing in the workbooks matches “{results.keyword}”.
            </p>
          )}
        </section>
      )}

      {isLoading && <p className="text-xs text-slate-400">Loading workbooks…</p>}

      {!isLoading && !workbooks.length && !error && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-surface p-10 text-center">
          <p className="text-sm font-semibold text-slate-700">No workbooks yet</p>
          <p className="mx-auto mt-1 max-w-md text-[11px] leading-relaxed text-slate-400">
            Upload a CSV or Excel file to create one. It is parsed once, and
            the assistant and the deck generator both read it from there.
          </p>
        </div>
      )}

      {!results && !isLoading && workbooks.length && !visibleWorkbooks.length && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-surface p-10 text-center">
          <p className="text-sm font-semibold text-slate-700">
            No workbooks match this filter
          </p>
          <p className="mx-auto mt-1 max-w-md text-[11px] leading-relaxed text-slate-400">
            Change the filter to see the rest of them.
          </p>
          <button
            type="button"
            onClick={() => setFilter("all")}
            className="mt-3 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50"
          >
            Show all workbooks
          </button>
        </div>
      )}

      {!results &&
        visibleWorkbooks.map((workbook) => (
          <WorkbookRow
            key={workbook.id}
            workbook={workbook}
            onChanged={refresh}
            onError={setError}
            onUseWorkbook={onUseWorkbook}
            onOverview={onOverview}
            isActive={workbook.id === activeWorkbookId}
          />
        ))}
    </div>
  );
}
