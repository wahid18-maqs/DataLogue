"""Generates professional PowerPoint (.pptx) presentations dynamically from datasets."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import (
    XL_CHART_TYPE,
    XL_LEGEND_POSITION,
)
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from src.presentation.dashboard_planner import detect_roles
from src.presentation.dataset_document import build_dataset_document
from src.presentation.deck_agent import run_deck_agent, run_slide_plan_agent
import src.presentation.deck_agent as deck_agent
from src.presentation.kpi_generator import generate_ecommerce_kpis
from src.ingestion.schema_detector import detect_schema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Themes
#
# A theme is a named set of colours. The one the app uses by default is
# "light" — the modern minimalist corporate palette — and the others are
# the alternatives offered in Settings. The theme is passed into the
# slide-building pipeline rather than hardcoded, so the requester can
# change it and the deck follows.
#
# The colours are stored as hex strings, because the same values are sent
# to the browser, which renders the slide preview from them. The PPTX
# renderer converts them to RGBColor at draw time.
# ---------------------------------------------------------------------------

THEME_LIGHT = {
    "bg_dark": "0F172A",       # Slate 900
    "primary": "2563EB",       # Royal Blue 600
    "secondary": "06B6D4",     # Cyan 500
    "accent": "8B5CF6",        # Violet 500
    "text_main": "1E293B",     # Slate 800
    "text_muted": "64748B",    # Slate 500
    "card_bg": "F8FAFC",       # Slate 50
    "border": "E2E8F0",        # Slate 200
    "on_dark": "FFFFFF",       # Slate 900
    "success": "10B981",       # Emerald 500
}

THEME_DARK = {
    "bg_dark": "020617",       # Slate 950
    "primary": "60A5FA",       # Blue 400
    "secondary": "22D3EE",     # Cyan 400
    "accent": "A78BFA",        # Violet 400
    "text_main": "F1F5F9",     # Slate 100
    "text_muted": "94A3B8",    # Slate 400
    "card_bg": "0F172A",       # Slate 900
    "border": "334155",        # Slate 700
    "on_dark": "F8FAFC",       # Slate 50
    "success": "34D399",       # Emerald 400
}

THEME_EXECUTIVE_NAVY = {
    "bg_dark": "0B1B33",       # Navy 950
    "primary": "1E3A8A",       # Navy 800
    "secondary": "38BDF8",     # Sky 400
    "accent": "C9A227",        # Gold
    "text_main": "0F172A",     # Slate 900
    "text_muted": "475569",    # Slate 600
    "card_bg": "F1F5F9",       # Slate 100
    "border": "CBD5E1",        # Slate 300
    "on_dark": "F8FAFC",       # Slate 50
    "success": "059669",       # Emerald 600
}

THEMES = {
    "light": THEME_LIGHT,
    "dark": THEME_DARK,
    "executive_navy": THEME_EXECUTIVE_NAVY,
}

# The chart series colours, in the order the series are drawn. Each theme
# has its own, so a dark deck's lines read against a dark background. The
# browser draws the preview from the same list, so the picture on screen
# and the one in the file are the same.
THEME_SERIES_COLORS = {
    "light": ["2563EB", "06B6D4", "8B5CF6", "10B981", "F59E0B", "EF4444", "3B82F6", "14B8A6"],
    "dark": ["60A5FA", "22D3EE", "A78BFA", "34D399", "FBBF24", "F87171", "93C5FD", "2DD4BF"],
    "executive_navy": ["1E3A8A", "38BDF8", "C9A227", "0F766E", "B45309", "9F1239", "4F46E5", "0D9488"],
}

DEFAULT_THEME = "light"

FONT_HEADING = "Helvetica Neue"
FONT_BODY = "Arial"

# ---------------------------------------------------------------------------
# Detail levels
#
# How much a slide carries. "concise" is the executive skim, "standard" is
# the normal briefing, and "detailed" is the working document. The level is
# applied to the finished slide plan, so it works the same whether the text
# came from the agent or from the deterministic templates.
# ---------------------------------------------------------------------------

DETAIL_LEVELS = ("concise", "standard", "detailed")
DEFAULT_DETAIL_LEVEL = "standard"

_DETAIL_LIMITS = {
    "concise": {"findings": 3, "insights": 3, "recommendations": 3, "chart_points": 5, "captions": False},
    "standard": {"findings": 4, "insights": 4, "recommendations": 4, "chart_points": 8, "captions": True},
    "detailed": {"findings": 5, "insights": 5, "recommendations": 5, "chart_points": 12, "captions": True},
}

# Canonical PowerPoint 16:9 widescreen dimensions (13.333in x 7.5in) expressed
# in EMU. Using the exact values keeps the deck a true 16:9 slide.
SLIDE_WIDTH_EMU = 12192000
SLIDE_HEIGHT_EMU = 6858000

# Maximum number of bars/points rendered on a chart slide.
MAX_CHART_POINTS = 8
MAX_TREND_POINTS = 18

_CHART_TYPES = {
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "bar": XL_CHART_TYPE.BAR_CLUSTERED,
}

# Ordered pipeline stages reported to the client while a deck is generated.
GENERATION_STAGES = [
    "reading_spreadsheet",
    "detecting_columns",
    "analyzing_data",
    "writing_narrative",
    "generating_slides",
    "preparing_powerpoint",
]

ProgressCallback = Callable[[str, str], None]


def _noop_progress(stage: str, message: str) -> None:
    """Default progress callback: discards stage updates."""
    return None


def _compute_findings(
    df: pd.DataFrame,
    key_roles: Dict[str, Any],
    schema: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute the statistics the deck agent is allowed to talk about.

    These are the same numbers the deterministic slide templates use, gathered
    into one place so the agent receives a single, complete picture of the
    dataset and cannot be asked to speculate beyond it.
    """
    findings: Dict[str, Any] = {
        "total_rows": int(schema.get("total_rows", len(df))),
        "total_columns": int(schema.get("total_columns", df.shape[1])),
    }

    rev_col = key_roles.get("revenue")
    if rev_col and rev_col in df.columns:
        series = df[rev_col].dropna().astype(float)
        if not series.empty:
            findings["revenue_column"] = rev_col
            findings["revenue_total"] = round(float(series.sum()), 2)
            findings["revenue_average"] = round(float(series.mean()), 2)
            findings["revenue_median"] = round(float(series.median()), 2)
            findings["revenue_max"] = round(float(series.max()), 2)
            findings["revenue_min"] = round(float(series.min()), 2)

            p75 = series.quantile(0.75)
            total = max(float(series.sum()), 1e-9)
            findings["top_quartile_share_pct"] = round(
                float((series >= p75).sum() / max(len(series), 1) * 100), 2
            )
            findings["top_quartile_value_share_pct"] = round(
                float(series[series >= p75].sum() / total * 100), 2
            )

    cat_col = key_roles.get("category")
    if cat_col and cat_col in df.columns:
        counts = df[cat_col].dropna().value_counts()
        if not counts.empty:
            findings["category_column"] = cat_col
            findings["category_count"] = int(len(counts))
            findings["top_category"] = str(counts.index[0])
            findings["top_category_count"] = int(counts.iloc[0])
            findings["top_category_share_pct"] = round(
                float(counts.iloc[0] / max(len(df), 1) * 100), 2
            )
            if rev_col and rev_col in df.columns:
                by_cat = df.groupby(cat_col)[rev_col].sum().sort_values(ascending=False)
                if not by_cat.empty:
                    findings["top_category_by_revenue"] = str(by_cat.index[0])
                    findings["top_category_revenue"] = round(float(by_cat.iloc[0]), 2)
                    findings["category_revenue_total"] = round(float(by_cat.sum()), 2)

    cust_col = key_roles.get("customer")
    if cust_col and cust_col in df.columns:
        findings["customer_column"] = cust_col
        findings["unique_customers"] = int(df[cust_col].dropna().nunique())

    status_col = key_roles.get("status")
    if status_col and status_col in df.columns:
        counts = df[status_col].dropna().value_counts()
        if not counts.empty:
            findings["status_column"] = status_col
            findings["top_status"] = str(counts.index[0])
            findings["top_status_count"] = int(counts.iloc[0])
            findings["top_status_share_pct"] = round(
                float(counts.iloc[0] / max(len(df), 1) * 100), 2
            )
            findings["status_breakdown"] = {
                str(k): int(v) for k, v in counts.head(5).items()
            }

    date_col = key_roles.get("datetime")
    if date_col and date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not dates.empty:
            span_days = int((dates.max() - dates.min()).days)
            findings["datetime_column"] = date_col
            findings["period_start"] = dates.min().strftime("%Y-%m-%d")
            findings["period_end"] = dates.max().strftime("%Y-%m-%d")
            findings["period_days"] = span_days
            findings["average_events_per_month"] = round(
                float(len(dates) / max(span_days / 30.0, 1.0)), 2
            )
            if rev_col and rev_col in df.columns:
                tmp = pd.DataFrame({
                    "date": dates,
                    "val": df.loc[dates.index, rev_col].astype(float),
                }).dropna().sort_values("date")
                if len(tmp) >= 2:
                    first_half = float(tmp["val"].head(len(tmp) // 2).mean())
                    second_half = float(tmp["val"].tail(len(tmp) // 2).mean())
                    findings["trend_first_half_average"] = round(first_half, 2)
                    findings["trend_second_half_average"] = round(second_half, 2)
                    findings["trend_change_pct"] = round(
                        ((second_half - first_half) / abs(first_half) * 100)
                        if first_half else 0.0,
                        2,
                    )
                    findings["trend_direction"] = (
                        "upward" if second_half > first_half
                        else "downward" if second_half < first_half
                        else "flat"
                    )

    missing = schema.get("missing_values", {})
    total_missing = int(sum(missing.values()))
    findings["total_missing_values"] = total_missing
    findings["data_completeness_pct"] = round(
        100.0 - (total_missing / max(len(df) * max(df.shape[1], 1), 1) * 100), 2
    )
    if missing:
        findings["columns_with_missing"] = {
            k: int(v) for k, v in sorted(
                missing.items(), key=lambda kv: kv[1], reverse=True
            )[:5] if v > 0
        }

    return findings


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------

def _plan_title_and_kpis(
    df: pd.DataFrame,
    key_roles: Dict[str, Any],
    schema: Dict[str, Any],
    narrative: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build slide 1 plan: title, scope line, KPI tiles and highlight banner."""
    rev_col = key_roles.get("revenue")
    title_text = "Business Performance & Analytics Report"
    if rev_col:
        title_text = f"{rev_col.replace('_', ' ').title()} & Operations Overview"

    scope_text = f"Dataset Analysis ({schema['total_rows']:,} records, {schema['total_columns']} attributes)"
    date_col = key_roles.get("datetime")
    if date_col and date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not dates.empty:
            scope_text += f" | Period: {dates.min().strftime('%b %Y')} – {dates.max().strftime('%b %Y')}"

    kpi_result = generate_ecommerce_kpis(df, schema=schema, key_roles=key_roles)
    kpis = kpi_result.get("kpis", [])[:4]
    if not kpis:
        kpis = [
            {"label": "Total Records", "formatted": f"{schema['total_rows']:,}"},
            {"label": "Total Attributes", "formatted": f"{schema['total_columns']:,}"},
        ]

    kpi_tiles = [
        {
            "label": str(kpi.get("label", "")),
            "value": str(kpi.get("formatted", kpi.get("value", "—"))),
            "caption": str(kpi.get("caption") or kpi.get("helper") or "Verified from active dataset"),
        }
        for kpi in kpis
    ]

    summary_pts = []
    if rev_col and rev_col in df.columns:
        summary_pts.append(f"Aggregate {rev_col} recorded: {df[rev_col].dropna().sum():,.2f}")
    cust_col = key_roles.get("customer")
    if cust_col and cust_col in df.columns:
        summary_pts.append(f"{df[cust_col].dropna().nunique():,} unique active entities ({cust_col})")
    cat_col = key_roles.get("category")
    if cat_col and cat_col in df.columns:
        summary_pts.append(f"categorized across {df[cat_col].dropna().nunique()} distinct {cat_col} groups")

    banner_text = (
        "This report delivers evidence-backed operational intelligence. High-level indicators confirm: "
        f"{'; '.join(summary_pts)}."
        if summary_pts
        else "This report delivers evidence-backed operational intelligence derived directly from the uploaded dataset."
    )

    # The agent's wording wins when it produced a usable narrative; the
    # template above is the fallback.
    agent_banner = (narrative or {}).get("banner_highlight")
    if agent_banner:
        banner_text = agent_banner

    return {
        "type": "title",
        "title": title_text,
        "subtitle": scope_text,
        "kpis": kpi_tiles,
        "banner_label": "Executive Summary Highlight",
        "banner_text": banner_text,
    }


def _plan_executive_summary(
    df: pd.DataFrame,
    key_roles: Dict[str, Any],
    narrative: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build slide 2 plan: data-derived key findings."""
    findings = []

    rev_col = key_roles.get("revenue")
    if rev_col and rev_col in df.columns:
        s_rev = df[rev_col].dropna().astype(float)
        findings.append({
            "title": f"Monetary / Volume Scale ({rev_col})",
            "desc": f"Total accumulated value is {s_rev.sum():,.2f} with an average of {s_rev.mean():,.2f} per transaction. The standard median sits at {s_rev.median():,.2f}.",
        })

    cat_col = key_roles.get("category")
    if cat_col and cat_col in df.columns:
        top_cat = df[cat_col].dropna().value_counts()
        if not top_cat.empty:
            lead_name = top_cat.index[0]
            lead_count = top_cat.iloc[0]
            pct = (lead_count / len(df)) * 100
            findings.append({
                "title": f"Concentration in {cat_col}",
                "desc": f"The primary category '{lead_name}' accounts for {lead_count:,} entries ({pct:.1f}% of total volume), leading overall distributions.",
            })

    date_col = key_roles.get("datetime")
    if date_col and date_col in df.columns:
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        if not dates.empty:
            span_months = max(1, (dates.max() - dates.min()).days // 30)
            avg_per_month = len(dates) / span_months
            findings.append({
                "title": "Temporal Velocity",
                "desc": f"Activity spans from {dates.min().strftime('%Y-%m-%d')} to {dates.max().strftime('%Y-%m-%d')} averaging approximately {avg_per_month:.1f} events/month.",
            })

    status_col = key_roles.get("status")
    if status_col and status_col in df.columns:
        top_st = df[status_col].dropna().value_counts()
        if not top_st.empty:
            findings.append({
                "title": f"Operational Status ({status_col})",
                "desc": f"Top disposition '{top_st.index[0]}' represents {top_st.iloc[0]:,} records ({(top_st.iloc[0] / len(df)) * 100:.1f}%).",
            })

    if not findings:
        return None

    # The agent's own sections replace the template ones when it produced
    # them; the templates stay as the fallback.
    agent_sections = (narrative or {}).get("executive_summary_sections") or []
    if agent_sections:
        findings = [
            {"title": section["heading"], "desc": section["body"]}
            for section in agent_sections
        ]

    return {
        "type": "summary",
        "category": "Executive Briefing",
        "title": "Executive Summary & Core Findings",
        "findings": findings[:4],
    }


def _plan_trend_analysis(
    df: pd.DataFrame,
    key_roles: Dict[str, Any],
    narrative: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build slide 3 plan: native editable line chart over time."""
    date_col = key_roles.get("datetime")
    rev_col = key_roles.get("revenue")

    if not (date_col and rev_col and date_col in df.columns and rev_col in df.columns):
        return None

    parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
    valid_mask = parsed_dates.notna() & df[rev_col].notna()
    sub_df = pd.DataFrame({
        "date": parsed_dates[valid_mask],
        "val": df.loc[valid_mask, rev_col].astype(float)
    }).sort_values(by="date")

    if len(sub_df) < 2:
        return None

    date_range = (sub_df["date"].max() - sub_df["date"].min()).days
    freq = "M" if date_range > 60 else "D"
    sub_df["period"] = sub_df["date"].dt.to_period(freq).astype(str)
    grouped = sub_df.groupby("period")["val"].sum()

    if len(grouped) < 2:
        return None

    if len(grouped) > MAX_TREND_POINTS:
        grouped = grouped.tail(MAX_TREND_POINTS)

    return {
        "type": "chart",
        "category": "Temporal Analysis",
        "title": f"{rev_col.replace('_', ' ').title()} Trend Over Time",
        "chart_type": "line",
        "categories": [str(p) for p in grouped.index],
        "series": [{
            "name": rev_col.replace("_", " ").title(),
            "values": [float(round(v, 2)) for v in grouped.values],
        }],
        "legend": True,
        # The agent's one-line reading of the trend, shown as the slide caption.
        "caption": (narrative or {}).get("trend_caption", ""),
    }


def _plan_category_performance(df: pd.DataFrame, key_roles: Dict[str, Any], schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build slide 4 plan: category / regional performance column chart."""
    cat_col = key_roles.get("category")
    rev_col = key_roles.get("revenue")

    if not cat_col or cat_col not in df.columns:
        cats = [c for c in schema.get("categorical_columns", []) if 2 <= df[c].dropna().nunique() <= 12]
        if cats:
            cat_col = cats[0]
        else:
            return None

    if rev_col and rev_col in df.columns:
        grouped = df.groupby(cat_col)[rev_col].sum().sort_values(ascending=False).head(MAX_CHART_POINTS)
        metric_label = rev_col.replace("_", " ").title()
    else:
        grouped = df[cat_col].value_counts().head(MAX_CHART_POINTS)
        metric_label = "Record Count"

    if len(grouped) < 2:
        return None

    return {
        "type": "chart",
        "category": "Segment Analysis",
        "title": f"Performance by {cat_col.replace('_', ' ').title()}",
        "chart_type": "column",
        "categories": [str(c) for c in grouped.index],
        "series": [{
            "name": metric_label,
            "values": [float(round(v, 2)) for v in grouped.values],
        }],
        "legend": False,
    }


def _plan_top_items(df: pd.DataFrame, key_roles: Dict[str, Any], schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build slide 5 plan: ranked horizontal bar chart of top items."""
    item_candidates = [
        c for c in df.columns
        if any(k in c.lower() for k in ["product", "item", "sub_category", "service", "sku", "title", "name"])
        and c != key_roles.get("customer")
    ]

    item_col = None
    if item_candidates:
        item_col = item_candidates[0]
    else:
        others = [c for c in schema.get("categorical_columns", []) if c != key_roles.get("category") and 4 <= df[c].dropna().nunique() <= 50]
        if others:
            item_col = others[0]

    if not item_col or item_col not in df.columns:
        return None

    rev_col = key_roles.get("revenue")
    if rev_col and rev_col in df.columns:
        grouped = df.groupby(item_col)[rev_col].sum().sort_values(ascending=True).tail(MAX_CHART_POINTS)
        metric_label = f"Total {rev_col.replace('_', ' ').title()}"
    else:
        grouped = df[item_col].value_counts().sort_values(ascending=True).tail(MAX_CHART_POINTS)
        metric_label = "Activity Count"

    if len(grouped) < 2:
        return None

    return {
        "type": "chart",
        "category": "Leadership Ranking",
        "title": f"Top Performing {item_col.replace('_', ' ').title()}s",
        "chart_type": "bar",
        "categories": [str(c) for c in grouped.index],
        "series": [{
            "name": metric_label,
            "values": [float(round(v, 2)) for v in grouped.values],
        }],
        "legend": False,
    }


def _plan_secondary_metric(df: pd.DataFrame, key_roles: Dict[str, Any], schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build slide 6 plan: profit / secondary metric breakdown by category."""
    numeric_cols = [c for c in schema.get("numeric_columns", []) if c != key_roles.get("revenue")]
    if not numeric_cols:
        return None

    best_sec_col = None
    for kw in ["profit", "margin", "cost", "shipping", "discount", "qty", "quantity"]:
        for c in numeric_cols:
            if kw in c.lower():
                best_sec_col = c
                break
        if best_sec_col:
            break

    if not best_sec_col:
        best_sec_col = numeric_cols[0]

    cat_col = key_roles.get("category")
    if not cat_col or cat_col not in df.columns:
        cats = [c for c in schema.get("categorical_columns", []) if 2 <= df[c].dropna().nunique() <= 10]
        if cats:
            cat_col = cats[0]
        else:
            return None

    grouped = df.groupby(cat_col)[best_sec_col].mean().sort_values(ascending=False).head(MAX_CHART_POINTS)
    if len(grouped) < 2:
        return None

    return {
        "type": "chart",
        "category": "Profitability & Efficiency",
        "title": f"Average {best_sec_col.replace('_', ' ').title()} by {cat_col.replace('_', ' ').title()}",
        "chart_type": "column",
        "categories": [str(c) for c in grouped.index],
        "series": [{
            "name": f"Avg {best_sec_col}",
            "values": [float(round(v, 2)) for v in grouped.values],
        }],
        "legend": False,
    }


def _plan_recommendations(
    df: pd.DataFrame,
    key_roles: Dict[str, Any],
    schema: Dict[str, Any],
    narrative: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build slide 7 plan: evidence-based observations and recommended actions."""
    rev_col = key_roles.get("revenue")
    cat_col = key_roles.get("category")

    insights = []
    if rev_col and rev_col in df.columns:
        rev_s = df[rev_col].dropna().astype(float)
        p75 = rev_s.quantile(0.75)
        top_contrib_pct = (rev_s[rev_s >= p75].sum() / max(rev_s.sum(), 1)) * 100
        insights.append(
            f"Revenue Concentration: The top 25% highest-value entries account for {top_contrib_pct:.1f}% of total value. Prioritize high-yield opportunities while lifting baseline conversion."
        )

    if cat_col and cat_col in df.columns:
        cat_counts = df[cat_col].dropna().value_counts()
        if len(cat_counts) > 1:
            lead_c = cat_counts.index[0]
            tail_c = cat_counts.index[-1]
            insights.append(
                f"Portfolio Balancing: Category '{lead_c}' demonstrates dominant volume ({cat_counts.iloc[0]:,} records), whereas '{tail_c}' exhibits under-penetration ({cat_counts.iloc[-1]:,} records)."
            )

    missing_tot = sum(schema.get("missing_values", {}).values())
    if missing_tot > 0:
        insights.append(
            f"Data Governance: Detected {missing_tot:,} null attribute fields across the dataset. Streamlining ingestion validation will enhance downstream analytics fidelity."
        )
    else:
        insights.append(
            "Data Integrity: 100% data completeness detected across core attributes, indicating consistent reporting quality."
        )

    recommendations = [
        "Align Resource Allocation: Direct promotional and account management resources toward highest-yield segments identified in the category analysis.",
        "Operational Cadence: Track weekly performance velocity against the established multi-period trendline baseline.",
        "Continuous Data Integration: Maintain automated dataset refreshes to ensure dashboard KPIs reflect real-time operational shifts.",
    ]

    # The agent's observations and actions replace the templates when it
    # produced them; the templates stay as the fallback.
    agent_observations = (narrative or {}).get("core_empirical_observations") or []
    if agent_observations:
        insights = agent_observations

    agent_actions = (narrative or {}).get("recommended_next_actions") or []
    if agent_actions:
        recommendations = agent_actions

    return {
        "type": "insights",
        "category": "Decision Roadmap",
        "title": "Strategic Insights & Recommendations",
        "insights": insights[:4],
        "recommendations": recommendations,
    }


def apply_detail_level(plan: Dict[str, Any], detail_level: Optional[str]) -> Dict[str, Any]:
    """
    Trim a finished deck plan to the requested level of detail.

    The level decides how much a slide carries: how many findings, insights
    and recommendations it shows, how many points a chart plots, and
    whether the chart captions are kept. It is applied to the plan rather
    than to each slide builder, so it works the same whether the text came
    from the agent or from the templates.

    An unknown level falls back to "standard", so a stale setting can never
    stop a deck from being built.
    """
    level = (detail_level or DEFAULT_DETAIL_LEVEL).strip().lower()
    limits = _DETAIL_LIMITS.get(level, _DETAIL_LIMITS[DEFAULT_DETAIL_LEVEL])

    for slide in plan.get("slides", []):
        if slide.get("type") == "summary":
            slide["findings"] = slide.get("findings", [])[: limits["findings"]]
        elif slide.get("type") == "insights":
            slide["insights"] = slide.get("insights", [])[: limits["insights"]]
            slide["recommendations"] = slide.get("recommendations", [])[: limits["recommendations"]]
        elif slide.get("type") == "chart":
            if not limits["captions"]:
                slide.pop("caption", None)

            # The chart keeps its shape but plots fewer points, so a concise
            # deck is readable rather than crowded.
            #
            # Which points survive depends on the chart. A trend runs from
            # oldest to newest, so it keeps the recent end — the reader wants
            # where it is now, not where it started. A category chart is
            # sorted by size, so it keeps the top end.
            max_points = limits["chart_points"]
            categories = slide.get("categories", [])
            if len(categories) > max_points:
                is_timeline = slide.get("chart_type") == "line"
                if is_timeline:
                    slide["categories"] = categories[-max_points:]
                    for series in slide.get("series", []):
                        series["values"] = series.get("values", [])[-max_points:]
                else:
                    slide["categories"] = categories[:max_points]
                    for series in slide.get("series", []):
                        series["values"] = series.get("values", [])[:max_points]

    plan["detail_level"] = level
    return plan


def _detailed_data_slides(
    df: pd.DataFrame,
    schema: Dict[str, Any],
    key_roles: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build additional grounded slides for the detailed report level."""
    metric = key_roles.get("revenue") or key_roles.get("order_metric")
    if not metric or metric not in df.columns:
        return []
    numeric = pd.to_numeric(df[metric], errors="coerce")
    slides: List[Dict[str, Any]] = []

    categorical = [
        column for column in schema.get("categorical_columns", [])
        if column in df.columns
        and 2 <= df[column].dropna().nunique() <= 12
        and not str(column).lower().startswith("unnamed")
    ]
    for column in categorical:
        grouped = (
            pd.DataFrame({"group": df[column], "value": numeric})
            .dropna()
            .groupby("group")["value"]
            .sum()
            .sort_values(ascending=False)
        )
        if len(grouped) < 2:
            continue
        slides.append({
            "type": "chart",
            "category": "Detailed Breakdown",
            "title": f"{metric} by {column}",
            "chart_type": "column",
            "categories": [str(value) for value in grouped.index[:8]],
            "series": [{
                "name": str(metric),
                "values": [float(round(value, 2)) for value in grouped.values[:8]],
            }],
            "legend": False,
            "source_id": f"detailed-breakdown-{column}",
        })

    valid = pd.DataFrame({"row": range(len(df)), "value": numeric}).dropna()
    if len(valid) >= 2:
        top = valid.nlargest(min(5, len(valid)), "value")["value"].tolist()
        bottom = valid.nsmallest(min(5, len(valid)), "value")["value"].tolist()
        slides.append({
            "type": "insights",
            "category": "Detailed Performance",
            "title": f"Top and Bottom {metric} Performers",
            "insights": [
                f"Top values: {', '.join(f'{value:,.2f}' for value in top)}.",
                f"Bottom values: {', '.join(f'{value:,.2f}' for value in bottom)}.",
            ],
            "recommendations": [],
            "source_id": "detailed-top-bottom",
        })
        slides.append({
            "type": "insights",
            "category": "Detailed Comparison",
            "title": f"{metric} Comparison Table",
            "insights": [
                f"Maximum: {numeric.max():,.2f}",
                f"Median: {numeric.median():,.2f}",
                f"Minimum: {numeric.min():,.2f}",
                f"Range: {(numeric.max() - numeric.min()):,.2f}",
            ],
            "recommendations": [],
            "source_id": "detailed-comparison",
        })

    missing = int(df.isna().sum().sum())
    slides.append({
        "type": "insights",
        "category": "Data Quality",
        "title": "Data Quality Notes",
        "insights": [
            f"{len(df):,} rows and {len(df.columns):,} columns were analyzed.",
            f"{missing:,} missing cell values were detected.",
            f"{len(schema.get('numeric_columns', []))} numeric and {len(schema.get('categorical_columns', []))} categorical columns were profiled.",
        ],
        "recommendations": [],
        "source_id": "detailed-data-quality",
    })
    return slides


def _apply_slide_budget(
    slides: List[Dict[str, Any]],
    df: pd.DataFrame,
    schema: Dict[str, Any],
    key_roles: Dict[str, Any],
    detail_level: Optional[str],
) -> List[Dict[str, Any]]:
    """Apply the requested slide-count budget after all planning paths."""
    level = normalize_detail_level(detail_level)
    if level == "concise":
        return slides[:4]
    if level == "detailed":
        slides.extend(_detailed_data_slides(df, schema, key_roles))
        return slides[:14]
    return slides[:8]


def build_deck_plan(
    df: pd.DataFrame,
    progress: Optional[ProgressCallback] = None,
    use_agent: bool = True,
    suggestions: Optional[str] = None,
    theme: Optional[str] = None,
    detail_level: Optional[str] = None,
    current_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a JSON-serialisable description of the presentation deck.

    The slide *structure* — which slides exist and what the charts show — is
    computed deterministically. The *narrative* (the banner, the executive
    summary sections, the observations and the recommended actions) is written
    by the deck agent when one is available, and falls back to deterministic
    template text otherwise.

    Args:
        df: The dataset to describe.
        progress: Optional callback invoked as ``progress(stage, message)`` at
            each real stage of the analysis, so callers can report genuine
            progress instead of an artificial timer.
        use_agent: Set to False to skip the LLM entirely and build the deck
            from the deterministic templates.
        suggestions: Free-text instructions from the requester about how the
            narrative should read. They guide the agent's wording, emphasis
            and angle; the structure and the figures stay as computed.
        theme: The name of the theme the deck is drawn in. It is recorded on
            the plan, so the deck is rendered in that theme and the browser
            preview uses the same colours.
        detail_level: How much each slide carries — "concise", "standard" or
            "detailed".

    Returns:
        {
          "title": str,
          "slides": [ { index, type, title, ... }, ... ]
        }
    """
    report = progress or _noop_progress

    report("detecting_columns", "Detecting columns")
    schema = detect_schema(df)
    key_roles = detect_roles(df, schema)

    report("analyzing_data", "Analyzing data")
    findings = _compute_findings(df, key_roles, schema)

    # The agent writes the narrative from the data itself. The spreadsheet is
    # first converted into a compact JSON document (columns, column profiles
    # and a sample of the rows), which is what the model actually reads. It is
    # optional: without a provider, or if its answer cannot be trusted, the
    # templates below are used instead.
    narrative = None
    report("writing_narrative", "Writing the narrative")
    if use_agent:
        try:
            kpi_payload = generate_ecommerce_kpis(df, schema=schema, key_roles=key_roles)
        except Exception:  # noqa: BLE001 - the agent is a bonus, never a blocker
            logger.warning("Could not compute KPIs for the deck agent.", exc_info=True)
            kpi_payload = {}

        document = None
        try:
            document = build_dataset_document(df, schema=schema, key_roles=key_roles)
        except Exception:  # noqa: BLE001 - the agent is a bonus, never a blocker
            logger.warning("Could not build the dataset document for the deck agent.", exc_info=True)

        narrative = run_deck_agent(schema, kpi_payload, findings, document, suggestions)

    slide_plans = [
        _plan_title_and_kpis(df, key_roles, schema, narrative),
        _plan_executive_summary(df, key_roles, narrative),
        _plan_trend_analysis(df, key_roles, narrative),
        _plan_category_performance(df, key_roles, schema),
        _plan_top_items(df, key_roles, schema),
        _plan_secondary_metric(df, key_roles, schema),
        _plan_recommendations(df, key_roles, schema, narrative),
    ]

    report("generating_slides", "Generating slides")
    slides = []
    for plan in slide_plans:
        if plan is None:
            continue
        slides.append(plan)

    for index, slide in enumerate(slides, start=1):
        slide["index"] = index
        slide.setdefault("source_id", _slide_source_id(slide, index))
        slide.setdefault("category", "Executive Briefing")
        slide.setdefault("title", f"Slide {index}")

    if use_agent:
        candidate_slides = slides
        planned = _apply_ai_slide_plan(
            df,
            schema,
            slides,
            current_plan=current_plan,
            request=suggestions,
        )
        if planned:
            slides = planned
            if (
                suggestions
                and any(
                    phrase in suggestions.lower()
                    for phrase in (
                        "conclusion",
                        "final slide",
                        "final takeaway",
                        "overall takeaway",
                    )
                )
                and not any(slide.get("source_id") == "conclusion" for slide in slides)
            ):
                conclusion = _conclusion_slide(candidate_slides)
                if conclusion:
                    slides.append(conclusion)
                    slides = _apply_explicit_slide_removals(slides, suggestions)
                else:
                    slides.append({
                        "type": "insights",
                        "category": "Executive Close",
                        "title": "Conclusion",
                        "insights": [],
                        "recommendations": [],
                        "source_id": "conclusion",
                    })
            for index, slide in enumerate(slides, start=1):
                slide["index"] = index

    slides = _apply_slide_budget(slides, df, schema, key_roles, detail_level)
    for index, slide in enumerate(slides, start=1):
        slide["index"] = index

    deck_title = slides[0]["title"] if slides else "Business Performance Report"

    plan = {
        "title": deck_title,
        "subtitle": slides[0].get("subtitle", "") if slides else "",
        "slide_count": len(slides),
        "slides": slides,
    }

    # The theme and the detail level are recorded on the plan, so the
    # renderer and the browser preview both read them from one place.
    plan["theme"] = _theme_name(theme)
    plan["theme_palette"] = resolve_theme(theme)
    plan["theme_series_colors"] = [
        str(value) for value in THEME_SERIES_COLORS.get(_theme_name(theme), THEME_SERIES_COLORS[DEFAULT_THEME])
    ]
    plan = apply_detail_level(plan, detail_level)

    # Record whether the narrative came from the agent or the templates, so
    # the caller can tell the user when a provider problem silently cost
    # them the AI-written narrative.
    plan["narrative_source"] = "agent" if narrative else "template"
    if not narrative and use_agent:
        failure = deck_agent.last_failure()
        if failure:
            plan["narrative_error"] = failure.get("detail") or failure.get("reason", "")
            plan["narrative_error_reason"] = failure.get("reason", "")
    return plan


def _slide_source_id(slide: Dict[str, Any], index: int) -> str:
    """Return a stable id for a deterministic candidate slide."""
    if index == 1 or slide.get("type") == "title":
        return "title"
    return f"{slide.get('type', 'slide')}-{index}"


def _custom_chart_slide(
    df: pd.DataFrame,
    metric: str,
    group_by: str,
    chart_type: str,
    title: str,
) -> Optional[Dict[str, Any]]:
    """Build a chart plan from exact columns selected by the AI."""
    if metric not in df.columns or group_by not in df.columns:
        return None
    values = pd.to_numeric(df[metric], errors="coerce")
    groups = df[group_by]
    valid = values.notna() & groups.notna()
    if valid.sum() < 2:
        return None
    work = pd.DataFrame({"group": groups[valid].astype(str), "value": values[valid]})
    grouped = work.groupby("group", sort=False)["value"].sum().sort_values(ascending=False)
    if grouped.empty:
        return None
    chart_type = chart_type if chart_type in {"bar", "line", "column"} else "bar"
    return {
        "type": "chart",
        "category": "AI-selected Analysis",
        "title": title or f"{metric} by {group_by}",
        "chart_type": chart_type,
        "categories": [str(value) for value in grouped.head(MAX_CHART_POINTS).index],
        "series": [{
            "name": metric.replace("_", " ").title(),
            "values": [float(round(value, 2)) for value in grouped.head(MAX_CHART_POINTS).values],
        }],
        "legend": True,
        "caption": f"Computed from {metric} grouped by {group_by}.",
        "source_id": f"custom-{metric}-{group_by}-{chart_type}",
    }


def _apply_ai_slide_plan(
    df: pd.DataFrame,
    schema: Dict[str, Any],
    base_slides: List[Dict[str, Any]],
    current_plan: Optional[Dict[str, Any]],
    request: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    """Validate an AI plan and materialise only grounded slide directives."""
    available = [
        {
            "source_id": slide["source_id"],
            "type": slide.get("type"),
            "title": slide.get("title"),
            "category": slide.get("category"),
        }
        for slide in base_slides
    ]
    known_ids = {item["source_id"] for item in available}
    if current_plan:
        for slide in current_plan.get("slides", []):
            source_id = slide.get("source_id")
            if source_id and source_id not in known_ids:
                available.append({
                    "source_id": source_id,
                    "type": slide.get("type"),
                    "title": slide.get("title"),
                    "category": slide.get("category"),
                })
                known_ids.add(source_id)
    wants_conclusion = bool(
        request
        and any(
            phrase in request.lower()
            for phrase in ("conclusion", "final slide", "final takeaway", "overall takeaway")
        )
    )
    conclusion = _conclusion_slide(base_slides) if wants_conclusion else None
    if conclusion:
        available.append({
            "source_id": "conclusion",
            "type": "insights",
            "title": conclusion["title"],
            "category": conclusion["category"],
        })
    directives = run_slide_plan_agent(
        schema,
        available,
        current_plan=current_plan,
        request=request,
    )
    if not directives:
        return None

    by_id = {slide["source_id"]: slide for slide in base_slides}
    if conclusion:
        by_id["conclusion"] = conclusion
    if current_plan:
        for slide in current_plan.get("slides", []):
            source_id = slide.get("source_id")
            if source_id and source_id not in by_id:
                by_id[source_id] = dict(slide)
    columns = set(df.columns)
    result: List[Dict[str, Any]] = []
    seen = set()
    for directive in directives:
        source_id = directive["source_id"]
        if source_id == "custom":
            metric = directive.get("metric")
            group_by = directive.get("group_by")
            if metric not in columns or group_by not in columns:
                continue
            custom = _custom_chart_slide(
                df,
                metric,
                group_by,
                directive.get("chart_type", "bar"),
                directive.get("title", ""),
            )
            if custom:
                result.append(custom)
            continue
        if source_id in seen or source_id not in by_id:
            continue
        result.append(dict(by_id[source_id]))
        seen.add(source_id)

    # A valid user request for a conclusion must not depend on the model
    # choosing the optional candidate correctly.
    if conclusion and "conclusion" not in seen:
        result.append(conclusion)

    result = _apply_explicit_slide_removals(result, request)
    if result and result[0].get("source_id") != "title":
        result.insert(0, by_id["title"])

    if not result or result[0].get("source_id") != "title":
        return None
    return result


def _apply_explicit_slide_removals(
    slides: List[Dict[str, Any]],
    request: Optional[str],
) -> List[Dict[str, Any]]:
    """Honor clear delete/remove requests without allowing title deletion."""
    if not request:
        return slides
    lowered = request.lower()
    delete_markers = ("delete", "remove", "drop", "omit")
    if not any(marker in lowered for marker in delete_markers):
        return slides

    aliases = {
        "recommendations": ("recommendation", "insights"),
        "conclusion": ("conclusion",),
        "executive summary": ("executive summary",),
        "summary": ("executive summary",),
        "trend": ("trend",),
        "category": ("category",),
        "top items": ("top items",),
    }
    requested_aliases = [
        terms
        for phrase, terms in aliases.items()
        if re.search(
            rf"(?:delete|remove|drop|omit)(?:\s+\w+){{0,4}}\s+{re.escape(phrase)}",
            lowered,
        )
    ]
    def deletion_mentions(value: str) -> bool:
        return bool(
            value
            and re.search(
                rf"(?:delete|remove|drop|omit)(?:\s+\w+){{0,4}}\s+{re.escape(value)}",
                lowered,
            )
        )

    targets = []
    for slide in slides:
        source_id = str(slide.get("source_id", "")).lower()
        title = str(slide.get("title", "")).lower()
        if source_id == "title":
            continue
        alias_match = any(
            any(term in title for term in terms)
            for terms in requested_aliases
        )
        if (
            deletion_mentions(title)
            or deletion_mentions(source_id)
            or alias_match
        ):
            targets.append(slide)

    if not targets:
        return slides
    target_ids = {slide.get("source_id") for slide in targets}
    return [
        slide for slide in slides
        if slide.get("source_id") not in target_ids
        or slide.get("source_id") == "title"
    ]


def _conclusion_slide(base_slides: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Create a grounded conclusion from the generated insights slide."""
    source = next(
        (
            slide
            for slide in base_slides
            if slide.get("type") == "insights"
            or slide.get("insights")
            or slide.get("recommendations")
        ),
        None,
    )
    if not source:
        return None
    return {
        "type": "insights",
        "category": "Executive Close",
        "title": "Conclusion",
        "insights": list(source.get("insights") or [])[:5],
        "recommendations": list(source.get("recommendations") or [])[:5],
        "source_id": "conclusion",
    }


def _theme_name(theme: Optional[str]) -> str:
    """The canonical name of a theme, falling back to the default."""
    key = (theme or DEFAULT_THEME).strip().lower()
    return key if key in THEMES else DEFAULT_THEME


def normalize_theme(theme: Optional[str]) -> str:
    """
    The canonical name of a theme.

    A setting can hold a name that no longer exists — an old browser, a
    hand-edited blob — so an unknown name falls back to the default rather
    than failing the request.
    """
    return _theme_name(theme)


def normalize_detail_level(detail_level: Optional[str]) -> str:
    """The canonical detail level, falling back to the default."""
    key = (detail_level or DEFAULT_DETAIL_LEVEL).strip().lower()
    return key if key in DETAIL_LEVELS else DEFAULT_DETAIL_LEVEL


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def _hex_to_rgb(value: str) -> RGBColor:
    """Turn a ``RRGGBB`` hex string into a PowerPoint colour."""
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        text = "000000"
    try:
        return RGBColor(int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return RGBColor(0, 0, 0)


def resolve_theme(theme: Optional[str] = None) -> Dict[str, str]:
    """
    The colour set for a theme name.

    An unknown name falls back to the default theme, so a stale setting
    can never stop a deck from being built.
    """
    key = (theme or DEFAULT_THEME).strip().lower()
    return dict(THEMES.get(key, THEMES[DEFAULT_THEME]))


def theme_series_colors(theme: Optional[str] = None) -> List[RGBColor]:
    """
    The chart series colours for a theme, in the order the series are drawn.

    A theme with fewer colours than the deck has series repeats, so a
    chart with more series than the palette still gets a colour for each.
    """
    key = (theme or DEFAULT_THEME).strip().lower()
    if key not in THEMES:
        key = DEFAULT_THEME
    colors = THEME_SERIES_COLORS.get(key, THEME_SERIES_COLORS[DEFAULT_THEME])
    return [_hex_to_rgb(value) for value in colors]


def theme_palette(theme: Optional[str] = None) -> Dict[str, RGBColor]:
    """
    The colours of a theme, as PowerPoint colours.

    The renderers take this rather than reaching for the module constants,
    so a themed deck is drawn entirely in the theme's colours.
    """
    return {name: _hex_to_rgb(value) for name, value in resolve_theme(theme).items()}


def _add_slide_header(
    slide,
    title_text: str,
    category_text: str = "EXECUTIVE BRIEFING",
    palette: Optional[Dict[str, RGBColor]] = None,
):
    """Adds a standard clean header to content slides."""
    colors = palette or theme_palette()
    tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.5), Inches(0.3))
    tf_tag = tag_box.text_frame
    tf_tag.word_wrap = True
    p_tag = tf_tag.paragraphs[0]
    p_tag.text = category_text.upper()
    p_tag.font.name = FONT_BODY
    p_tag.font.size = Pt(10)
    p_tag.font.bold = True
    p_tag.font.color.rgb = colors["primary"]

    title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(11.5), Inches(0.6))
    tf_title = title_box.text_frame
    tf_title.word_wrap = True
    p_title = tf_title.paragraphs[0]
    p_title.text = title_text
    p_title.font.name = FONT_HEADING
    p_title.font.size = Pt(22)
    p_title.font.bold = True
    p_title.font.color.rgb = colors["text_main"]


def _render_title_slide(prs: Presentation, plan: Dict[str, Any], palette=None):
    """Slide 1: Dataset/business title, subtitle, KPI cards and highlight banner."""
    colors = palette or theme_palette()
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)

    top_bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_WIDTH_EMU, Inches(0.12)
    )
    top_bar.fill.solid()
    top_bar.fill.fore_color.rgb = colors["primary"]
    top_bar.line.fill.background()

    tb = slide.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(11.5), Inches(1.5))
    tf = tb.text_frame
    tf.word_wrap = True

    p1 = tf.paragraphs[0]
    p1.text = plan["title"]
    p1.font.name = FONT_HEADING
    p1.font.size = Pt(28)
    p1.font.bold = True
    p1.font.color.rgb = colors["text_main"]

    p2 = tf.add_paragraph()
    p2.text = plan.get("subtitle", "")
    p2.font.name = FONT_BODY
    p2.font.size = Pt(12)
    p2.font.color.rgb = colors["text_muted"]

    kpi_tiles = plan.get("kpis", [])[:4]
    card_count = len(kpi_tiles)
    card_width = Inches(2.65)
    gap = Inches(0.35)
    start_x = Inches(0.8)
    start_y = Inches(2.5)
    card_height = Inches(2.0)

    for i, kpi in enumerate(kpi_tiles):
        x = start_x + (i * (card_width + gap))
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, start_y, card_width, card_height)
        card.fill.solid()
        card.fill.fore_color.rgb = colors["card_bg"]
        card.line.color.rgb = colors["border"]
        card.line.width = Pt(1)

        ctb = slide.shapes.add_textbox(x + Inches(0.2), start_y + Inches(0.25), card_width - Inches(0.4), card_height - Inches(0.5))
        ctf = ctb.text_frame
        ctf.word_wrap = True

        cp1 = ctf.paragraphs[0]
        cp1.text = str(kpi.get("label", "")).upper()
        cp1.font.name = FONT_BODY
        cp1.font.size = Pt(9.5)
        cp1.font.bold = True
        cp1.font.color.rgb = colors["text_muted"]

        cp2 = ctf.add_paragraph()
        cp2.text = str(kpi.get("value", "—"))
        cp2.font.name = FONT_HEADING
        cp2.font.size = Pt(22)
        cp2.font.bold = True
        cp2.font.color.rgb = colors["primary"]
        cp2.space_before = Pt(8)

        cp3 = ctf.add_paragraph()
        cp3.text = str(kpi.get("caption", "Verified from active dataset"))
        cp3.font.name = FONT_BODY
        cp3.font.size = Pt(9)
        cp3.font.color.rgb = colors["text_muted"]
        cp3.space_before = Pt(4)

    bb = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(4.9), Inches(11.7), Inches(1.8))
    bb.fill.solid()
    bb.fill.fore_color.rgb = colors["bg_dark"]
    bb.line.fill.background()

    btb = slide.shapes.add_textbox(Inches(1.1), Inches(5.1), Inches(11.1), Inches(1.4))
    btf = btb.text_frame
    btf.word_wrap = True
    bp1 = btf.paragraphs[0]
    bp1.text = str(plan.get("banner_label", "Executive Summary Highlight")).upper()
    bp1.font.name = FONT_BODY
    bp1.font.size = Pt(10)
    bp1.font.bold = True
    bp1.font.color.rgb = colors["secondary"]

    bp2 = btf.add_paragraph()
    bp2.text = plan.get("banner_text", "")
    bp2.font.name = FONT_BODY
    bp2.font.size = Pt(11)
    bp2.font.color.rgb = colors["on_dark"]
    bp2.space_before = Pt(6)


def _render_summary_slide(prs: Presentation, plan: Dict[str, Any], palette=None):
    """Slide 2: Data-derived key findings rendered as modern cards."""
    colors = palette or theme_palette()
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)
    _add_slide_header(
        slide, plan["title"], plan.get("category", "Executive Briefing"), colors
    )

    start_y = Inches(1.5)
    card_h = Inches(1.15)
    gap = Inches(0.2)

    for i, finding in enumerate(plan.get("findings", [])[:4]):
        y = start_y + (i * (card_h + gap))
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), y, Inches(11.7), card_h)
        card.fill.solid()
        card.fill.fore_color.rgb = colors["card_bg"]
        card.line.color.rgb = colors["border"]
        card.line.width = Pt(1)

        pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), y + Inches(0.2), Inches(0.08), card_h - Inches(0.4))
        pill.fill.solid()
        pill.fill.fore_color.rgb = colors["primary"]
        pill.line.fill.background()

        tb = slide.shapes.add_textbox(Inches(1.15), y + Inches(0.12), Inches(11.2), card_h - Inches(0.24))
        tf = tb.text_frame
        tf.word_wrap = True

        p1 = tf.paragraphs[0]
        p1.text = finding["title"]
        p1.font.name = FONT_HEADING
        p1.font.size = Pt(13)
        p1.font.bold = True
        p1.font.color.rgb = colors["text_main"]

        p2 = tf.add_paragraph()
        p2.text = finding["desc"]
        p2.font.name = FONT_BODY
        p2.font.size = Pt(11)
        p2.font.color.rgb = colors["text_muted"]
        p2.space_before = Pt(3)


