"""Checks for the workbook layer: the store, the cache, the pipeline and the"""

import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402

from src.workbook.workbook_cache import WorkbookCache  # noqa: E402
from src.ingestion.workbook_processor import (  # noqa: E402
    SheetError,
    _clean_frame,
    build_auto_summary,
    compute_findings,
    infer_schema,
    looks_tabular,
    process_workbook,
    validate_file,
)
from src.workbook.workbook_service import WorkbookNotFound, WorkbookService  # noqa: E402
from src.workbook.workbook_store import (  # noqa: E402
    STATUS_NEEDS_ATTENTION,
    STATUS_PARSED,
    STATUS_STALE,
    WorkbookStore,
)

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name} {detail}")


SALES_CSV = """Date,Category,Region,Sales,Quantity,Customer
2025-01-05,Furniture,North,1000,2,Globex
2025-01-18,Office,South,250,1,Initech
2025-02-03,Technology,East,1540,5,Initech
2025-02-21,Office,West,720,3,Umbrella
2025-03-07,Technology,North,1980,6,Acme
2025-03-25,Furniture,South,1430,2,Globex
"""


def write_csv(directory: Path, name: str = "sales.csv", content: str = SALES_CSV) -> Path:
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def write_excel(directory: Path, name: str = "book.xlsx") -> Path:
    path = directory / name
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_excel(
            writer, sheet_name="Data", index=False
        )
        pd.DataFrame({"note": ["just a cover sheet"]}).to_excel(
            writer, sheet_name="Cover", index=False
        )
    return path


