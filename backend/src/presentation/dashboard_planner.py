import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd
import plotly.graph_objects as go

from src.ingestion.schema_detector import detect_schema

logger = logging.getLogger(__name__)

# Recent activity table: rows shown inline, and the cap on rows sent to the
# client (the remainder are listed in the dropdown).
TABLE_PREVIEW_ROWS = 10
MAX_TABLE_ROWS = 200

# Heuristic keyword weights for ecommerce role classification
REVENUE_KEYWORDS = [
    "revenue", "sales", "sale", "turnover", "total_amount", "gross_amount",
    "net_amount", "order_amount", "amount", "total", "price", "profit",
    "income", "subtotal", "cost", "value"
]

ORDER_COUNT_KEYWORDS = [
    "order", "orders", "transaction", "transactions", "invoice", "invoices",
    "booking", "bookings", "item", "items", "qty", "quantity", "unit", "units",
    "count", "sales_count"
]

CUSTOMER_KEYWORDS = [
    "customer", "client", "buyer", "user", "consumer", "shopper", "account",
    "member", "subscriber", "visitor", "lead"
]

CATEGORY_KEYWORDS = [
    "category", "sub_category", "product", "item", "department", "genre",
    "type", "segment", "brand", "model", "class", "group"
]

STATUS_KEYWORDS = [
    "status", "state", "stage", "payment", "paid", "plan", "subscription",
    "tier", "condition", "disposition", "result", "mode"
]

REVIEW_KEYWORDS = [
    "review", "comment", "feedback", "rating", "score", "notes", "message",
    "description", "text"
]

DATE_KEYWORDS = [
    "date", "time", "created", "timestamp", "datetime", "ordered", "purchased",
    "day", "month", "year"
]

ID_KEYWORDS = [
    "id", "code", "key", "number", "no", "num", "ref", "uuid", "hash"
]


