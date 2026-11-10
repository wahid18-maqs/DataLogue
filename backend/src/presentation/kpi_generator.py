"""Generates key performance indicators (KPIs) from a dataset."""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from src.ingestion.schema_detector import detect_schema

logger = logging.getLogger(__name__)

# Cap on how many top categorical values are reported per column.
MAX_TOP_VALUES = 10
TOTAL_LABELS = {"total", "all", "grand total", "subtotal"}


def _business_values(series: pd.Series) -> pd.Series:
    """Exclude report-total rows from category and status KPIs."""
    values = series.dropna()
    return values[~values.astype(str).str.strip().str.lower().isin(TOTAL_LABELS)]


def _plural_label(name: str) -> str:
    """Create a readable plural label without changing the source column."""
    if name.lower().endswith("y") and len(name) > 1 and name[-2].lower() not in "aeiou":
        return f"{name[:-1]}ies"
    return name if name.lower().endswith("s") else f"{name}s"


def _numeric_column_stats(df: pd.DataFrame, columns: List[str]) -> Dict[str, Dict[str, Any]]:
    """Compute sum/mean/min/max/unique-count statistics for each numeric column."""
    stats: Dict[str, Dict[str, Any]] = {}
    for column in columns:
        series = df[column].dropna()
        if series.empty:
            stats[column] = {
                "sum": None,
                "mean": None,
                "min": None,
                "max": None,
                "unique_count": 0,
            }
            continue

        stats[column] = {
            "sum": float(series.sum()),
            "mean": float(series.mean()),
            "min": float(series.min()),
            "max": float(series.max()),
            "unique_count": int(series.nunique()),
        }
    return stats


def _categorical_column_stats(df: pd.DataFrame, columns: List[str]) -> Dict[str, Dict[str, Any]]:
    """Compute unique counts and top value frequencies for each categorical column."""
    stats: Dict[str, Dict[str, Any]] = {}
    for column in columns:
        series = df[column].dropna()
        top_values = series.value_counts().head(MAX_TOP_VALUES)
        stats[column] = {
            "unique_count": int(series.nunique()),
            "top_values": {str(value): int(count) for value, count in top_values.items()},
        }
    return stats