def _render_chart_slide(prs: Presentation, plan: Dict[str, Any], palette=None, series_colors=None):
    """Slide with a native, editable PowerPoint chart."""
    colors = palette or theme_palette()
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)
    _add_slide_header(slide, plan["title"], plan.get("category", "Analysis"), colors)

    chart_data = CategoryChartData()
    chart_data.categories = [str(c) for c in plan.get("categories", [])]
    for series in plan.get("series", []):
        chart_data.add_series(series["name"], tuple(float(v) for v in series["values"]))

    chart_type = _CHART_TYPES.get(plan.get("chart_type", "column"), XL_CHART_TYPE.COLUMN_CLUSTERED)

    # A caption (the agent's reading of the trend) shrinks the chart a little
    # so the two never overlap.
    caption = str(plan.get("caption", "") or "").strip()
    x, y, cx, cy = Inches(0.8), Inches(1.5), Inches(11.7), Inches(5.2)
    if caption:
        cy = Inches(4.7)

    chart = slide.shapes.add_chart(chart_type, x, y, cx, cy, chart_data).chart

    # The series are drawn in the theme's colours rather than PowerPoint's
    # defaults, so the chart in the file is the chart in the preview.
    if series_colors is None:
        series_colors = theme_series_colors()
    for index, plot_series in enumerate(chart.series):
        color = series_colors[index % len(series_colors)]
        plot_series.format.fill.solid()
        plot_series.format.fill.fore_color.rgb = color
        plot_series.format.line.color.rgb = color

    if plan.get("legend"):
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.TOP
        chart.legend.include_in_layout = False
    else:
        chart.has_legend = False

    if caption:
        ctb = slide.shapes.add_textbox(Inches(0.8), Inches(6.35), Inches(11.7), Inches(0.5))
        ctf = ctb.text_frame
        ctf.word_wrap = True
        cp = ctf.paragraphs[0]
        cp.text = caption
        cp.font.name = FONT_BODY
        cp.font.size = Pt(11)
        cp.font.italic = True
        cp.font.color.rgb = colors["text_muted"]