def _normalize(name: str) -> str:
    """Normalize a column name to lowercase alphanumeric tokens separated by underscores."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower())
    return cleaned.strip("_")


def _keyword_score(normalized_name: str, keywords: List[str]) -> float:
    """Calculate a matching score based on exact match, prefix/suffix, or substring in name."""
    score = 0.0
    tokens = [t for t in normalized_name.split("_") if t]

    for kw in keywords:
        kw_norm = _normalize(kw)
        if normalized_name == kw_norm:
            score = max(score, 10.0)
        elif kw_norm in tokens:
            score = max(score, 6.0)
        elif normalized_name.startswith(f"{kw_norm}_") or normalized_name.endswith(f"_{kw_norm}"):
            score = max(score, 4.0)
        elif kw_norm in normalized_name:
            score = max(score, 2.0)
    return score


def _is_likely_identifier(col_name: str, series: pd.Series, total_rows: int) -> bool:
    """Check if a column is likely an internal unique ID rather than a continuous metric."""
    norm = _normalize(col_name)
    tokens = set(norm.split("_"))
    has_id_keyword = any(k in tokens for k in ID_KEYWORDS) or norm.endswith("id")

    unique_ratio = series.nunique(dropna=True) / max(total_rows, 1)

    # If it explicitly has an ID keyword in the name and high uniqueness
    if has_id_keyword and unique_ratio > 0.4:
        return True

    # Numeric floating-point columns with unique values (like prices or amounts: 19.99, 24.50)
    # are continuous metrics, NOT ID codes unless named id/key.
    if pd.api.types.is_float_dtype(series):
        return False

    # For integer or string/object columns: if virtually every single row has a distinct integer/string
    # and total rows > 20, it is likely an auto-incrementing surrogate index or key
    if unique_ratio > 0.98 and total_rows > 20 and has_id_keyword:
        return True

    return False


def _detect_datetime_column(df: pd.DataFrame, datetime_columns: List[str]) -> Optional[str]:
    """Pick the primary datetime column, prioritizing order/transaction date semantics."""
    if not datetime_columns:
        return None

    best_col = None
    best_score = -1.0

    for col in datetime_columns:
        norm = _normalize(col)
        score = _keyword_score(norm, DATE_KEYWORDS)

        # Extra weight if contains order/trans/create
        if any(w in norm for w in ["order", "trans", "create", "purchase", "sale"]):
            score += 5.0

        # Penalize if it looks like update or delete date
        if any(w in norm for w in ["update", "modify", "delete", "expire", "ship"]):
            score -= 1.0

        if score > best_score:
            best_score = score
            best_col = col

    return best_col or datetime_columns[0]


def _detect_revenue_column(df: pd.DataFrame, numeric_columns: List[str], total_rows: int) -> Optional[str]:
    """Pick the column that most likely represents financial monetary value / sales."""
    if not numeric_columns:
        return None

    best_col = None
    best_score = -999.0

    for col in numeric_columns:
        series = df[col].dropna()
        if series.empty:
            continue

        if _is_likely_identifier(col, series, total_rows):
            continue

        norm = _normalize(col)
        score = _keyword_score(norm, REVENUE_KEYWORDS)

        # Revenue values are usually positive and floating-point or moderate-to-large numbers
        if (series < 0).mean() < 0.05:  # almost all non-negative
            score += 1.0

        # If values have decimals or large variance, it's more likely a financial metric
        if not pd.api.types.is_integer_dtype(series):
            score += 0.5
        if series.mean() > 10:
            score += 0.5

        # Penalize columns that sound like quantities, discounts (ratios), ratings, years, or zip codes
        if any(w in norm for w in ["qty", "quantity", "year", "zip", "postal", "rate", "rating", "percent"]):
            score -= 4.0

        if score > best_score:
            best_score = score
            best_col = col

    # Fallback: if no column had a positive match, pick the numeric column with highest variance / range
    if best_col is None:
        valid_cols = [c for c in numeric_columns if not _is_likely_identifier(c, df[c].dropna(), total_rows)]
        if valid_cols:
            best_col = max(valid_cols, key=lambda c: df[c].dropna().mean() if not df[c].dropna().empty else 0)
        else:
            best_col = numeric_columns[0]

    return best_col


def _detect_order_metric(df: pd.DataFrame, numeric_columns: List[str], total_rows: int, exclude_col: Optional[str] = None) -> Tuple[Optional[str], str]:
    """
    Detect whether we should aggregate by a quantity/orders numeric column (sum)
    or count the rows/order IDs (count).
    Returns (column_name, aggregation_mode: "sum" or "count").
    """
    candidates = [c for c in numeric_columns if c != exclude_col]

    best_col = None
    best_score = -1.0

    for col in candidates:
        series = df[col].dropna()
        if series.empty:
            continue
        if _is_likely_identifier(col, series, total_rows):
            continue

        norm = _normalize(col)
        score = _keyword_score(norm, ORDER_COUNT_KEYWORDS)
        if score > best_score:
            best_score = score
            best_col = col

    if best_col and best_score > 0:
        return best_col, "sum"

    # Fallback to row counts (orders count)
    return None, "count"


def _detect_customer_column(df: pd.DataFrame, all_columns: List[str], total_rows: int) -> Optional[str]:
    """Detect customer / user / client entity column (ID, name, or email)."""
    best_col = None
    best_score = -1.0

    for col in all_columns:
        norm = _normalize(col)
        score = _keyword_score(norm, CUSTOMER_KEYWORDS)
        if score > 0:
            series = df[col].dropna()
            # Customer column usually has multiple rows per customer or decent cardinality
            n_unique = series.nunique()
            if 1 < n_unique <= total_rows:
                score += 1.0
            if score > best_score:
                best_score = score
                best_col = col

    return best_col


def _detect_category_column(
    df: pd.DataFrame,
    categorical_columns: List[str],
    exclude_columns: Set[str]
) -> Optional[str]:
    """Detect product or business category column (moderate cardinality: 2 to 25 unique values)."""
    candidates = [c for c in categorical_columns if c not in exclude_columns]
    if not candidates:
        return None

    best_col = None
    best_score = -999.0

    for col in candidates:
        series = df[col].dropna()
        if series.empty:
            continue

        n_unique = series.nunique()
        if n_unique < 2 or n_unique > 30:
            continue

        norm = _normalize(col)
        score = _keyword_score(norm, CATEGORY_KEYWORDS)

        # Ideal cardinality for category breakdown: 3 to 10
        if 3 <= n_unique <= 10:
            score += 2.0
        elif 10 < n_unique <= 20:
            score += 1.0

        if score > best_score:
            best_score = score
            best_col = col

    # Fallback to any categorical column with 2-15 unique values
    if best_col is None:
        suitable = [c for c in candidates if 2 <= df[c].dropna().nunique() <= 15]
        if suitable:
            best_col = suitable[0]

    return best_col


def _detect_status_column(
    df: pd.DataFrame,
    categorical_columns: List[str],
    exclude_columns: Set[str]
) -> Optional[str]:
    """Detect status, payment method, or binary/low-cardinality distribution column (2 to 6 unique values)."""
    candidates = [c for c in categorical_columns if c not in exclude_columns]
    if not candidates:
        return None

    best_col = None
    best_score = -999.0

    for col in candidates:
        series = df[col].dropna()
        if series.empty:
            continue

        n_unique = series.nunique()
        if n_unique < 2 or n_unique > 8:
            continue

        norm = _normalize(col)
        score = _keyword_score(norm, STATUS_KEYWORDS)

        # Prefer 2-5 values for a compact donut/radial breakdown
        if 2 <= n_unique <= 4:
            score += 2.0

        if score > best_score:
            best_score = score
            best_col = col

    # Fallback: if keywords don't match, pick any 2-4 category column
    if best_col is None:
        low_cardinality = [c for c in candidates if 2 <= df[c].dropna().nunique() <= 5]
        if low_cardinality:
            best_col = low_cardinality[0]

    return best_col


def _detect_table_columns(
    df: pd.DataFrame,
    schema: Dict[str, Any],
    key_roles: Dict[str, Optional[str]]
) -> List[str]:
    """Select the most informative 4-7 columns for the recent activity table."""
    all_columns = schema.get("columns", list(df.columns))
    selected: List[str] = []

    # Priority 1: Key entity columns from roles
    for role_key in ["datetime", "customer", "category", "revenue", "order_metric", "status"]:
        col = key_roles.get(role_key)
        if col and col in all_columns and col not in selected:
            selected.append(col)

    # Priority 2: Look for ID or Review/Description columns if not yet present
    for col in all_columns:
        if col not in selected:
            norm = _normalize(col)
            if _keyword_score(norm, ID_KEYWORDS) > 0 or _keyword_score(norm, REVIEW_KEYWORDS) > 0:
                selected.append(col)
                if len(selected) >= 6:
                    break

    # Priority 3: Add remaining columns up to 6
    for col in all_columns:
        if col not in selected:
            selected.append(col)
        if len(selected) >= 6:
            break

    return selected


# ---------------------------------------------------------------------------
# Visual Builders
# ---------------------------------------------------------------------------

def _build_main_chart(
    df: pd.DataFrame,
    datetime_col: Optional[str],
    revenue_col: Optional[str]
) -> Dict[str, Any]:
    """Build the large main line/area chart: total sales/revenue over time."""
    if datetime_col and revenue_col:
        # Time-aggregated series
        parsed_dates = pd.to_datetime(df[datetime_col], errors="coerce")
        valid_mask = parsed_dates.notna() & df[revenue_col].notna()
        sub_df = pd.DataFrame({
            "date": parsed_dates[valid_mask],
            "val": df.loc[valid_mask, revenue_col].astype(float)
        }).sort_values(by="date")

        # Aggregate if many points (> 30 points -> monthly or daily)
        if len(sub_df) > 30:
            # Check date range
            date_range = (sub_df["date"].max() - sub_df["date"].min()).days
            freq = "M" if date_range > 90 else "D"
            sub_df["period"] = sub_df["date"].dt.to_period(freq).astype(str)
            grouped = sub_df.groupby("period")["val"].sum().reset_index()
            x_vals = grouped["period"].tolist()
            y_vals = grouped["val"].round(2).tolist()
        else:
            x_vals = sub_df["date"].dt.strftime("%Y-%m-%d").tolist()
            y_vals = sub_df["val"].round(2).tolist()

        title = f"{revenue_col} Over Time"
        figure = go.Figure(
            data=[
                go.Scatter(
                    x=x_vals,
                    y=y_vals,
                    mode="lines+markers",
                    fill="tozeroy",
                    name=revenue_col
                )
            ]
        )
        figure.update_layout(title=title, xaxis_title=datetime_col, yaxis_title=revenue_col)

        return {
            "chart_type": "line",
            "title": title,
            "columns": [datetime_col, revenue_col],
            "figure": figure.to_dict(),
            "layout_slot": "main",
        }

    # Graceful fallback if no datetime column exists: top items by revenue or histogram of revenue
    if revenue_col:
        # If there's any categorical column, show top categories by revenue
        cats = [c for c in df.columns if pd.api.types.is_string_dtype(df[c]) or df[c].dtype == "object"]
        if cats:
            cat = cats[0]
            grouped = df.groupby(cat)[revenue_col].sum().sort_values(ascending=False).head(15)
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
            # Line of cumulative or series values
            series = df[revenue_col].dropna().head(50)
            figure = go.Figure(data=[go.Scatter(y=series.tolist(), mode="lines+markers")])
            figure.update_layout(title=f"{revenue_col} Trend", yaxis_title=revenue_col)
            return {
                "chart_type": "line",
                "title": f"{revenue_col} Trend",
                "columns": [revenue_col],
                "figure": figure.to_dict(),
                "layout_slot": "main",
            }

    # Ultimate fallback: Row counts over index
    figure = go.Figure(data=[go.Scatter(y=list(range(1, min(len(df) + 1, 100))), mode="lines")])
    figure.update_layout(title="Activity Trend")
    return {
        "chart_type": "line",
        "title": "Activity Trend",
        "columns": [],
        "figure": figure.to_dict(),
        "layout_slot": "main",
    }


def _build_orders_chart(
    df: pd.DataFrame,
    datetime_col: Optional[str],
    category_col: Optional[str],
    order_col: Optional[str],
    agg_mode: str
) -> Optional[Dict[str, Any]]:
    """Build small bar chart: orders/volume over time or by category."""
    if category_col:
        if order_col and agg_mode == "sum":
            grouped = df.groupby(category_col)[order_col].sum().sort_values(ascending=False).head(8)
            title = f"{order_col} by {category_col}"
            y_title = order_col
        else:
            grouped = df[category_col].value_counts().head(8)
            title = f"Orders by {category_col}"
            y_title = "Order Count"

        figure = go.Figure(data=[go.Bar(x=grouped.index.astype(str).tolist(), y=grouped.values.tolist())])
        figure.update_layout(title=title, xaxis_title=category_col, yaxis_title=y_title)
        return {
            "chart_type": "bar",
            "title": title,
            "columns": [category_col] + ([order_col] if order_col else []),
            "figure": figure.to_dict(),
            "layout_slot": "secondary",
        }

    if datetime_col:
        parsed_dates = pd.to_datetime(df[datetime_col], errors="coerce").dropna()
        if not parsed_dates.empty:
            periods = parsed_dates.dt.to_period("M").astype(str).value_counts().sort_index().tail(12)
            figure = go.Figure(data=[go.Bar(x=periods.index.tolist(), y=periods.values.tolist())])
            figure.update_layout(title=f"Order Volume over {datetime_col}", xaxis_title=datetime_col, yaxis_title="Orders")
            return {
                "chart_type": "bar",
                "title": f"Order Volume over {datetime_col}",
                "columns": [datetime_col],
                "figure": figure.to_dict(),
                "layout_slot": "secondary",
            }

    return None


def _build_customers_chart(
    df: pd.DataFrame,
    datetime_col: Optional[str],
    customer_col: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Build small line chart: customers or new customers over time."""
    if datetime_col and customer_col:
        parsed_dates = pd.to_datetime(df[datetime_col], errors="coerce")
        valid_df = df[parsed_dates.notna() & df[customer_col].notna()].copy()
        if not valid_df.empty:
            valid_df["date"] = pd.to_datetime(valid_df[datetime_col])
            # Track first occurrence of each customer (new customer acquisition)
            first_dates = valid_df.groupby(customer_col)["date"].min().reset_index()
            first_dates["period"] = first_dates["date"].dt.to_period("M").astype(str)
            acq_counts = first_dates["period"].value_counts().sort_index()

            if len(acq_counts) >= 2:
                figure = go.Figure(
                    data=[
                        go.Scatter(
                            x=acq_counts.index.tolist(),
                            y=acq_counts.values.tolist(),
                            mode="lines+markers",
                            name="New Customers"
                        )
                    ]
                )
                figure.update_layout(title="New Customer Acquisition", xaxis_title="Period", yaxis_title="New Customers")
                return {
                    "chart_type": "line",
                    "title": "New Customer Acquisition",
                    "columns": [datetime_col, customer_col],
                    "figure": figure.to_dict(),
                    "layout_slot": "secondary",
                }

    # Fallback: Top customers by order count or volume
    if customer_col:
        top_cust = df[customer_col].dropna().value_counts().head(8)
        if len(top_cust) > 1:
            figure = go.Figure(
                data=[go.Scatter(x=top_cust.index.astype(str).tolist(), y=top_cust.values.tolist(), mode="lines+markers")]
            )
            figure.update_layout(title=f"Top {customer_col} Activity", xaxis_title=customer_col, yaxis_title="Count")
            return {
                "chart_type": "line",
                "title": f"Top {customer_col} Activity",
                "columns": [customer_col],
                "figure": figure.to_dict(),
                "layout_slot": "secondary",
            }

    return None


