"""Generates chart configurations/specs from a dataset."""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go

from src.ingestion.schema_detector import detect_schema

logger = logging.getLogger(__name__)

MAX_PIE_CATEGORIES = 8
MAX_BAR_CATEGORIES = 15
MAX_SCATTER_POINTS = 500
MAX_CHARTS = 12
RANDOM_SAMPLE_SEED = 42


def _histogram_chart(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    """Build a histogram chart config for a numeric column's distribution."""
    series = df[column].dropna()
    figure = go.Figure(data=[go.Histogram(x=series.tolist())])
    figure.update_layout(title=f"Distribution of {column}", xaxis_title=column, yaxis_title="Frequency")
    return {
        "chart_type": "histogram",
        "title": f"Distribution of {column}",
        "columns": [column],
        "figure": figure.to_dict(),
    }


def _bar_chart(df: pd.DataFrame, category_column: str, numeric_column: str) -> Dict[str, Any]:
    """Build a bar chart config aggregating a numeric column by category."""
    grouped = (
        df.groupby(category_column)[numeric_column]
        .sum()
        .sort_values(ascending=False)
        .head(MAX_BAR_CATEGORIES)
    )
    figure = go.Figure(
        data=[go.Bar(x=grouped.index.astype(str).tolist(), y=grouped.values.tolist())]
    )
    figure.update_layout(
        title=f"{numeric_column} by {category_column}",
        xaxis_title=category_column,
        yaxis_title=numeric_column,
    )
    return {
        "chart_type": "bar",
        "title": f"{numeric_column} by {category_column}",
        "columns": [category_column, numeric_column],
        "figure": figure.to_dict(),
    }


def _pie_chart(df: pd.DataFrame, category_column: str) -> Dict[str, Any]:
    """Build a pie chart config showing the share of each category."""
    counts = df[category_column].dropna().value_counts()
    figure = go.Figure(
        data=[go.Pie(labels=counts.index.astype(str).tolist(), values=counts.values.tolist())]
    )
    figure.update_layout(title=f"Share of {category_column}")
    return {
        "chart_type": "pie",
        "title": f"Share of {category_column}",
        "columns": [category_column],
        "figure": figure.to_dict(),
    }


def _line_chart(df: pd.DataFrame, datetime_column: str, numeric_column: str) -> Dict[str, Any]:
    """Build a line chart config showing a numeric column's trend over time."""
    subset = df[[datetime_column, numeric_column]].dropna().sort_values(by=datetime_column)
    figure = go.Figure(
        data=[
            go.Scatter(
                x=subset[datetime_column].astype(str).tolist(),
                y=subset[numeric_column].tolist(),
                mode="lines",
            )
        ]
    )
    figure.update_layout(
        title=f"{numeric_column} over {datetime_column}",
        xaxis_title=datetime_column,
        yaxis_title=numeric_column,
    )
    return {
        "chart_type": "line",
        "title": f"{numeric_column} over {datetime_column}",
        "columns": [datetime_column, numeric_column],
        "figure": figure.to_dict(),
    }


def _scatter_chart(df: pd.DataFrame, x_column: str, y_column: str) -> Dict[str, Any]:
    """Build a scatter plot config comparing two numeric columns."""
    subset = df[[x_column, y_column]].dropna()
    if len(subset) > MAX_SCATTER_POINTS:
        subset = subset.sample(MAX_SCATTER_POINTS, random_state=RANDOM_SAMPLE_SEED)

    figure = go.Figure(
        data=[go.Scatter(x=subset[x_column].tolist(), y=subset[y_column].tolist(), mode="markers")]
    )
    figure.update_layout(title=f"{y_column} vs {x_column}", xaxis_title=x_column, yaxis_title=y_column)
    return {
        "chart_type": "scatter",
        "title": f"{y_column} vs {x_column}",
        "columns": [x_column, y_column],
        "figure": figure.to_dict(),
    }


def generate_charts(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Analyze the DataFrame's schema and recommend an appropriate set of charts.

    Returns a list of chart configuration dicts, each containing a
    "chart_type", "title", the source "columns", and a JSON-serializable
    Plotly "figure" spec. No images are generated.
    """
    schema = detect_schema(df)
    numeric_columns = schema["numeric_columns"]
    categorical_columns = schema["categorical_columns"]
    datetime_columns = schema["datetime_columns"]

    charts: List[Dict[str, Any]] = []

    for column in numeric_columns:
        charts.append(_histogram_chart(df, column))

    if datetime_columns and numeric_columns:
        primary_datetime_column = datetime_columns[0]
        for numeric_column in numeric_columns:
            charts.append(_line_chart(df, primary_datetime_column, numeric_column))

    for category_column in categorical_columns:
        unique_count = df[category_column].nunique(dropna=True)
        if unique_count == 0 or unique_count > MAX_BAR_CATEGORIES:
            continue

        if numeric_columns:
            charts.append(_bar_chart(df, category_column, numeric_columns[0]))

        if unique_count <= MAX_PIE_CATEGORIES:
            charts.append(_pie_chart(df, category_column))

    if len(numeric_columns) >= 2:
        charts.append(_scatter_chart(df, numeric_columns[0], numeric_columns[1]))

    charts = charts[:MAX_CHARTS]

    logger.info("Generated %d chart recommendation(s).", len(charts))
    return charts


def _build_ecommerce_main_timeseries(
    df: pd.DataFrame,
    datetime_col: Optional[str],
    revenue_col: Optional[str],
    breakdown_col: Optional[str] = None
) -> Dict[str, Any]:
    """
    Build the main 'Total Sales' time-series chart data.
    - Aggregates by a sensible period (e.g. Month or Day).
    - Supports multiple series when a suitable categorical breakdown exists (e.g. region/category, max 4 series).
    - If no datetime column exists, falls back gracefully to a categorical aggregation.
    """
    if datetime_col and revenue_col:
        parsed_dates = pd.to_datetime(df[datetime_col], errors="coerce")
        valid_mask = parsed_dates.notna() & df[revenue_col].notna()

        # Decide whether to break down by a categorical column (2 to 5 unique values max)
        valid_breakdown = False
        if breakdown_col and breakdown_col in df.columns and breakdown_col != datetime_col:
            unique_breakdowns = df.loc[valid_mask, breakdown_col].dropna().unique()
            if 2 <= len(unique_breakdowns) <= 4:
                valid_breakdown = True

        sub_df = pd.DataFrame({
            "date": parsed_dates[valid_mask],
            "val": df.loc[valid_mask, revenue_col].astype(float)
        })

        if valid_breakdown:
            sub_df["group"] = df.loc[valid_mask, breakdown_col].astype(str)

        sub_df = sub_df.sort_values(by="date")

        if sub_df.empty:
            x_vals = []
            y_vals = []
            traces = [go.Scatter(x=[], y=[], mode="lines+markers", fill="tozeroy", name=revenue_col)]
        else:
            date_range = (sub_df["date"].max() - sub_df["date"].min()).days
            freq = "M" if date_range > 60 else "D"
            sub_df["period"] = sub_df["date"].dt.to_period(freq).astype(str)

            if valid_breakdown:
                traces = []
                all_periods = sorted(sub_df["period"].unique())
                top_groups = sub_df["group"].value_counts().head(4).index.tolist()

                for grp in top_groups:
                    grp_df = sub_df[sub_df["group"] == grp].groupby("period")["val"].sum()
                    y_series = [round(float(grp_df.get(p, 0.0)), 2) for p in all_periods]
                    traces.append(
                        go.Scatter(
                            x=all_periods,
                            y=y_series,
                            mode="lines+markers",
                            name=str(grp)
                        )
                    )
            else:
                grouped = sub_df.groupby("period")["val"].sum().reset_index()
                x_vals = grouped["period"].tolist()
                y_vals = grouped["val"].round(2).tolist()
                traces = [
                    go.Scatter(
                        x=x_vals,
                        y=y_vals,
                        mode="lines+markers",
                        fill="tozeroy",
                        name=revenue_col
                    )
                ]

        title = f"Total {revenue_col} over Time" + (f" by {breakdown_col}" if valid_breakdown else "")
        figure = go.Figure(data=traces)
        figure.update_layout(title=title, xaxis_title=datetime_col, yaxis_title=revenue_col)

        return {
            "chart_type": "line",
            "title": title,
            "columns": [datetime_col, revenue_col] + ([breakdown_col] if valid_breakdown else []),
            "figure": figure.to_dict(),
            "layout_slot": "main",
        }

    # Fallback: if no datetime column exists, aggregate by the primary category or first categorical column
    if revenue_col:
        cats = [c for c in df.columns if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == "object"]
        if cats:
            cat = breakdown_col if (breakdown_col and breakdown_col in cats) else cats[0]
            grouped = df.groupby(cat)[revenue_col].sum().sort_values(ascending=False).head(10)
            figure = go.Figure(data=[go.Bar(x=grouped.index.astype(str).tolist(), y=grouped.values.round(2).tolist())])
            figure.update_layout(title=f"Total {revenue_col} by {cat}", xaxis_title=cat, yaxis_title=revenue_col)
            return {
                "chart_type": "bar",
                "title": f"Total {revenue_col} by {cat}",
                "columns": [cat, revenue_col],
                "figure": figure.to_dict(),
                "layout_slot": "main",
            }
        else:
            series = df[revenue_col].dropna().head(40)
            figure = go.Figure(data=[go.Scatter(y=series.tolist(), mode="lines+markers")])
            figure.update_layout(title=f"{revenue_col} Overview", yaxis_title=revenue_col)
            return {
                "chart_type": "line",
                "title": f"{revenue_col} Overview",
                "columns": [revenue_col],
                "figure": figure.to_dict(),
                "layout_slot": "main",
            }

    # Ultimate fallback
    figure = go.Figure(data=[go.Scatter(y=list(range(1, min(len(df) + 1, 50))), mode="lines")])
    figure.update_layout(title="Activity Overview")
    return {
        "chart_type": "line",
        "title": "Activity Overview",
        "columns": [],
        "figure": figure.to_dict(),
        "layout_slot": "main",
    }


def generate_ecommerce_charts(
    df: pd.DataFrame,
    schema: Optional[Dict[str, Any]] = None,
    key_roles: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generate the curated chart suite for the ecommerce dashboard:
      - main_chart: large time-series line/area chart (or categorical fallback)
      - secondary_charts: up to 4 small charts (orders bar, customer line, category donut, status radial/donut)
    """
    if schema is None:
        schema = detect_schema(df)

    key_roles = key_roles or {}
    datetime_col = key_roles.get("datetime")
    revenue_col = key_roles.get("revenue")
    order_col = key_roles.get("order_metric")
    order_agg = key_roles.get("order_agg_mode", "count")
    cust_col = key_roles.get("customer")
    category_col = key_roles.get("category")
    status_col = key_roles.get("status")

    # 1. Main "Total Sells" time-series data (supports multi-series if region/secondary category exists)
    # Check if a secondary grouping exists (like region or segment)
    all_cats = [c for c in schema.get("categorical_columns", []) if c != cust_col]
    secondary_breakdown = None
    for c in all_cats:
        if c != category_col and 2 <= df[c].dropna().nunique() <= 4:
            secondary_breakdown = c
            break

    main_chart = _build_ecommerce_main_timeseries(
        df,
        datetime_col=datetime_col,
        revenue_col=revenue_col,
        breakdown_col=secondary_breakdown or category_col
    )

    # 2. Up to 4 Small Secondary Charts
    secondary_charts: List[Dict[str, Any]] = []

    # Chart 1: Bar chart for order counts or category totals
    if category_col:
        if order_col and order_agg == "sum" and order_col in df.columns:
            grouped = df.groupby(category_col)[order_col].sum().sort_values(ascending=False).head(8)
            y_title = order_col
            b_title = f"{order_col} by {category_col}"
        else:
            grouped = df[category_col].value_counts().head(8)
            y_title = "Orders"
            b_title = f"Orders by {category_col}"

        fig_bar = go.Figure(data=[go.Bar(x=grouped.index.astype(str).tolist(), y=grouped.values.tolist())])
        fig_bar.update_layout(title=b_title, xaxis_title=category_col, yaxis_title=y_title)
        secondary_charts.append({
            "chart_type": "bar",
            "title": b_title,
            "columns": [category_col] + ([order_col] if order_col else []),
            "figure": fig_bar.to_dict(),
            "layout_slot": "secondary",
        })
    elif datetime_col:
        parsed_dates = pd.to_datetime(df[datetime_col], errors="coerce").dropna()
        if not parsed_dates.empty:
            periods = parsed_dates.dt.to_period("M").astype(str).value_counts().sort_index().tail(10)
            fig_bar = go.Figure(data=[go.Bar(x=periods.index.tolist(), y=periods.values.tolist())])
            fig_bar.update_layout(title="Order Volume over Time", xaxis_title=datetime_col, yaxis_title="Orders")
            secondary_charts.append({
                "chart_type": "bar",
                "title": "Order Volume over Time",
                "columns": [datetime_col],
                "figure": fig_bar.to_dict(),
                "layout_slot": "secondary",
            })

    # Chart 2: Line chart for customer counts / acquisition over time when possible
    if datetime_col and cust_col and cust_col in df.columns:
        parsed_dates = pd.to_datetime(df[datetime_col], errors="coerce")
        valid_df = df[parsed_dates.notna() & df[cust_col].notna()].copy()
        if not valid_df.empty:
            valid_df["date"] = pd.to_datetime(valid_df[datetime_col])
            first_dates = valid_df.groupby(cust_col)["date"].min().reset_index()
            first_dates["period"] = first_dates["date"].dt.to_period("M").astype(str)
            acq = first_dates["period"].value_counts().sort_index()
            if len(acq) >= 2:
                fig_cust = go.Figure(
                    data=[
                        go.Scatter(
                            x=acq.index.tolist(),
                            y=acq.values.tolist(),
                            mode="lines+markers",
                            name="Customers"
                        )
                    ]
                )
                fig_cust.update_layout(title="New Customers over Time", xaxis_title="Period", yaxis_title="Customers")
                secondary_charts.append({
                    "chart_type": "line",
                    "title": "New Customers over Time",
                    "columns": [datetime_col, cust_col],
                    "figure": fig_cust.to_dict(),
                    "layout_slot": "secondary",
                })
    elif cust_col and cust_col in df.columns:
        top_c = df[cust_col].value_counts().head(6)
        if len(top_c) >= 2:
            fig_cust = go.Figure(
                data=[go.Scatter(x=top_c.index.astype(str).tolist(), y=top_c.values.tolist(), mode="lines+markers")]
            )
            fig_cust.update_layout(title=f"Top {cust_col} Activity", xaxis_title=cust_col, yaxis_title="Orders")
            secondary_charts.append({
                "chart_type": "line",
                "title": f"Top {cust_col} Activity",
                "columns": [cust_col],
                "figure": fig_cust.to_dict(),
                "layout_slot": "secondary",
            })

    # Chart 3: Donut/pie for top categories/products
    if category_col:
        cat_title = f"Top {category_col}s" + (f" by {revenue_col}" if revenue_col else "")
        if revenue_col and revenue_col in df.columns:
            cat_grouped = df.groupby(category_col)[revenue_col].sum().sort_values(ascending=False).head(7)
            pie_labels = cat_grouped.index.astype(str).tolist()
            pie_vals = cat_grouped.values.round(2).tolist()
        else:
            cat_counts = df[category_col].value_counts().head(7)
            pie_labels = cat_counts.index.astype(str).tolist()
            pie_vals = cat_counts.values.tolist()

        fig_pie = go.Figure(data=[go.Pie(labels=pie_labels, values=pie_vals, hole=0.45)])
        fig_pie.update_layout(title=cat_title)
        secondary_charts.append({
            "chart_type": "pie",
            "title": cat_title,
            "columns": [category_col] + ([revenue_col] if revenue_col else []),
            "figure": fig_pie.to_dict(),
            "layout_slot": "secondary",
        })

    # Chart 4: Donut/radial-style distribution for status/payment/customer type
    if status_col and status_col in df.columns:
        status_title = f"{status_col} Distribution"
        st_counts = df[status_col].value_counts().head(6)
        fig_status = go.Figure(
            data=[go.Pie(labels=st_counts.index.astype(str).tolist(), values=st_counts.values.tolist(), hole=0.5)]
        )
        fig_status.update_layout(title=status_title)
        secondary_charts.append({
            "chart_type": "pie",
            "title": status_title,
            "columns": [status_col],
            "figure": fig_status.to_dict(),
            "layout_slot": "secondary",
        })

    # Ensure max 4 secondary charts
    return {
        "main_chart": main_chart,
        "secondary_charts": secondary_charts[:4],
    }