def _render_insights_slide(prs: Presentation, plan: Dict[str, Any], palette=None):
    """Slide: two-column empirical observations and recommended actions."""
    colors = palette or theme_palette()
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)
    _add_slide_header(
        slide, plan["title"], plan.get("category", "Decision Roadmap"), colors
    )

    col_width = Inches(5.7)
    height = Inches(5.0)

    ib = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.5), col_width, height)
    ib.fill.solid()
    ib.fill.fore_color.rgb = colors["card_bg"]
    ib.line.color.rgb = colors["border"]
    ib.line.width = Pt(1)

    itb = slide.shapes.add_textbox(Inches(1.0), Inches(1.7), col_width - Inches(0.4), height - Inches(0.4))
    itf = itb.text_frame
    itf.word_wrap = True

    ip0 = itf.paragraphs[0]
    ip0.text = "CORE EMPIRICAL OBSERVATIONS"
    ip0.font.name = FONT_HEADING
    ip0.font.size = Pt(12)
    ip0.font.bold = True
    ip0.font.color.rgb = colors["primary"]

    for obs in plan.get("insights", [])[:4]:
        p = itf.add_paragraph()
        p.text = f"• {obs}"
        p.font.name = FONT_BODY
        p.font.size = Pt(11)
        p.font.color.rgb = colors["text_main"]
        p.space_before = Pt(12)

    rb = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.8), Inches(1.5), col_width, height)
    rb.fill.solid()
    rb.fill.fore_color.rgb = colors["bg_dark"]
    rb.line.fill.background()

    rtb = slide.shapes.add_textbox(Inches(7.0), Inches(1.7), col_width - Inches(0.4), height - Inches(0.4))
    rtf = rtb.text_frame
    rtf.word_wrap = True

    rp0 = rtf.paragraphs[0]
    rp0.text = "RECOMMENDED NEXT ACTIONS"
    rp0.font.name = FONT_HEADING
    rp0.font.size = Pt(12)
    rp0.font.bold = True
    rp0.font.color.rgb = colors["secondary"]

    for rec in plan.get("recommendations", [])[:4]:
        p = rtf.add_paragraph()
        p.text = f"→ {rec}"
        p.font.name = FONT_BODY
        p.font.size = Pt(11)
        p.font.color.rgb = colors["on_dark"]
        p.space_before = Pt(12)