def generate_kpis(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate a structured set of KPIs for the given DataFrame.

    Returns dataset-level KPIs (row/column counts, missing values) plus
    per-column statistics, grouped by the dynamically detected column type.
    """
    schema = detect_schema(df)

    kpis: Dict[str, Any] = {
        "total_rows": schema["total_rows"],
        "total_columns": schema["total_columns"],
        "total_missing_values": int(sum(schema["missing_values"].values())),
        "missing_values_by_column": schema["missing_values"],
        "numeric_statistics": _numeric_column_stats(df, schema["numeric_columns"]),
        "categorical_statistics": _categorical_column_stats(df, schema["categorical_columns"]),
    }

    logger.info(
        "Generated KPIs for %d rows: %d numeric column(s), %d categorical column(s).",
        kpis["total_rows"],
        len(kpis["numeric_statistics"]),
        len(kpis["categorical_statistics"]),
    )

    return kpis


def generate_ecommerce_kpis(
    df: pd.DataFrame,
    schema: Optional[Dict[str, Any]] = None,
    key_roles: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generate top-level ecommerce KPIs and quick stats from schema and column roles.

    Returns a dict containing:
      - "quick_stats": list of concise stat widgets with change indicators
      - "kpis": list of detailed KPI cards with labels, formatted values, and types
    """
    if schema is None:
        schema = detect_schema(df)

    total_rows = schema.get("total_rows", len(df))
    numeric_columns = schema.get("numeric_columns", [])
    categorical_columns = schema.get("categorical_columns", [])

    key_roles = key_roles or {}
    rev_col = key_roles.get("revenue")
    order_col = key_roles.get("order_metric")
    order_agg = key_roles.get("order_agg_mode", "count")
    cust_col = key_roles.get("customer")
    cat_col = key_roles.get("category")
    status_col = key_roles.get("status")

    kpis: List[Dict[str, Any]] = []
    quick_stats: List[Dict[str, Any]] = []

    # 1. Financial / Revenue Metric
    if rev_col and rev_col in df.columns:
        s_rev = df[rev_col].dropna().astype(float)
        tot_rev = float(s_rev.sum())
        avg_rev = float(s_rev.mean()) if not s_rev.empty else 0.0

        kpis.append({
            "key": "total_sales",
            "label": f"Total {rev_col}",
            "value": round(tot_rev, 2),
            "formatted": f"{tot_rev:,.2f}",
            "column": rev_col,
            "type": "currency_or_number"
        })
        kpis.append({
            "key": "avg_order_value",
            "label": f"Avg {rev_col}",
            "value": round(avg_rev, 2),
            "formatted": f"{avg_rev:,.2f}",
            "column": rev_col,
            "type": "currency_or_number"
        })
        quick_stats.append({
            "label": f"Total {rev_col}",
            "value": f"{tot_rev:,.2f}",
            "numeric_value": round(tot_rev, 2),
        })
        quick_stats.append({
            "label": f"Avg {rev_col}",
            "value": f"{avg_rev:,.2f}",
            "numeric_value": round(avg_rev, 2),
        })

    # 2. Orders / Activity Volume
    if order_col and order_agg == "sum" and order_col in df.columns:
        s_order = df[order_col].dropna().astype(float)
        tot_orders = float(s_order.sum())
        val_display = f"{tot_orders:,.0f}" if tot_orders.is_integer() else f"{tot_orders:,.2f}"
        kpis.append({
            "key": "total_volume",
            "label": f"Total {order_col}",
            "value": int(tot_orders) if tot_orders.is_integer() else round(tot_orders, 2),
            "formatted": val_display,
            "column": order_col,
            "type": "count"
        })
        quick_stats.append({
            "label": f"Total {order_col}",
            "value": val_display,
            "numeric_value": round(tot_orders, 2),
        })
    else:
        kpis.append({
            "key": "total_orders",
            "label": "Total Orders",
            "value": total_rows,
            "formatted": f"{total_rows:,}",
            "column": None,
            "type": "count"
        })
        quick_stats.append({
            "label": "Total Orders",
            "value": f"{total_rows:,}",
            "numeric_value": total_rows,
        })

    # 3. Customers
    if cust_col and cust_col in df.columns:
        n_cust = int(_business_values(df[cust_col]).nunique())
        kpis.append({
            "key": "unique_customers",
            "label": f"Unique {_plural_label(cust_col)}",
            "value": n_cust,
            "formatted": f"{n_cust:,}",
            "column": cust_col,
            "type": "count"
        })
        quick_stats.append({
            "label": f"Customers",
            "value": f"{n_cust:,}",
            "numeric_value": n_cust,
        })

    # 4. Categories or Statuses
    if cat_col and cat_col in df.columns:
        n_cats = int(_business_values(df[cat_col]).nunique())
        kpis.append({
            "key": "active_categories",
            "label": f"Active {_plural_label(cat_col)}",
            "value": n_cats,
            "formatted": f"{n_cats:,}",
            "column": cat_col,
            "type": "count"
        })

    if status_col and status_col in df.columns and len(kpis) < 5:
        top_status = _business_values(df[status_col]).value_counts()
        if not top_status.empty:
            lead_status = str(top_status.index[0])
            pct = round((top_status.iloc[0] / max(total_rows, 1)) * 100, 1)
            kpis.append({
                "key": "primary_status",
                "label": f"Top {status_col} ({lead_status})",
                "value": pct,
                "formatted": f"{pct}%",
                "column": status_col,
                "type": "percentage"
            })

    return {
        "kpis": kpis[:5],
        "quick_stats": quick_stats[:4],
    }
