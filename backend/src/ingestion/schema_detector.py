"""Detects column types and dataset schema from a loaded CSV."""

import logging
from typing import Any, Dict, List

import pandas as pd
from dateutil.parser import ParserError, parse as parse_date

logger = logging.getLogger(__name__)

# Sampling parameters used to heuristically detect datetime-like text columns.
DATETIME_SAMPLE_SIZE = 20
DATETIME_MATCH_THRESHOLD = 0.8


def _looks_like_datetime(series: pd.Series) -> bool:
    """Heuristically determine whether a text column holds datetime values."""
    sample = series.dropna().astype(str).head(DATETIME_SAMPLE_SIZE)
    if sample.empty:
        return False

    matches = 0
    for value in sample:
        try:
            parse_date(value)
            matches += 1
        except (ParserError, ValueError, OverflowError, TypeError):
            continue

    return (matches / len(sample)) >= DATETIME_MATCH_THRESHOLD


def _classify_columns(df: pd.DataFrame) -> Dict[str, List[str]]:
    """Classify each column into numeric, categorical, or datetime groupings."""
    numeric_columns: List[str] = []
    categorical_columns: List[str] = []
    datetime_columns: List[str] = []

    for column in df.columns:
        series = df[column]

        if pd.api.types.is_datetime64_any_dtype(series):
            datetime_columns.append(column)
        elif pd.api.types.is_numeric_dtype(series):
            numeric_columns.append(column)
        elif pd.api.types.is_string_dtype(series) and _looks_like_datetime(series):
            datetime_columns.append(column)
        else:
            categorical_columns.append(column)

    return {
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "datetime_columns": datetime_columns,
    }


def detect_schema(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Inspect a DataFrame and return its schema metadata.

    Returns a dict containing: column names, dtypes, numeric/categorical/
    datetime column groupings, total rows, total columns, and per-column
    missing value counts.
    """
    column_groups = _classify_columns(df)

    schema = {
        "columns": list(df.columns),
        "dtypes": {column: str(dtype) for column, dtype in df.dtypes.items()},
        "numeric_columns": column_groups["numeric_columns"],
        "categorical_columns": column_groups["categorical_columns"],
        "datetime_columns": column_groups["datetime_columns"],
        "total_rows": int(df.shape[0]),
        "total_columns": int(df.shape[1]),
        "missing_values": {column: int(count) for column, count in df.isna().sum().items()},
    }

    logger.info(
        "Detected schema: %d rows, %d columns (%d numeric, %d categorical, %d datetime)",
        schema["total_rows"],
        schema["total_columns"],
        len(schema["numeric_columns"]),
        len(schema["categorical_columns"]),
        len(schema["datetime_columns"]),
    )

    return schema