def render_deck(prs: Presentation, plan: Dict[str, Any]) -> Presentation:
    """
    Materialise a deck plan into PowerPoint slides on the given presentation.

    The theme recorded on the plan decides the colours: the plan carries
    it, so a deck that is edited and re-rendered keeps the theme it was
    built with, without the caller having to pass it again.
    """
    colors = theme_palette(plan.get("theme"))
    series_colors = theme_series_colors(plan.get("theme"))

    renderers = {
        "title": _render_title_slide,
        "summary": _render_summary_slide,
        "chart": _render_chart_slide,
        "insights": _render_insights_slide,
    }

    for slide_plan in plan.get("slides", []):
        renderer = renderers.get(slide_plan.get("type"))
        if renderer is None:
            continue
        if renderer is _render_chart_slide:
            renderer(prs, slide_plan, colors, series_colors)
        else:
            renderer(prs, slide_plan, colors)

    return prs


# ---------------------------------------------------------------------------
# Main Generator Flow
# ---------------------------------------------------------------------------

def render_plan_to_pptx(plan: Dict[str, Any], output_path: Union[str, Path]) -> str:
    """
    Materialise an existing deck plan into a .pptx file.

    This is the second half of :func:`generate_presentation_with_plan`, split
    out so a plan that the requester has edited can be written to a file
    without re-running the analysis or the agent. The plan is rendered
    exactly as it would have been the first time, so the edited file matches
    the preview on screen.

    The plan is also written alongside the .pptx as a sidecar JSON file, so
    the deck can be found and edited again later — even after the server has
    restarted and the in-memory job registry is gone.

    Args:
        plan: The deck plan to render.
        output_path: Destination path for the .pptx file.

    Returns:
        The path of the written file, as a string.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    prs = Presentation()
    prs.core_properties.title = "Datalogue Analytics Report"
    prs.core_properties.subject = "Data analysis and business insights"
    prs.core_properties.author = "Datalogue"
    prs.core_properties.last_modified_by = "Datalogue"
    prs.core_properties.keywords = "Datalogue, analytics, data"
    prs.slide_width = SLIDE_WIDTH_EMU
    prs.slide_height = SLIDE_HEIGHT_EMU
    render_deck(prs, plan)
    prs.save(str(path))

    save_deck_plan(plan, path)

    logger.info("Rendered PowerPoint presentation with %d slides at: %s", len(prs.slides), path)
    return str(path)


def deck_plan_path(pptx_path: Union[str, Path]) -> Path:
    """The path of the sidecar plan file that belongs to a .pptx file."""
    path = Path(pptx_path)
    return path.with_suffix(".plan.json")


def save_deck_plan(plan: Dict[str, Any], pptx_path: Union[str, Path]) -> Path:
    """
    Write the deck plan next to its .pptx file, as a sidecar JSON file.

    The sidecar is what lets a deck be edited again after the fact: the
    .pptx alone holds the rendered slides, not the plan they came from.

    Returns:
        The path of the sidecar file.
    """
    target = deck_plan_path(pptx_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, default=str), encoding="utf-8")
    return target


def load_deck_plan(pptx_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """
    Read the plan of a deck from its sidecar file.

    Returns None when the sidecar is missing or unreadable, so a caller can
    tell the difference between "this deck cannot be edited" and "this deck
    has no edits yet".
    """
    target = deck_plan_path(pptx_path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Could not read the deck plan at %s", target, exc_info=True)
        return None


def generate_presentation(df: pd.DataFrame, output_path: Union[str, Path]) -> str:
    """
    Generate an editable PowerPoint presentation from a pandas DataFrame.

    Saves the .pptx presentation to `output_path` and returns the file path as string.
    """
    path, _ = generate_presentation_with_plan(df, output_path)
    return path


def generate_presentation_with_plan(
    df: pd.DataFrame,
    output_path: Union[str, Path],
    progress: Optional[ProgressCallback] = None,
    use_agent: bool = True,
    suggestions: Optional[str] = None,
    theme: Optional[str] = None,
    detail_level: Optional[str] = None,
    current_plan: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate the .pptx and return both the file path and the deck plan that
    describes it. The plan powers the in-browser slide preview.

    Args:
        df: The dataset to present.
        output_path: Destination path for the .pptx file.
        progress: Optional callback invoked as ``progress(stage, message)`` at
            each real stage of the pipeline.
        use_agent: Set to False to skip the LLM and build the deck from the
            deterministic templates.
        suggestions: Free-text instructions from the requester about how the
            narrative should read. They are passed to the deck agent.
        theme: The name of the theme the deck is drawn in.
        detail_level: How much each slide carries.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    report = progress or _noop_progress

    plan = build_deck_plan(
        df,
        progress=progress,
        use_agent=use_agent,
        suggestions=suggestions,
        theme=theme,
        detail_level=detail_level,
        current_plan=current_plan,
    )

    report("preparing_powerpoint", "Preparing PowerPoint")
    prs = Presentation()
    prs.core_properties.title = "Datalogue Analytics Report"
    prs.core_properties.subject = "Data analysis and business insights"
    prs.core_properties.author = "Datalogue"
    prs.core_properties.last_modified_by = "Datalogue"
    prs.core_properties.keywords = "Datalogue, analytics, data"
    prs.slide_width = SLIDE_WIDTH_EMU
    prs.slide_height = SLIDE_HEIGHT_EMU
    render_deck(prs, plan)
    prs.save(str(path))

    # The plan is written next to the file so the deck can be edited again
    # later, even after the server has restarted.
    save_deck_plan(plan, path)

    logger.info("Generated PowerPoint presentation with %d slides at: %s", len(prs.slides), path)
    return str(path), plan
