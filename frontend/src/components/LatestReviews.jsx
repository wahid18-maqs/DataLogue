// Bottom Recent Orders / Latest Reviews table:
// - Title "Latest reviews" or "Latest orders" based on backend metadata
// - The first 10 records are shown inline; the rest are listed in a dropdown
// - Clean responsive table with horizontal scrolling on small screens
// - Dynamically renders returned columns without hardcoding ecommerce names
// - Status and currency styling heuristics

import { useMemo, useState } from "react";

const PREVIEW_ROWS = 10;

function formatCell(val) {
  if (val === null || val === undefined || val === "") return "—";
  if (typeof val === "number") {
    return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(2);
  }
  return String(val);
}

function StatusPill({ value }) {
  const str = String(value).toLowerCase();
  let color = "bg-slate-100 text-slate-700 border-slate-200";

  if (["delivered", "completed", "paid", "success", "active", "approved"].some((s) => str.includes(s))) {
    color = "bg-emerald-50 text-emerald-700 border-emerald-200";
  } else if (["pending", "processing", "in progress", "hold"].some((s) => str.includes(s))) {
    color = "bg-amber-50 text-amber-700 border-amber-200";
  } else if (["cancelled", "refunded", "failed", "returned", "rejected"].some((s) => str.includes(s))) {
    color = "bg-rose-50 text-rose-700 border-rose-200";
  }

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${color}`}>
      {value}
    </span>
  );
}

/**
 * One extra record, rendered as a compact row for the dropdown list.
 *
 * Only the columns that identify the record are shown — an order id, a
 * customer, a date — so the list stays readable next to the wide table.
 */
function DropdownRow({ row, columns }) {
  const labelColumns = useMemo(() => {
    const preferred = columns.filter((col) => {
      const lower = col.toLowerCase();
      return (
        lower.includes("id") ||
        lower.includes("name") ||
        lower.includes("date") ||
        lower.includes("time") ||
        lower.includes("status") ||
        lower.includes("amount") ||
        lower.includes("total") ||
        lower.includes("sales")
      );
    });
    return (preferred.length ? preferred : columns).slice(0, 4);
  }, [columns]);

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-xs text-slate-700 transition-colors hover:bg-slate-50">
      {labelColumns.map((col) => (
        <span key={col} className="flex items-center gap-1.5">
          <span className="font-medium text-slate-400">{col.replace(/_/g, " ")}</span>
          <span className="font-semibold text-slate-700">{formatCell(row[col])}</span>
        </span>
      ))}
    </li>
  );
}

export default function LatestReviews({ table }) {
  const [isOpen, setIsOpen] = useState(false);

  const { title = "Latest Orders & Activity", columns = [], rows = [], total_rows } = table || {};

  const previewRows = useMemo(() => rows.slice(0, PREVIEW_ROWS), [rows]);
  const extraRows = useMemo(() => rows.slice(PREVIEW_ROWS), [rows]);

  if (!table || !columns || columns.length === 0) {
    return null;
  }

  // Determine if a column represents a status or category pill
  const isStatusColumn = (col) => {
    const lower = col.toLowerCase();
    return lower.includes("status") || lower.includes("state") || lower.includes("stage");
  };

  return (
    <section className="rounded-xl border border-slate-200/80 bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-bold tracking-tight text-slate-900">{title}</h2>
          <p className="text-xs text-slate-500">
            Showing latest {previewRows.length} records{" "}
            {total_rows ? `out of ${total_rows.toLocaleString()} total entries` : ""}
          </p>
        </div>

        {extraRows.length > 0 && (
          <button
            type="button"
            onClick={() => setIsOpen((open) => !open)}
            aria-expanded={isOpen}
            className="inline-flex items-center gap-1.5 self-start rounded-lg border border-slate-300 bg-surface px-3 py-1.5 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 sm:self-auto"
          >
            <svg
              className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M19 9l-7 7-7-7" />
            </svg>
            {isOpen ? "Hide" : "Show"} next {extraRows.length}
          </button>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-slate-200 bg-slate-50/75 text-slate-600">
            <tr>
              {columns.map((col) => (
                <th key={col} className="whitespace-nowrap px-4 py-3 font-semibold">
                  {col.replace(/_/g, " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-slate-700">
            {previewRows.map((row, idx) => (
              <tr key={idx} className="transition-colors hover:bg-slate-50/50">
                {columns.map((col) => {
                  const cellVal = row[col];
                  return (
                    <td key={col} className="whitespace-nowrap px-4 py-3">
                      {isStatusColumn(col) ? (
                        <StatusPill value={cellVal} />
                      ) : (
                        <span className="font-normal">{formatCell(cellVal)}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {extraRows.length > 0 && isOpen && (
        <div className="mt-3 overflow-hidden rounded-lg border border-slate-200">
          <div className="border-b border-slate-200 bg-slate-50/75 px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            Next {extraRows.length} entries
          </div>
          <ul className="divide-y divide-slate-100 bg-surface">
            {extraRows.map((row, idx) => (
              <DropdownRow key={idx} row={row} columns={columns} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
