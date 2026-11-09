"""Runs a pandas query plan written by the LLM, under a fixed allowlist."""

import logging
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

logger = logging.getLogger(__name__)

# The longest plan the model may produce, in characters.
MAX_PLAN_CHARS = 4000

# How many rows of a table are handed back to the client.
MAX_RESULT_ROWS = 50

# How many grouping levels a plan may use.
MAX_GROUP_LEVELS = 3

# The aggregation functions a plan may ask for.
AGGREGATIONS = {
    "sum": lambda series: series.sum(),
    "mean": lambda series: series.mean(),
    "median": lambda series: series.median(),
    "min": lambda series: series.min(),
    "max": lambda series: series.max(),
    "count": lambda series: series.count(),
    "nunique": lambda series: series.nunique(),
    "std": lambda series: series.std(),
    "var": lambda series: series.var(),
    "size": lambda series: series.size,
}

# How a column may be filtered.
FILTER_OPERATORS = {
    "eq": lambda series, value: series == value,
    "ne": lambda series, value: series != value,
    "gt": lambda series, value: series > value,
    "gte": lambda series, value: series >= value,
    "lt": lambda series, value: series < value,
    "lte": lambda series, value: series <= value,
    "contains": lambda series, value: series.astype(str).str.contains(str(value), na=False),
    "in": lambda series, value: series.isin(value if isinstance(value, list) else [value]),
    "notnull": lambda series, value: series.notna(),
    "isnull": lambda series, value: series.isna(),
}

# How the result may be ordered.
ORDERINGS = {
    "asc": lambda series: series.sort_values(ascending=True),
    "desc": lambda series: series.sort_values(ascending=False),
}

# How the result may be trimmed.
LIMITS = {
    "head": lambda frame, count: frame.head(count),
    "tail": lambda frame, count: frame.tail(count),
}


class SandboxError(ValueError):
    """Raised when a query plan cannot be run."""


def _require_column(df: pd.DataFrame, name: Any) -> str:
    """Check that a name is a real column of the dataframe."""
    if not isinstance(name, str) or name not in df.columns:
        raise SandboxError(f"'{name}' is not a column of this dataset.")
    return name


def _apply_filters(df: pd.DataFrame, filters: Any) -> pd.DataFrame:
    """Apply the plan's filters to the dataframe."""
    if filters is None:
        return df
    if not isinstance(filters, list):
        raise SandboxError("The filters must be a list.")
    if len(filters) > 10:
        raise SandboxError("Too many filters were requested.")

    result = df
    for spec in filters:
        if not isinstance(spec, dict):
            raise SandboxError("A filter must be an object.")

        column = _require_column(result, spec.get("column"))
        operator = spec.get("op")
        if operator not in FILTER_OPERATORS:
            raise SandboxError(f"'{operator}' is not a filter this can apply.")

        value = spec.get("value")
        if operator in ("gt", "gte", "lt", "lte"):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise SandboxError(
                    f"The '{operator}' filter needs a number, not {type(value).__name__}."
                )
        if operator == "in":
            if not isinstance(value, list):
                raise SandboxError("The 'in' filter needs a list of values.")

        result = result.loc[FILTER_OPERATORS[operator](result[column], value)]

    return result


def _apply_grouping(
    df: pd.DataFrame, group_by: Any, metrics: Any
) -> pd.DataFrame:
    """Group the dataframe and compute the requested metrics."""
    if not isinstance(metrics, list) or not metrics:
        raise SandboxError("The plan must ask for at least one metric.")

    group_columns: List[str] = []
    if group_by is not None:
        if not isinstance(group_by, list):
            group_by = [group_by]
        if len(group_by) > MAX_GROUP_LEVELS:
            raise SandboxError("Too many grouping levels were requested.")
        for column in group_by:
            group_columns.append(_require_column(df, column))

    if not group_columns:
        # No grouping: one row of totals over the whole (filtered) frame.
        computed: Dict[str, Any] = {}
        for metric in metrics:
            computed.update(_compute_metric(df, metric))
        return pd.DataFrame([computed])

    grouped = df.groupby(group_columns, dropna=False)
    result = None
    for metric in metrics:
        piece = _compute_grouped_metric(grouped, metric)
        result = piece if result is None else result.join(piece, how="outer")

    return result.reset_index()


