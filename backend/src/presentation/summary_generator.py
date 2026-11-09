"""Generates AI-powered natural language summaries of a dataset."""

import json
import logging
from typing import Any, Dict

import pandas as pd

from src.presentation.kpi_generator import generate_kpis
from src.core.llm import LLMError, generate_response
from src.ingestion.schema_detector import detect_schema

logger = logging.getLogger(__name__)

SUMMARY_SECTIONS = ("executive_summary", "key_insights", "trends", "recommendations")


def _build_prompt(schema: Dict[str, Any], kpis: Dict[str, Any]) -> str:
    """Build a business-analysis prompt from schema and KPI data."""
    return (
        "You are a data analyst producing a business report for a dataset. "
        "Using ONLY the structured information below, respond with a single "
        "JSON object with exactly these keys: \"executive_summary\" (a short "
        "string), \"key_insights\" (array of strings), \"trends\" (array of "
        "strings), and \"recommendations\" (array of strings). Do not "
        "include any text outside the JSON object.\n\n"
        f"Dataset schema:\n{json.dumps(schema, default=str)}\n\n"
        f"Dataset KPIs:\n{json.dumps(kpis, default=str)}\n"
    )


def _strip_code_fence(raw_response: str) -> str:
    """Remove a surrounding markdown code fence (e.g. ```json ... ```) if present."""
    cleaned = raw_response.strip().strip("`").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[len("json"):].strip()
    return cleaned


def _parse_llm_response(raw_response: str) -> Dict[str, Any]:
    """Parse the LLM's JSON response, falling back to a raw-text summary on failure."""
    try:
        parsed = json.loads(_strip_code_fence(raw_response))
        return {section: parsed.get(section) for section in SUMMARY_SECTIONS}
    except (json.JSONDecodeError, AttributeError):
        logger.warning("Failed to parse LLM response as JSON; returning raw text fallback.")
        return {
            "executive_summary": raw_response.strip(),
            "key_insights": [],
            "trends": [],
            "recommendations": [],
        }


def generate_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate a structured AI summary for the given DataFrame.

    Returns a dict with "executive_summary", "key_insights", "trends", and
    "recommendations". On LLM failure, returns the same shape populated
    with empty values plus an "error" field.
    """
    schema = detect_schema(df)
    kpis = generate_kpis(df)
    prompt = _build_prompt(schema, kpis)

    try:
        raw_response = generate_response(prompt)
    except LLMError as exc:
        logger.error("Summary generation failed: %s", exc)
        return {
            "executive_summary": None,
            "key_insights": [],
            "trends": [],
            "recommendations": [],
            "error": str(exc),
        }

    summary = _parse_llm_response(raw_response)
    logger.info("Generated AI summary for dataset with %d rows.", schema["total_rows"])
    return summary
