// Dynamic activity table with consistent columns, formatting, and pagination.

import { useMemo, useState } from "react";

const PAGE_OPTIONS = [10, 25, 50];

function isDateColumn(column, value) {
  const name = column.toLowerCase();
  return (
    name.includes("date") ||
    name.includes("time") ||
    (typeof value === "string" && /^\d{4}-\d{2}-\d{2}(?:[t ]|$)/i.test(value))
  );
}

function isNumericColumn(column, rows) {
  const values = rows
    .map((row) => row[column])
    .filter((value) => value !== null && value !== undefined && value !== "");
  if (!values.length) return false;
  return values.every((value) => typeof value === "number" || (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value.replace(/,/g, "")))));
}

function isCurrencyColumn(column) {
  return /(?:[$€£₹]|amount|revenue|sales|price|cost|profit|value|total)/i.test(column);
}

function formatDate(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toISOString().slice(0, 10);
}

function formatCell(value, column, numeric, currency) {
  if (value === null || value === undefined || value === "") return "—";
  if (isDateColumn(column, value)) return formatDate(value);
  if (!numeric) return String(value);

  const number = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(number)) return String(value);
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: currency || !Number.isInteger(number) ? 2 : 0,
    maximumFractionDigits: 2,
  }).format(number);
}

function StatusPill({ value }) {
  const text = String(value);
  const normalized = text.toLowerCase();
  const tone = ["delivered", "completed", "paid", "success", "active", "approved"].some((item) => normalized.includes(item))
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : ["pending", "processing", "in progress", "hold"].some((item) => normalized.includes(item))
      ? "border-amber-200 bg-amber-50 text-amber-700"
      : ["cancelled", "refunded", "failed", "returned", "rejected"].some((item) => normalized.includes(item))
        ? "border-rose-200 bg-rose-50 text-rose-700"
        : "border-slate-200 bg-fill text-text-secondary";

  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}>{text}</span>;
}

export default function LatestReviews({ table }) {
  const [pageSize, setPageSize] = useState(10);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState(null);

  const { title = "Recent Activity", columns = [], rows = [], total_rows = rows.length } = table || {};
  const columnInfo = useMemo(
    () => columns.map((column) => ({
      name: column,
      numeric: isNumericColumn(column, rows),
      currency: isCurrencyColumn(column),
      status: /status|state|stage/i.test(column),
    })),
    [columns, rows]
  );

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const info = columnInfo.find((item) => item.name === sort.column);
    return [...rows].sort((left, right) => {
      const a = left[sort.column];
      const b = right[sort.column];
      if (info?.numeric) return (Number(a) || 0) - (Number(b) || 0) || (sort.direction === "asc" ? 1 : -1);
      return String(a ?? "").localeCompare(String(b ?? ""), undefined, { numeric: true }) * (sort.direction === "asc" ? 1 : -1);
    });
  }, [rows, sort, columnInfo]);

  const pageCount = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const pageRows = sortedRows.slice((safePage - 1) * pageSize, safePage * pageSize);
  const start = sortedRows.length ? (safePage - 1) * pageSize + 1 : 0;
  const end = Math.min(safePage * pageSize, sortedRows.length);

  if (!table || !columns.length) return null;

  const handleSort = (column) => {
    setPage(1);
    setSort((current) => current?.column === column
      ? { column, direction: current.direction === "asc" ? "desc" : "asc" }
      : { column, direction: "asc" });
  };

  return (
    <section className="rounded-xl border border-slate-200/80 bg-surface p-5 shadow-sm">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-bold tracking-tight text-text-primary">{title}</h2>
          <p className="text-xs text-text-secondary">
            Showing {start.toLocaleString()}-{end.toLocaleString()} of {Number(total_rows).toLocaleString()}
          </p>
        </div>
        <label className="flex items-center gap-2 text-xs text-text-secondary">
          Rows per page
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
            }}
            className="rounded-lg border border-slate-200 bg-surface px-2 py-1.5 text-text-primary"
          >
            {PAGE_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
          </select>
        </label>
      </div>

      <div className={`max-w-full overflow-x-auto rounded-lg border border-slate-200 ${pageSize > 25 ? "max-h-[34rem] overflow-y-auto" : ""}`}>
        <table className="w-max min-w-full table-auto text-left text-xs">
          <thead className="sticky top-0 z-10 border-b border-slate-200 bg-surface text-text-secondary">
            <tr>
              {columnInfo.map((info) => (
                <th key={info.name} className={`whitespace-nowrap px-3 py-3 font-semibold ${info.numeric ? "text-right" : ""}`}>
                  <button type="button" onClick={() => handleSort(info.name)} className="inline-flex items-center gap-1 hover:text-text-primary">
                    {info.name.replace(/_/g, " ")}
                    {sort?.column === info.name && (sort.direction === "asc" ? "↑" : "↓")}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 text-text-primary">
            {pageRows.map((row, index) => (
              <tr key={`${safePage}-${index}`} className="transition-colors odd:bg-fill/30 hover:bg-slate-50/60">
                {columnInfo.map((info) => (
                  <td key={info.name} className={`whitespace-nowrap px-3 py-3 ${info.numeric ? "text-right tabular-nums" : ""}`}>
                    {info.status ? <StatusPill value={row[info.name]} /> : formatCell(row[info.name], info.name, info.numeric, info.currency)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between gap-3 text-xs text-text-secondary">
        <span>Page {safePage} of {pageCount}</span>
        <div className="flex gap-2">
          <button type="button" disabled={safePage === 1} onClick={() => setPage((value) => value - 1)} className="rounded-lg border border-slate-200 bg-surface px-3 py-1.5 font-semibold disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
          <button type="button" disabled={safePage === pageCount} onClick={() => setPage((value) => value + 1)} className="rounded-lg border border-slate-200 bg-surface px-3 py-1.5 font-semibold disabled:cursor-not-allowed disabled:opacity-40">Next</button>
        </div>
      </div>
    </section>
  );
}
