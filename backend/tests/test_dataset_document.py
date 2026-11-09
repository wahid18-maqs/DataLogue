"""Checks for the dataset document that is sent to the LLM."""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import pandas as pd  # noqa: E402

from src.presentation.dataset_document import (  # noqa: E402
    MAX_DOCUMENT_CHARS,
    build_dataset_document,
    document_to_json,
    document_to_text,
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


def sample_frame():
    return pd.DataFrame({
        "order_id": [f"ORD-{i:03d}" for i in range(1, 26)],
        "order_date": pd.date_range("2026-01-01", periods=25, freq="D"),
        "region": ["North", "South", "East", "West"] * 6 + ["North"],
        "category": ["Tools", "Tools", "Parts", "Parts", "Consumables"] * 5,
        "quantity": list(range(1, 26)),
        "revenue": [round(10.5 * i, 2) for i in range(1, 26)],
        "status": ["Delivered"] * 18 + ["Pending"] * 4 + ["Cancelled"] * 3,
    })


def main():
    df = sample_frame()
    doc = build_dataset_document(df)

    print("\n[1] The document describes the dataset")
    check("Reports the row count", doc["dataset"]["row_count"] == 25)
    check("Reports the column count", doc["dataset"]["column_count"] == 7)
    check("Lists every column", len(doc["dataset"]["columns"]) == 7)
    check("Profiles every column", len(doc["column_profiles"]) == 7)
    check("Includes a sample of the rows", len(doc["sample_rows"]) > 0)
    check("The sample does not exceed the row count",
          len(doc["sample_rows"]) <= doc["dataset"]["row_count"])

    print("\n[2] The sample holds real values")
    first = doc["sample_rows"][0]
    check("A sample row has every column", len(first) == 7)
    check("A sample row holds the real order id", first["order_id"] == "ORD-001")
    check("A sample row holds the real revenue", first["revenue"] == 10.5)
    check("The document is JSON-serialisable",
          isinstance(json.loads(document_to_json(doc)), dict))

    print("\n[3] Numeric columns are profiled")
    revenue = doc["column_profiles"]["revenue"]
    check("Reports the minimum", revenue["min"] == 10.5)
    check("Reports the maximum", revenue["max"] == 262.5)
    check("Reports the sum", revenue["sum"] == round(sum(10.5 * i for i in range(1, 26)), 4))
    check("Reports the median", revenue["median"] == 136.5)

    print("\n[4] Categorical columns are profiled")
    status = doc["column_profiles"]["status"]
    check("Reports the distinct count", status["distinct"] == 3)
    check("Reports the most common value first",
          status["most_common"][0]["value"] == "Delivered")
    check("Reports the most common count", status["most_common"][0]["count"] == 18)

    print("\n[5] Datetime columns are profiled")
    dates = doc["column_profiles"]["order_date"]
    check("Reports the first date", dates["min"].startswith("2026-01-01"))
    check("Reports the last date", dates["max"].startswith("2026-01-25"))

    print("\n[6] Missing values are reported")
    with_gaps = df.copy()
    with_gaps.loc[0:2, "revenue"] = None
    doc = build_dataset_document(with_gaps)
    check("Counts the missing values", doc["column_profiles"]["revenue"]["missing"] == 3)
    check("Counts the non-null values", doc["column_profiles"]["revenue"]["non_null"] == 22)

    print("\n[7] The document stays within its size cap")
    big = pd.DataFrame({
        f"col_{i}": [f"value-{i}-{j}" for j in range(20000)] for i in range(12)
    })
    doc = build_dataset_document(big)
    encoded = document_to_json(doc)
    check("The document fits the cap", len(encoded) <= MAX_DOCUMENT_CHARS, str(len(encoded)))
    check("The sample was trimmed", len(doc["sample_rows"]) < 20000,
          str(len(doc["sample_rows"])))
    check("Every column is still profiled", len(doc["column_profiles"]) == 12)

    print("\n[7b] An oversized sample is trimmed and says so")
    doc = build_dataset_document(big, sample_rows=20000)
    check("The document fits the cap", len(document_to_json(doc)) <= MAX_DOCUMENT_CHARS)
    check("The sample was trimmed", len(doc["sample_rows"]) < 20000,
          str(len(doc["sample_rows"])))
    check("The note explains the trim", "trimmed" in doc["sample_note"].lower())
    check("The note still states the row count",
          "20000" in doc["sample_note"])

    print("\n[8] The text rendering")
    doc = build_dataset_document(df)
    text = document_to_text(doc)
    check("Names the column profile section", "COLUMN PROFILES" in text)
    check("Names the sample rows section", "SAMPLE ROWS" in text)
    check("Includes a real value", "ORD-001" in text)
    check("Lists the columns", "revenue" in text)

    print("\n[9] Key roles are included when known")
    from src.presentation.dashboard_planner import detect_roles
    from src.ingestion.schema_detector import detect_schema
    schema = detect_schema(df)
    roles = detect_roles(df, schema)
    doc = build_dataset_document(df, schema=schema, key_roles=roles)
    check("Includes the key roles", "key_roles" in doc)
    check("The roles map is a dict", isinstance(doc["key_roles"], dict))

    print("\n[10] An empty frame does not break the document")
    empty = build_dataset_document(df.head(0))
    check("Handles an empty frame", empty["dataset"]["row_count"] == 0)
    check("Still profiles the columns", len(empty["column_profiles"]) == 7)
    check("Has no sample rows", empty["sample_rows"] == [])

    print(f"\n{'=' * 60}")
    print(f"PASSED: {len(PASSED)}   FAILED: {len(FAILED)}")
    if FAILED:
        print("\nFailures:")
        for name in FAILED:
            print(f"  - {name}")
        return 1
    print("All dataset document checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
