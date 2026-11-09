// The filter and the sort for the workbooks list.
//
// Both are applied to the list the client already has, rather than to the
// request, so changing one is instant and costs nothing.
//
// The logic lives on its own, away from the component, so it can be
// checked without rendering anything.

// The filters the list can be narrowed by.
export const FILTERS = [
  { id: "all", label: "All workbooks" },
  { id: "needs_attention", label: "Needs attention" },
  { id: "parsed", label: "Ready" },
  { id: "stale", label: "Stale" },
  { id: "csv", label: "CSV files" },
  { id: "xlsx", label: "Excel files" },
];

// The orders the list can be shown in.
export const SORTS = [
  { id: "newest", label: "Newest first" },
  { id: "oldest", label: "Oldest first" },
  { id: "name_asc", label: "Name (A–Z)" },
  { id: "name_desc", label: "Name (Z–A)" },
  { id: "largest", label: "Most rows" },
];

/** How many rows a workbook holds, across all its sheets. */
export function rowCount(workbook) {
  return (workbook.sheets || []).reduce(
    (total, sheet) => total + (sheet.row_count || 0),
    0
  );
}

/** Whether a workbook passes the filter. */
export function matchesFilter(workbook, filter) {
  switch (filter) {
    case "needs_attention":
      return workbook.status === "needs_attention";
    case "parsed":
      return workbook.status === "parsed";
    case "stale":
      return workbook.status === "stale";
    case "csv":
      return workbook.file_type === "csv";
    case "xlsx":
      return workbook.file_type === "xlsx" || workbook.file_type === "xls";
    case "all":
    default:
      return true;
  }
}

/**
 * The list as it is shown: filtered, then ordered.
 *
 * The workbooks are copied before they are sorted, so the list the caller
 * holds is never reordered underneath it.
 */
export function filterAndSort(workbooks, filter, sort) {
  const filtered = (workbooks || []).filter((workbook) =>
    matchesFilter(workbook, filter)
  );

  const sorted = [...filtered];

  if (sort === "newest") {
    sorted.sort((a, b) =>
      String(b.uploaded_at).localeCompare(String(a.uploaded_at))
    );
  } else if (sort === "oldest") {
    sorted.sort((a, b) =>
      String(a.uploaded_at).localeCompare(String(b.uploaded_at))
    );
  } else if (sort === "name_asc") {
    sorted.sort((a, b) => String(a.file_name).localeCompare(String(b.file_name)));
  } else if (sort === "name_desc") {
    sorted.sort((a, b) => String(b.file_name).localeCompare(String(a.file_name)));
  } else if (sort === "largest") {
    sorted.sort((a, b) => rowCount(b) - rowCount(a));
  }

  return sorted;
}