def _build_donut_chart(
    df: pd.DataFrame,
    col_name: str,
    title: str,
    value_col: Optional[str] = None
) -> Dict[str, Any]:
    """Build small donut/pie chart."""
    if value_col:
        grouped = df.groupby(col_name)[value_col].sum().sort_values(ascending=False).head(8)
        labels = grouped.index.astype(str).tolist()
        values = grouped.values.round(2).tolist()
    else:
        counts = df[col_name].dropna().value_counts().head(8)
        labels = counts.index.astype(str).tolist()
        values = counts.values.tolist()

    figure = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.45  # Donut style
            )
        ]
    )
    figure.update_layout(title=title)
    return {
        "chart_type": "pie",
        "title": title,
        "columns": [col_name] + ([value_col] if value_col else []),
        "figure": figure.to_dict(),
        "layout_slot": "secondary",
    }


def _build_metric_cards(
    df: pd.DataFrame,
    key_roles: Dict[str, Optional[str]],
    total_rows: int
) -> List[Dict[str, Any]]:
    """Build high-level ecommerce KPI metric cards."""
    cards: List[Dict[str, Any]] = []

    # 1. Total Revenue / Financial Metric
    rev_col = key_roles.get("revenue")
    if rev_col and rev_col in df.columns:
        series = df[rev_col].dropna().astype(float)
        cards.append({
            "key": "total_revenue",
            "label": f"Total {rev_col}",
            "value": round(float(series.sum()), 2),
            "formatted": f"{series.sum():,.2f}",
            "column": rev_col,
            "type": "currency_or_number"
        })
        cards.append({
            "key": "avg_order_value",
            "label": f"Avg {rev_col}",
            "value": round(float(series.mean()), 2),
            "formatted": f"{series.mean():,.2f}",
            "column": rev_col,
            "type": "currency_or_number"
        })

    # 2. Total Orders / Transactions
    order_col = key_roles.get("order_metric")
    if order_col and key_roles.get("order_agg_mode") == "sum" and order_col in df.columns:
        qty_sum = float(df[order_col].dropna().sum())
        cards.append({
            "key": "total_volume",
            "label": f"Total {order_col}",
            "value": int(qty_sum) if qty_sum.is_integer() else round(qty_sum, 2),
            "formatted": f"{qty_sum:,.0f}" if qty_sum.is_integer() else f"{qty_sum:,.2f}",
            "column": order_col,
            "type": "count"
        })
    else:
        cards.append({
            "key": "total_orders",
            "label": "Total Orders",
            "value": total_rows,
            "formatted": f"{total_rows:,}",
            "column": None,
            "type": "count"
        })

    # 3. Unique Customers
    cust_col = key_roles.get("customer")
    if cust_col and cust_col in df.columns:
        n_cust = int(df[cust_col].dropna().nunique())
        cards.append({
            "key": "total_customers",
            "label": f"Unique {cust_col}s",
            "value": n_cust,
            "formatted": f"{n_cust:,}",
            "column": cust_col,
            "type": "count"
        })

    # Ensure we return 3-5 concise, high-value cards
    if len(cards) < 4:
        # Add missing value rate or categorical entity count
        cat_col = key_roles.get("category")
        if cat_col and cat_col in df.columns:
            n_cats = int(df[cat_col].dropna().nunique())
            cards.append({
                "key": "total_categories",
                "label": f"Active {cat_col}s",
                "value": n_cats,
                "formatted": f"{n_cats:,}",
                "column": cat_col,
                "type": "count"
            })

    return cards[:5]


