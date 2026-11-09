import json
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# How many sample rows to include. Enough for the model to see the shape of
# the data without the prompt growing large.
DEFAULT_SAMPLE_ROWS = 40

# How many distinct values to list for a categorical column before it is
# described only by its counts.
MAX_CATEGORY_VALUES = 12

# The largest document we will send, in characters. Beyond this the sample
# is trimmed rather than risking a provider payload error.
MAX_DOCUMENT_CHARS = 60_000


def _json_value(value: Any) -> Any:
    """Convert a pandas/numpy value into something JSON can hold."""
    if value is None:
        return None
    if isinstance(value, float):
        # JSON has no NaN/Infinity; None is the closest portable stand-in.
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return round(value, 4)
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _column_profile(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    """Describe one column: its type, completeness and value distribution."""
    series = df[column]
    profile: Dict[str, Any] = {
        "dtype": str(series.dtype),
        "non_null": int(series.notna().sum()),
        "missing": int(series.isna().sum()),
    }

    if pd.api.types.is_numeric_dtype(series):
        numbers = series.dropna().astype(float)
        if not numbers.empty:
            profile["min"] = _json_value(numbers.min())
            profile["max"] = _json_value(numbers.max())
            profile["mean"] = _json_value(numbers.mean())
            profile["median"] = _json_value(numbers.median())
            profile["sum"] = _json_value(numbers.sum())
            profile["std"] = _json_value(numbers.std())
    elif pd.api.types.is_datetime64_any_dtype(series):
        dates = series.dropna()
        if not dates.empty:
            profile["min"] = dates.min().isoformat()
            profile["max"] = dates.max().isoformat()
    else:
        counts = series.dropna().value_counts()
        if not counts.empty:
            profile["distinct"] = int(len(counts))
            profile["most_common"] = [
                {"value": _json_value(value), "count": int(count)}
                for value, count in counts.head(MAX_CATEGORY_VALUES).items()
            ]
            if len(counts) > MAX_CATEGORY_VALUES:
                profile["other_values_count"] = int(counts.iloc[MAX_CATEGORY_VALUES:].sum())

    return profile


def build_dataset_document(
    df: pd.DataFrame,
    schema: Optional[Dict[str, Any]] = None,
    key_roles: Optional[Dict[str, Any]] = None,
    sample_rows: int = DEFAULT_SAMPLE_ROWS,
) -> Dict[str, Any]:
    """
    Build a JSON description of the dataset for the LLM to read.

    Returns:
        {
          "dataset": { "row_count", "column_count", "columns" },
          "column_profiles": { column: profile },
          "key_roles": { role: column },
          "sample_rows": [ { column: value, ... }, ... ],
          "sample_note": "..."
        }
    """
    if schema is None:
        from src.ingestion.schema_detector import detect_schema
        schema = detect_schema(df)
    if key_roles is None:
        from src.presentation.dashboard_planner import detect_roles
        key_roles = detect_roles(df, schema)

    profiles: Dict[str, Any] = {}
    for column in df.columns:
        try:
            profiles[column] = _column_profile(df, column)
        except Exception:  # noqa: BLE001 - one odd column must not break the document
            logger.warning("Could not profile column %r", column, exc_info=True)
            profiles[column] = {"dtype": str(df[column].dtype), "error": "profile unavailable"}

    rows: List[Dict[str, Any]] = []
    for _, row in df.head(sample_rows).iterrows():
        rows.append({str(column): _json_value(row[column]) for column in df.columns})

    document = {
        "dataset": {
            "row_count": int(df.shape[0]),
            "column_count": int(df.shape[1]),
            "columns": [str(column) for column in df.columns],
        },
        "key_roles": {k: v for k, v in (key_roles or {}).items() if v},
        "column_profiles": profiles,
        "sample_rows": rows,
        "sample_note": (
            f"The first {len(rows)} of {df.shape[0]} rows. "
            "The column profiles above describe the entire dataset."
        ),
    }

    return _trim(document)


def _trim(document: Dict[str, Any]) -> Dict[str, Any]:
    """Drop sample rows if the document is too large to send comfortably."""
    # The size is measured on the rendered payload, because that is what is
    # actually sent to the provider.
    if len(document_to_json(document)) <= MAX_DOCUMENT_CHARS:
        return document

    rows = document.get("sample_rows", [])
    # Halve the sample until the document fits.
    while rows:
        rows = rows[: max(1, len(rows) // 2)]
        document["sample_rows"] = rows
        if len(document_to_json(document)) <= MAX_DOCUMENT_CHARS:
            break
        if len(rows) == 1:
            # The sample cannot shrink any further; the rest of the document
            # is what it is.
            break

    document["sample_note"] = (
        f"The first {len(rows)} of {document['dataset']['row_count']} rows "
        "(trimmed to fit the request). The column profiles above describe "
        "the entire dataset."
    )

    logger.info("Trimmed the dataset document to %d sample rows.", len(rows))
    return document


def document_to_json(document: Dict[str, Any], indent: Optional[int] = 2) -> str:
    """Render the document as the JSON text that is sent to the model."""
    return json.dumps(document, default=str, indent=indent)


def document_to_text(document: Dict[str, Any]) -> str:
    """
    Render the document as a plain-text table.

    Useful when a model handles a readable table better than JSON, and for
    eyeballing what the model actually receives.
    """
    columns = document.get("dataset", {}).get("columns", [])
    profiles = document.get("column_profiles", {})
    lines: List[str] = []

    lines.append(f"Dataset: {document.get('dataset', {}).get('row_count', '?')} rows "
                 f"x {document.get('dataset', {}).get('column_count', '?')} columns")
    lines.append("")

    lines.append("COLUMN PROFILES")
    for column in columns:
        profile = profiles.get(column, {})
        detail = ", ".join(
            f"{key}={value}"
            for key, value in profile.items()
            if key not in ("dtype", "most_common")
        )
        lines.append(f"- {column} ({profile.get('dtype', '?')}): {detail}")
        common = profile.get("most_common")
        if common:
            top = ", ".join(f"{item['value']} ({item['count']})" for item in common[:6])
            lines.append(f"    most common: {top}")
    lines.append("")

    lines.append("SAMPLE ROWS")
    header = " | ".join(str(column) for column in columns)
    lines.append(header)
    lines.append("-" * len(header))
    for row in document.get("sample_rows", []):
        lines.append(" | ".join(str(row.get(column, "")) for column in columns))

    return "\n".join(lines)