def _compute_metric(frame: pd.DataFrame, metric: Any) -> Dict[str, Any]:
    """Compute one metric over a whole frame."""
    if not isinstance(metric, dict):
        raise SandboxError("A metric must be an object.")

    aggregation = metric.get("agg")
    if aggregation not in AGGREGATIONS:
        raise SandboxError(f"'{aggregation}' is not an aggregation this can compute.")

    column = metric.get("column")
    alias = metric.get("as") or f"{aggregation}_{column or 'value'}"

    if column is None:
        if aggregation != "count" and aggregation != "size":
            raise SandboxError(f"The '{aggregation}' aggregation needs a column.")
        # A count over the whole frame is a count of its rows.
        return {alias: int(len(frame))}

    series = frame[_require_column(frame, column)]
    return {alias: AGGREGATIONS[aggregation](series)}


def _compute_grouped_metric(grouped, metric: Any) -> pd.DataFrame:
    """Compute one metric per group."""
    if not isinstance(metric, dict):
        raise SandboxError("A metric must be an object.")

    aggregation = metric.get("agg")
    if aggregation not in AGGREGATIONS:
        raise SandboxError(f"'{aggregation}' is not an aggregation this can compute.")

    column = metric.get("column")
    alias = metric.get("as") or f"{aggregation}_{column or 'value'}"

    if column is None:
        if aggregation not in ("count", "size"):
            raise SandboxError(f"The '{aggregation}' aggregation needs a column.")
        return grouped.size().to_frame(name=alias)

    series = grouped[_require_column(grouped.obj, column)]
    return AGGREGATIONS[aggregation](series).to_frame(name=alias)


def _apply_order(df: pd.DataFrame, order: Any) -> pd.DataFrame:
    """Order the result."""
    if order is None:
        return df
    if not isinstance(order, dict):
        raise SandboxError("The order must be an object.")

    direction = order.get("by", "desc")
    if direction not in ORDERINGS:
        raise SandboxError(f"'{direction}' is not an ordering this can apply.")

    column = order.get("column")
    if column is None:
        # No column named: order by the first metric.
        if df.shape[1] == 0:
            return df
        column = str(df.columns[0])

    if column not in df.columns:
        raise SandboxError(f"'{column}' is not a column of the result.")

    # The ordering is applied by position, so the result keeps its columns.
    ordered = ORDERINGS[direction](df[column])
    return df.iloc[ordered.index]


def _apply_limit(df: pd.DataFrame, limit: Any) -> pd.DataFrame:
    """Trim the result."""
    if limit is None:
        return df
    if not isinstance(limit, dict):
        raise SandboxError("The limit must be an object.")

    mode = limit.get("mode", "head")
    if mode not in LIMITS:
        raise SandboxError(f"'{mode}' is not a limit this can apply.")

    count = limit.get("count", 10)
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 500:
        raise SandboxError("The limit count must be a whole number between 1 and 500.")

    return LIMITS[mode](df, count)


def _json_value(value: Any) -> Any:
    """Convert a pandas/numpy value into something JSON can hold."""
    if value is None:
        return None
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return round(value, 4)
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def _summarise(frame: pd.DataFrame) -> Dict[str, Any]:
    """Turn the computed table into a JSON-serialisable summary."""
    rows = [
        {str(k): _json_value(v) for k, v in row.items()}
        for row in frame.head(MAX_RESULT_ROWS).to_dict(orient="records")
    ]
    return {
        "kind": "table",
        "columns": [str(column) for column in frame.columns],
        "rows": rows,
        "row_count": int(len(frame)),
        "truncated": len(frame) > MAX_RESULT_ROWS,
    }


def run_plan(df: pd.DataFrame, plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run a query plan against the dataframe.

    Args:
        df: The dataframe to analyse.
        plan: The plan, as a dict with these optional keys:
          - "filters": a list of {"column", "op", "value"} objects
          - "group_by": a column name, or a list of them
          - "metrics": a list of {"column", "agg", "as"} objects
          - "order": {"column", "by"} — "asc" or "desc"
          - "limit": {"mode", "count"} — "head" or "tail"

    Returns:
        A dict with "kind" ("table"), the "columns" and the "rows".

    Raises:
        SandboxError: If the plan asks for something this cannot do.
    """
    if not isinstance(plan, dict):
        raise SandboxError("The plan must be an object.")

    filtered = _apply_filters(df, plan.get("filters"))

    if plan.get("group_by") is not None or plan.get("metrics"):
        result = _apply_grouping(filtered, plan.get("group_by"), plan.get("metrics"))
    else:
        # No metrics: the filtered rows themselves are the answer.
        result = filtered

    result = _apply_order(result, plan.get("order"))
    result = _apply_limit(result, plan.get("limit"))

    return _summarise(result)