def _build_table_data(
    df: pd.DataFrame,
    table_columns: List[str],
    datetime_col: Optional[str]
) -> Dict[str, Any]:
    """Build recent activity table data (sorted by date descending if datetime exists).

    The first 10 rows are shown inline in the table; the rest are available as
    a dropdown list in the UI, so more rows are sent than are displayed.
    """
    if not table_columns:
        return {"columns": [], "rows": [], "total_rows": len(df)}

    subset_df = df[table_columns].copy()

    # Sort by datetime if present
    if datetime_col and datetime_col in subset_df.columns:
        try:
            parsed = pd.to_datetime(subset_df[datetime_col], errors="coerce")
            subset_df["_sort_date"] = parsed
            subset_df = subset_df.sort_values(by="_sort_date", ascending=False).drop(columns=["_sort_date"])
        except Exception:
            pass

    # Cap what we send so a huge dataset cannot blow up the payload; the
    # frontend shows the first 10 and lists the remainder in a dropdown.
    display_rows = subset_df.head(MAX_TABLE_ROWS).fillna("").to_dict(orient="records")

    return {
        "columns": table_columns,
        "rows": display_rows,
        "preview_count": TABLE_PREVIEW_ROWS,
        "total_rows": len(df),
        "title": "Recent Orders & Activity",
    }


