"""Focused checks for header detection and sheet classification."""

import tempfile
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion.workbook_processor import (
    classify_sheet,
    detect_header_row,
    process_workbook,
)


def main() -> None:
    header = detect_header_row(pd.DataFrame([
        ["Report title", None],
        ["Date", "Sales"],
        ["2026-01-01", 10],
    ]))
    assert header == 1, header
    assert classify_sheet(pd.DataFrame({"a": [1, 2], "b": [3, 4]}))["class"] == "tabular"
    assert classify_sheet(pd.DataFrame())["class"] == "not_data"
    assert classify_sheet(
        pd.DataFrame({"Product Name": ["A"], "Base Price": [10]}),
        "Product Calculator",
    )["class"] == "not_data"

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "offset.csv"
        path.write_text(
            "\n\nReport title\nDate,Sales\n2026-01-01,10\n2026-01-02,20\n",
            encoding="utf-8",
        )
        result = process_workbook(str(path))
        assert result["status"] == "parsed", result
        assert result["sheets"][0]["schema"][0]["name"] == "Date"

    complex_path = Path(__file__).with_name("test-complex.xlsx")
    if complex_path.exists():
        complex_result = process_workbook(str(complex_path))
        by_name = {sheet["name"]: sheet for sheet in complex_result["sheets"]}
        assert complex_result["status"] == "partially_parsed"
        assert by_name["Executive Dashboard"]["sheet_class"] == "dashboard"
        assert by_name["Financials"]["sheet_class"] == "wide_financial"
        assert by_name["Product Calculator"]["status"] == "skipped"

    print("All ingestion feature checks passed.")


if __name__ == "__main__":
    main()