def main():
    print("\n[1] The metadata store")
    with tempfile.TemporaryDirectory() as tmp:
        store = WorkbookStore(Path(tmp) / "workbooks.db")
        record = store.create_workbook(
            file_name="sales.csv", file_type="csv", storage_path="/tmp/sales.csv"
        )
        check("A workbook is created", bool(record["id"]), str(record))
        check("It starts as uploading", record["status"] == "uploading", record["status"])
        check("It has no sheets yet", record["sheets"] == [], str(record["sheets"]))

        found = store.get_workbook(record["id"])
        check("The workbook can be read back", found is not None)
        check("The name is kept", found["file_name"] == "sales.csv", str(found))

        store.update_workbook(
            record["id"],
            status=STATUS_PARSED,
            sheets=[{"id": "sheet_1", "name": "Data"}],
            active_sheet_id="sheet_1",
        )
        found = store.get_workbook(record["id"])
        check("The status is updated", found["status"] == STATUS_PARSED, found["status"])
        check("The sheets are stored as JSON", len(found["sheets"]) == 1, str(found["sheets"]))
        check("The active sheet is set", found["active_sheet_id"] == "sheet_1",
              str(found["active_sheet_id"]))

        listing = store.list_workbooks()
        check("The workbook is listed", len(listing) == 1, str(len(listing)))

        check("A missing workbook is None", store.get_workbook("nope") is None)
        check("It can be deleted", store.delete_workbook(record["id"]))
        check("It is gone", store.get_workbook(record["id"]) is None)
        check("Deleting it again reports nothing removed",
              store.delete_workbook(record["id"]) is False)
        store.close()

    print("\n[2] The store survives a restart")
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "workbooks.db"
        store = WorkbookStore(db)
        record = store.create_workbook(
            file_name="a.csv", file_type="csv", storage_path="/tmp/a.csv"
        )
        store.update_workbook(record["id"], status=STATUS_PARSED, active_sheet_id="sheet_1")
        store.close()

        # A new store over the same file, as a restart would do.
        store = WorkbookStore(db)
        found = store.get_workbook(record["id"])
        check("The record is still there", found is not None)
        check("Its status is still parsed", found["status"] == STATUS_PARSED, found["status"])
        stale = store.mark_all_stale()
        check("A restart marks the workbooks stale", stale == 1, str(stale))
        check("The status is now stale",
              store.get_workbook(record["id"])["status"] == STATUS_STALE)
        store.close()

    print("\n[3] The schema is inferred")
    frame = _clean_frame(pd.read_csv(StringIO(SALES_CSV)))
    schema = infer_schema(frame)
    by_name = {entry["name"]: entry for entry in schema}
    check("Every column is described", len(schema) == 6, str(len(schema)))
    check("A date column is a date", by_name["Date"]["type"] == "date", str(by_name["Date"]))
    check("A numeric column is a number", by_name["Sales"]["type"] == "number", str(by_name["Sales"]))
    check("A categorical column is categorical",
          by_name["Category"]["type"] == "categorical", str(by_name["Category"]))
    check("A categorical column lists its values",
          "Furniture" in by_name["Category"].get("values", []), str(by_name["Category"]))
    check("A numeric column has a range",
          by_name["Sales"]["min"] == 250 and by_name["Sales"]["max"] == 1980,
          str(by_name["Sales"]))

    print("\n[4] The findings are computed")
    findings = compute_findings(frame, schema)
    check("The row count is right", findings["row_count"] == 6, str(findings["row_count"]))
    check("The total is computed", findings["totals"]["Sales"] == 6920.0,
          str(findings["totals"]))
    check("The average is computed", findings["averages"]["Sales"] == 1153.3333,
          str(findings["averages"]))
    check("The unique count is computed", findings["unique_counts"]["Sales"] == 6,
          str(findings["unique_counts"]))
    check("The category breakdown is computed",
          findings["category_breakdowns"]["Category"]["Furniture"] == 2,
          str(findings["category_breakdowns"]))
    check("The concentration ratio is computed",
          findings["concentration"]["Category"] == 0.3333,
          str(findings["concentration"]))
    check("A date range is recorded", "from" in findings["trends"].get("Date", {}),
          str(findings["trends"]))

    print("\n[5] The auto-summary is one line")
    summary = build_auto_summary("Data", schema, findings)
    check("It is a single line", "\n" not in summary, summary)
    check("It names the rows", "6 rows" in summary, summary)
    check("It names the columns", "Sales" in summary, summary)

    print("\n[6] The pipeline reads a CSV")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_csv(Path(tmp))
        result = process_workbook(str(path))
        check("The workbook is parsed", result["status"] == "parsed", str(result["status"]))
        check("It has one sheet", len(result["sheets"]) == 1, str(len(result["sheets"])))
        check("The active sheet is the first", result["active_sheet_id"] == "sheet_1",
              str(result["active_sheet_id"]))
        sheet = result["sheets"][0]
        check("The sheet has a schema", len(sheet["schema"]) == 6, str(len(sheet["schema"])))
        check("The sheet has sample rows", len(sheet["sample_rows"]) == 6,
              str(len(sheet["sample_rows"])))
        check("The sheet has findings", sheet["findings"]["row_count"] == 6,
              str(sheet["findings"]))
        check("The sheet has an auto-summary", bool(sheet["auto_summary"]))
        check("The cleaned frame is returned", "sheet_1" in result["frames"],
              str(list(result["frames"])))

    print("\n[7] The pipeline reads an Excel file with several sheets")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_excel(Path(tmp))
        result = process_workbook(str(path))
        check("Both sheets are found", len(result["sheets"]) == 2, str(len(result["sheets"])))
        names = [sheet["name"] for sheet in result["sheets"]]
        check("The cover sheet is skipped", "Cover" in names, str(names))
        cover = next(s for s in result["sheets"] if s["name"] == "Cover")
        check("The cover sheet is marked as skipped", cover["status"] == "skipped",
              cover["status"])
        check("The cover sheet has a reason", bool(cover["error_reason"]))
        data = next(s for s in result["sheets"] if s["name"] == "Data")
        check("The data sheet is parsed", data["status"] == "parsed", data["status"])
        check("The data sheet has its rows", data["row_count"] == 3, str(data["row_count"]))

    print("\n[8] A file that cannot be used needs attention")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_csv(Path(tmp), "empty.csv", "")
        result = process_workbook(str(path))
        check("An empty file needs attention", result["status"] == "needs_attention",
              str(result["status"]))
        check("It has a reason", bool(result["error_reason"]), str(result["error_reason"]))

    print("\n[9] The validation refuses the wrong file")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "notes.txt"
        path.write_text("hello", encoding="utf-8")
        result = process_workbook(str(path))
        check("An unsupported extension needs attention",
              result["status"] == "needs_attention", str(result["status"]))
        check("It says why", "not supported" in result["error_reason"],
              str(result["error_reason"]))

        missing = Path(tmp) / "nope.csv"
        result = process_workbook(str(missing))
        check("A missing file needs attention",
              result["status"] == "needs_attention", str(result["status"]))
        check("It says why", "missing" in result["error_reason"],
              str(result["error_reason"]))

        try:
            validate_file(str(path))
            check("The validation itself raises", False, "it was allowed")
        except SheetError:
            check("The validation itself raises", True)

    print("\n[10] The cache holds the parsed frames")
    cache = WorkbookCache(max_workbooks=2)
    frame_a = pd.DataFrame({"a": [1]})
    frame_b = pd.DataFrame({"b": [2]})
    cache.put("wb1", "sheet_1", frame_a)
    check("The frame is cached", cache.get("wb1", "sheet_1") is not None)
    check("A missing sheet is None", cache.get("wb1", "sheet_9") is None)
    check("A missing workbook is None", cache.get("nope", "sheet_1") is None)

    cache.put("wb2", "sheet_1", frame_b)
    cache.put("wb3", "sheet_1", frame_b)
    check("The oldest workbook is evicted", cache.get("wb1", "sheet_1") is None)
    check("The newest is kept", cache.get("wb3", "sheet_1") is not None)

    cache.invalidate("wb3")
    check("Invalidation drops the frames", cache.get("wb3", "sheet_1") is None)

    print("\n[11] The service runs the whole lifecycle")
    with tempfile.TemporaryDirectory() as tmp:
        store = WorkbookStore(Path(tmp) / "workbooks.db")
        cache = WorkbookCache()
        service = WorkbookService(store, cache)

        path = write_csv(Path(tmp))
        record = service.create(file_name="sales.csv", storage_path=str(path))
        check("The workbook is created", bool(record["id"]), str(record))
        check("It ends up parsed", record["status"] == STATUS_PARSED, record["status"])
        check("It has a sheet", len(record["sheets"]) == 1, str(len(record["sheets"])))
        check("The active sheet is set", record["active_sheet_id"] == "sheet_1",
              str(record["active_sheet_id"]))

        listing = service.list()
        check("It is listed", len(listing) == 1, str(len(listing)))
        check("The list entry has the auto-summary",
              bool(listing[0]["sheets"][0]["auto_summary"]), str(listing[0]))
        check("The list entry does not carry the whole schema",
              "schema" not in listing[0]["sheets"][0], str(listing[0]["sheets"][0].keys()))

        detail = service.get(record["id"])
        check("The detail carries the schema",
              len(detail["sheets"][0]["schema"]) == 6, str(detail["sheets"][0].keys()))
        check("The detail carries the findings",
              detail["sheets"][0]["findings"]["row_count"] == 6,
              str(detail["sheets"][0]["findings"]))

        frame = service.get_frame(record["id"])
        check("The frame comes from the cache", frame.shape == (6, 6), str(frame.shape))

        service.set_active_sheet(record["id"], "sheet_1")
        check("The active sheet can be set", True)

        try:
            service.set_active_sheet(record["id"], "sheet_9")
            check("An unknown sheet is refused", False, "it was allowed")
        except ValueError:
            check("An unknown sheet is refused", True)

        try:
            service.get("nope")
            check("A missing workbook raises", False, "expected a raise")
        except WorkbookNotFound:
            check("A missing workbook raises", True)

        print("\n[12] Replacing a file invalidates the cache")
        # The cache is dropped, so nothing can be computed against the old file.
        new_path = write_csv(
            Path(tmp), "sales2.csv",
            "Date,Category,Sales\n2025-01-01,A,10\n2025-01-02,B,20\n",
        )
        replaced = service.replace(
            record["id"], file_name="sales2.csv", storage_path=str(new_path)
        )
        check("The workbook is re-parsed", replaced["status"] == STATUS_PARSED,
              replaced["status"])
        check("The new shape is recorded",
              replaced["sheets"][0]["row_count"] == 2,
              str(replaced["sheets"][0]["row_count"]))
        check("The old findings are gone",
              "Sales" not in replaced["sheets"][0]["findings"].get("totals", {})
              or replaced["sheets"][0]["findings"]["totals"]["Sales"] == 30.0,
              str(replaced["sheets"][0]["findings"]))
        check("The old file is still on disk (it is not deleted on replace)",
              path.exists(), str(path))

        print("\n[13] A deleted workbook takes its file with it")
        service.delete(record["id"])
        check("The record is gone", service.list() == [], str(service.list()))
        check("The raw file is gone", not new_path.exists(), str(new_path.exists()))

        store.close()

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All workbook checks passed.")
    return 0


if __name__ == "__main__":
    from io import StringIO

    sys.exit(main())