# ---------------------------------------------------------------------------
# Main Planner Entry Point
# ---------------------------------------------------------------------------

def detect_roles(df: pd.DataFrame, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Deterministically detect the key business/ecommerce column roles from schema.
    Returns a dict with roles: datetime, revenue, order_metric, order_agg_mode,
    customer, category, status, and table_columns.
    """
    if schema is None:
        schema = detect_schema(df)

    total_rows = schema["total_rows"]
    numeric_columns = schema["numeric_columns"]
    categorical_columns = schema["categorical_columns"]
    datetime_columns = schema["datetime_columns"]
    all_columns = schema["columns"]

    datetime_col = _detect_datetime_column(df, datetime_columns)
    revenue_col = _detect_revenue_column(df, numeric_columns, total_rows)
    order_col, agg_mode = _detect_order_metric(df, numeric_columns, total_rows, exclude_col=revenue_col)
    cust_col = _detect_customer_column(df, all_columns, total_rows)

    excluded_cats: Set[str] = set()
    if cust_col and cust_col in categorical_columns:
        excluded_cats.add(cust_col)

    category_col = _detect_category_column(df, categorical_columns, excluded_cats)
    if category_col:
        excluded_cats.add(category_col)

    status_col = _detect_status_column(df, categorical_columns, excluded_cats)

    key_roles = {
        "datetime": datetime_col,
        "revenue": revenue_col,
        "order_metric": order_col,
        "order_agg_mode": agg_mode,
        "customer": cust_col,
        "category": category_col,
        "status": status_col,
    }

    table_cols = _detect_table_columns(df, schema, key_roles)
    key_roles["table_columns"] = table_cols

    return key_roles


def plan_dashboard(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate an ecommerce-style dashboard layout plan from a DataFrame.

    Adheres strictly to the detected schema from schema_detector.py without
    hardcoding column names.

    Returns:
    {
        "main_chart": {...},
        "metric_cards": [...],
        "secondary_charts": [...],
        "table": {...}
    }
    """
    schema = detect_schema(df)
    key_roles = detect_roles(df, schema)

    datetime_col = key_roles["datetime"]
    revenue_col = key_roles["revenue"]
    order_col = key_roles["order_metric"]
    agg_mode = key_roles["order_agg_mode"]
    cust_col = key_roles["customer"]
    category_col = key_roles["category"]
    status_col = key_roles["status"]

    logger.info("Planned ecommerce roles: %s", key_roles)

    # 2. Main Large Chart
    main_chart = _build_main_chart(df, datetime_col, revenue_col)

    # 3. Secondary Visuals (target: 3 to 4 useful charts, maximum 5)
    secondary_charts: List[Dict[str, Any]] = []

    # Chart A: Orders over time or by category
    orders_chart = _build_orders_chart(df, datetime_col, category_col, order_col, agg_mode)
    if orders_chart:
        secondary_charts.append(orders_chart)

    # Chart B: New customers / customer activity over time
    cust_chart = _build_customers_chart(df, datetime_col, cust_col)
    if cust_chart:
        secondary_charts.append(cust_chart)

    # Chart C: Top category/product donut/pie chart
    if category_col:
        cat_title = f"Top {category_col}s" + (f" by {revenue_col}" if revenue_col else "")
        secondary_charts.append(_build_donut_chart(df, category_col, cat_title, value_col=revenue_col))

    # Chart D: Status / payment / segment distribution
    if status_col:
        status_title = f"{status_col} Distribution"
        secondary_charts.append(_build_donut_chart(df, status_col, status_title))

    # Ensure total visual components stay lean (around 4-6 total: 1 main + max 4 secondary)
    secondary_charts = secondary_charts[:4]

    # 4. Metric Cards
    metric_cards = _build_metric_cards(df, key_roles, schema["total_rows"])

    # 5. Table: Recent orders / reviews / activity
    table_data = _build_table_data(df, key_roles["table_columns"], datetime_col)

    return {
        "main_chart": main_chart,
        "metric_cards": metric_cards,
        "secondary_charts": secondary_charts,
        "table": table_data,
    }


def generate_dashboard(df: pd.DataFrame) -> Dict[str, Any]:
    """
    End-to-end ecommerce dashboard generation flow:
      schema_detector -> KPI generator -> dashboard planner -> chart/data generation

    Produces the complete, unified dashboard response structure:
    {
      "title": "Ecommerce Dashboard",
      "subtitle": "Here's what's going on at your business right now",
      "quick_stats": [...],
      "kpis": [...],
      "main_chart": {...},
      "secondary_charts": [...],
      "latest_table": {...}
    }
    """
    from src.presentation.chart_generator import generate_ecommerce_charts
    from src.presentation.kpi_generator import generate_ecommerce_kpis

    # Step 1: schema_detector (single source of truth)
    schema = detect_schema(df)

    # Step 2 & 3: dashboard planner role detection
    key_roles = detect_roles(df, schema)

    # Step 4: KPI generator (top-level stat values and quick stats)
    kpi_result = generate_ecommerce_kpis(df, schema=schema, key_roles=key_roles)

    # Step 5: Chart generator (main time-series + small metric charts)
    chart_result = generate_ecommerce_charts(df, schema=schema, key_roles=key_roles)

    # Step 6: Latest orders / reviews table
    datetime_col = key_roles.get("datetime")
    latest_table = _build_table_data(df, key_roles.get("table_columns", []), datetime_col)

    return {
        "title": "Ecommerce Dashboard",
        "subtitle": "Here's what's going on at your business right now",
        "quick_stats": kpi_result.get("quick_stats", []),
        "kpis": kpi_result.get("kpis", []),
        "main_chart": chart_result.get("main_chart", {}),
        "secondary_charts": chart_result.get("secondary_charts", []),
        "latest_table": latest_table,
    }
